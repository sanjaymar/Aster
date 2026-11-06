"""Publish compact experiment results; never generate extra documentation files."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from aster.data.sources import save_json, utc_now
from aster.evaluation.benchmarks import read_benchmarks

ROOT = Path(__file__).resolve().parents[2]


def publish(finished=False):
    reports = {}
    groups = [
        ("run-20261105", ["intent", "rewrite"]),
        (
            "gpu-20261105",
            [
                "retrieval",
                "boundary",
                "boundary-no-reflect",
                "dialogues",
                "dialogues-no-rewrite",
                "dialogues-no-reflect",
                "dialogues-no-rerank",
                "dialogues-no-memory",
                "memory",
                "ablations",
            ],
        ),
    ]
    for folder, names in groups:
        for name in names:
            path = ROOT / ".local/metabolomics/evaluation" / folder / f"{name}.json"
            if not path.exists():
                reports[name] = {"status": "pending", "cases": 0}
                continue
            data = json.loads(path.read_text())
            reports[name] = {
                key: value for key, value in data.items() if key not in {"rows", "evaluation_id"}
            }
            reports[name].update(
                cases=len(data.get("rows", [])),
                local_report=str(path.relative_to(ROOT)),
                report_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            if name == "ablations":
                reports[name]["comparisons"] = data["rows"]
    complete = all(row["status"] == "complete" for row in reports.values())
    report = {
        "updated_at": utc_now(),
        "status": "complete" if complete else "incomplete" if finished else "running",
        "annotation": "author/model-assisted draft labels; pending independent human review",
        "baseline": "2026-11-05 grounded QA; discussion mode requires separate validation",
        "reports": reports,
        "benchmarks": read_benchmarks(ROOT / "jobs"),
        "citation_semantic_accuracy": None,
        "citation_review_status": "pending independent human review",
    }
    save_json(ROOT / "eval/results/metabolomics-2026-11-05.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "progress": {key: row["cases"] for key, row in reports.items()},
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch-pid", type=int)
    args = parser.parse_args()
    publish()
    if args.watch_pid:
        while True:
            try:
                os.kill(args.watch_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(30)
        publish(finished=True)


if __name__ == "__main__":
    main()
