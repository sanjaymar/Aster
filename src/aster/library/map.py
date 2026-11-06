"""A reproducible lexical map, derived from current papers rather than a static graph."""

from collections import Counter
import hashlib
import json
import re
import threading

import numpy as np
from sqlalchemy import select
from aster.domain.models import SourceSpan
from aster.library.topics import group

LOCK = threading.Lock()
STOP = set(
    "the and for with that this from were was are has have had not also can using used use study studies results analysis data based method methods our their these those into between its which through shown figure table supplementary abstract introduction doi license source full text xml converted pages page numbers article rights reserved author authors copyright available pmc europe journal et al may more two one each than both been".split()
)
STOP.update(
    "licence licensed you your permission permissions credit creative commons attribution international commercial noncommercial derivative derivatives adaptation distribution reproduction publisher published publishing springer nature elsevier scientific reports received accepted revised correspondence corresponding email mail address affiliated affiliation department university institute hospital city country fig figs version peer review reviewed preprint biorxiv medrxiv access open http https www org com retrieved volume issue download online electronic supplementary material materials author manuscript final citation cite funding funded foundation grant acknowledgments acknowledgment disclosure conflict interests competing declared declaration consent ethics committee approval approved under provided unless otherwise indicated third party included permitted obtain visit copy terms conditions content link images image processing charge".split()
)


def terms(text):
    return [
        t
        for t in re.findall(r"[a-z][a-z0-9-]{2,}|[\u3400-\u9fff]{2,6}", text.lower())
        if t not in STOP
    ]


def build_map(service, project_id):
    sources = sorted(service.sources(project_id), key=lambda s: s["id"])
    records = [r for r in service.artifacts(project_id) if r["kind"] == "note"]
    signature = hashlib.blake2b(
        json.dumps(
            {
                "papers": sources,
                "notes": [(r["id"], r["revision"]) for r in records],
                "method": "paper-topics",
            },
            sort_keys=True,
            default=str,
        ).encode(),
        digest_size=16,
    ).hexdigest()
    cache = service.db.data_dir / "cache" / "maps" / f"{project_id}.json"
    with LOCK:
        if cache.exists():
            try:
                stored = json.loads(cache.read_text())
            except (OSError, ValueError):
                stored = {}
            if isinstance(stored, dict) and stored.get("revision") == signature:
                return stored
        nodes, documents = [], []
        with service.db.session() as session:
            for source in sources:
                spans = list(
                    session.scalars(
                        select(SourceSpan)
                        .where(SourceSpan.source_version_id == source["version_id"])
                        .order_by(SourceSpan.page)
                        .limit(2)
                    )
                )
                text = " ".join(s.text for s in spans)[:9000]
                related_notes = [
                    r
                    for r in records
                    if source["id"] == r["version"]["fields"].get("source_id")
                    or source["id"] in r["version"]["fields"].get("source_ids", [])
                ]
                abstract = source.get("provenance", {}).get("abstract", "")
                match = re.search(
                    r"\babstract\b(.+?)(?:\bintroduction\b|\bkeywords?\b|$)", text, re.I | re.S
                )
                summary = abstract or (match.group(1) if match else text)
                documents.append(Counter(terms((source["title"] + " ") * 4 + summary)))
                nodes.append(
                    {
                        "id": source["id"],
                        "title": source["title"],
                        "year": source["year"],
                        "doi": source["doi"],
                        "journal": source.get("provenance", {}).get("journal", ""),
                        "abstract": source.get("provenance", {}).get("abstract") or text[:1800],
                        "authors": source.get("authors", ""),
                        "reading_status": source.get("reading", {}).get("reading_status", "unread"),
                        "starred": source.get("reading", {}).get("starred", False),
                        "notes": [{"id": r["id"], "title": r["title"]} for r in related_notes],
                        "tags": source.get("reading", {}).get("tags", []),
                        "x": 0.0,
                        "y": 0.0,
                        "keywords": [],
                    }
                )
        count = len(nodes)
        frequencies = Counter(t for document in documents for t in document)
        vocabulary = [t for t, n in frequencies.most_common(2500) if n <= max(2, count * 0.65)]
        matrix = np.zeros((count, len(vocabulary)), dtype=np.float64)
        for i, document in enumerate(documents):
            for j, term in enumerate(vocabulary):
                if document[term]:
                    matrix[i, j] = (1 + np.log(document[term])) * np.log(
                        1 + count / (1 + frequencies[term])
                    )
            nodes[i]["keywords"] = [
                vocabulary[j] for j in np.argsort(-matrix[i])[:4] if matrix[i, j] > 0
            ]
        if count and vocabulary:
            matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)
        similarity = matrix @ matrix.T
        topics = group(matrix, vocabulary, nodes)
        edges = {}
        for i, node in enumerate(nodes):
            for j in np.argsort(-similarity[i]):
                if int(j) == i or similarity[i, j] < 0.18:
                    continue
                key = tuple(sorted((i, int(j))))
                edges[key] = {
                    "source": nodes[key[0]]["id"],
                    "target": nodes[key[1]]["id"],
                    "score": round(float(similarity[i, j]), 3),
                }
                if sum(i in pair for pair in edges) >= 3:
                    break
        value = {
            "revision": signature,
            "method": "标题与前两页 · TF-IDF / 余弦聚类 · 主题分组",
            "relation": "主题相似，不代表引用关系或生物学作用",
            "nodes": nodes,
            "edges": list(edges.values()),
            "topics": topics,
            "stats": {
                "papers": count,
                "notes": len(records),
                "read": sum(n["reading_status"] == "read" for n in nodes),
                "topics": len(topics),
            },
        }
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False))
        temporary.replace(cache)
        return value
