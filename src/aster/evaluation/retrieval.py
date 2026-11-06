"""Reproducible retrieval ablations; weak-label reports never masquerade as QA accuracy."""

import hashlib
import importlib.metadata
import json
import re
import time
from pathlib import Path

from aster.retrieval.corpus import CHUNKER
from aster.domain.models import EvaluationRun, AppSetting
from aster.domain.service import Problem, plain


def normalize(text):
    return re.sub(r"[^a-z0-9\u3400-\u9fff]", "", text.lower())


def ingest_public_corpus(service, papers_dir):
    papers_dir = Path(papers_dir)
    manifest = json.loads((papers_dir / "manifest.json").read_text())
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    key = "eval-corpus:" + fingerprint[:32]
    with service.db.session() as s:
        previous = s.get(AppSetting, key)
        if previous:
            return previous.value
    project = service.save_project("公开检索论文 · 独立评测示例", manifest["description"])
    mapping = {}
    for paper in manifest["papers"]:
        path = papers_dir / paper["filename"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != paper["sha256"]:
            raise Problem("评测论文文件校验失败")
        source = service.import_source(
            project["id"],
            path.name,
            data,
            title=paper["title"],
            year=str(2000 + int(paper["arxiv"][:2])),
        )
        mapping[paper["key"]] = source["id"]
    value = {
        "project_id": project["id"],
        "sources": mapping,
        "manifest_sha256": fingerprint,
        "corpus_name": manifest["name"],
        "paper_count": len(mapping),
    }
    with service.db.session() as s:
        s.merge(AppSetting(key=key, value=value))
    return value


def retrieval_metrics(ranking, gold):
    relevant = set(gold)
    if not relevant:
        raise ValueError("gold evidence cannot be empty")
    return {
        "recall@5": len(set(ranking[:5]) & relevant) / len(relevant),
        "recall@10": len(set(ranking[:10]) & relevant) / len(relevant),
        "hit@5": float(bool(set(ranking[:5]) & relevant)),
        "mrr@10": next((1 / (i + 1) for i, key in enumerate(ranking[:10]) if key in relevant), 0.0),
    }


def evaluate_retrieval(retriever, project_id, dataset_path, source_mapping, strategies=None):
    dataset_path = Path(dataset_path)
    raw = dataset_path.read_bytes()
    dataset = json.loads(raw)
    snapshot = retriever.corpus.snapshot(project_id, scope="project")
    items = retriever.corpus.items(project_id, snapshot)
    labels = {}
    missing = []
    for case in dataset["cases"]:
        expected = source_mapping.get(case["paper"], case["paper"])
        anchors = [normalize(a) for a in case["anchors"]]
        labels[case["id"]] = [
            i.id
            for i in items
            if i.source_id == expected
            and i.page <= case.get("max_gold_page", 6)
            and any(a in normalize(i.text) for a in anchors)
        ]
        if not labels[case["id"]]:
            missing.append(case["id"])
    if missing:
        raise Problem("以下评测锚点未匹配到原文，请先检查标注：" + ", ".join(missing))
    configurations = {
        "bm25": ("bm25", False),
        "dense": ("dense", False),
        "hybrid": ("hybrid", False),
        "hybrid-rerank": ("hybrid", True),
    }
    strategies = strategies or list(configurations)
    results = []
    metrics = {}
    for label in strategies:
        strategy, rerank = configurations[label]
        rows = []
        for case in dataset["cases"]:
            start = time.perf_counter()
            hits, meta = retriever.search(
                project_id, snapshot, case["query"], top_k=10, strategy=strategy, rerank=rerank
            )
            ranking = [h.evidence.id for h in hits]
            row = {
                "case_id": case["id"],
                "query": case["query"],
                "gold": labels[case["id"]],
                "ranking": ranking,
                "metrics": retrieval_metrics(ranking, labels[case["id"]]),
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                "retrieval": meta,
            }
            rows.append(row)
        aggregate = {k: sum(r["metrics"][k] for r in rows) / len(rows) for k in rows[0]["metrics"]}
        aggregate["mean_ms"] = sum(r["duration_ms"] for r in rows) / len(rows)
        aggregate["cases"] = len(rows)
        metrics[label] = aggregate
        results.append({"strategy": label, "cases": rows})
    config = {
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "annotation": dataset.get("annotation", "user_supplied"),
        "gold_rule": "chunk contains annotated anchor, matching source, within first six pages unless specified",
        "corpus": snapshot,
        "chunker": CHUNKER,
        "models": retriever.models.fingerprint(),
        "retrieval_status": retriever.status(),
        "strategies": strategies,
        "versions": {name: importlib.metadata.version(name) for name in ["numpy", "sqlalchemy"]},
    }
    with retriever.db.session() as s:
        row = EvaluationRun(
            project_id=project_id,
            dataset=dataset["name"],
            config=config,
            metrics=metrics,
            results=results,
        )
        s.add(row)
        s.flush()
        return plain(row)
