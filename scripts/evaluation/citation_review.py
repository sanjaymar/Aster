"""Export final-answer citations for independent review; score only explicit labels.

A reviewer must read both claim and cited text. Empty labels are never counted as
correct. This tool deliberately does not use the answer-generating model as gold.
"""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from collections import Counter

from aster.storage.database import Database
from aster.domain.service import Service, CITATION
from aster.app.settings import Settings
from aster.retrieval.corpus import Corpus

FIELDS = [
    "review_id",
    "case_id",
    "run_id",
    "claim",
    "answer",
    "source_title",
    "evidence",
    "supported",
    "reviewer",
    "reason",
]


def score_reviews(rows):
    allowed = {"", "yes", "no", "uncertain"}
    if any(row.get("supported", "") not in allowed for row in rows):
        raise ValueError("supported must be yes, no, uncertain, or empty")
    ids = [row["review_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate review_id")
    labelled = [row for row in rows if row.get("supported")]
    if any(not row.get("reviewer", "").strip() for row in labelled):
        raise ValueError("Labelled rows require a reviewer identity")
    labels = Counter(row["supported"] for row in labelled)
    return {
        "total_citations": len(rows),
        "reviewed": len(labelled),
        "coverage": len(labelled) / len(rows) if rows else None,
        "supported": labels["yes"],
        "unsupported": labels["no"],
        "uncertain": labels["uncertain"],
        "reviewed_citation_support_accuracy": labels["yes"] / len(labelled) if labelled else None,
        "scope": "independent review of whether each cited passage supports its associated claim; uncertain is not correct",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", help="Pipeline report containing final answers and citations")
    parser.add_argument("--export", help="New CSV file; existing annotations are never overwritten")
    parser.add_argument("--score", help="Annotated CSV to score")
    args = parser.parse_args()
    if args.score:
        path = Path(args.score)
        with path.open(encoding="utf-8-sig", newline="") as file:
            result = score_reviews(list(csv.DictReader(file)))
        result["annotation_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not args.report or not args.export:
        parser.error("Use --report REPORT --export NEW.csv or --score ANNOTATED.csv")
    settings = Settings.from_env()
    db = Database(settings.database_url, settings.data_dir)
    corpus = Corpus(Service(db))
    report = json.loads(Path(args.report).read_text())
    project_id = (
        report.get("corpus_project_id")
        or json.loads((settings.data_dir / "experiments/qa/corpus/imported.json").read_text())[
            "papers"
        ]["project_id"]
    )
    snapshot = corpus.snapshot(project_id, scope="project")
    by_id = {item.id: item for item in corpus.items(project_id, snapshot)}
    with Path(args.export).open("x", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for row in report["rows"]:
            for part, paragraph in enumerate(re.split(r"\n\s*\n", row.get("answer", ""))):
                refs = list(dict.fromkeys(CITATION.findall(paragraph)))
                for kind, key in refs:
                    evidence = by_id.get(key) if kind == "C" else None
                    writer.writerow(
                        {
                            "review_id": f"{row['case_id']}:{kind}:{key}:{part}",
                            "case_id": row["case_id"],
                            "run_id": row.get("run_id", ""),
                            "claim": CITATION.sub("", paragraph).removeprefix("- ").strip(),
                            "answer": row.get("answer", ""),
                            "source_title": evidence.title if evidence else "",
                            "evidence": evidence.text if evidence else "",
                        }
                    )
    db.engine.dispose()


if __name__ == "__main__":
    main()
