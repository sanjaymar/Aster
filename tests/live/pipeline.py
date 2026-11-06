"""Small real-Qwen flow regression. Requires downloaded eval PDFs and a local model.

Run: .venv/bin/python tests/live/pipeline.py [--backend auto|lexical]
This checks engineering behavior, not independently annotated answer correctness.
"""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from aster.storage.database import Database
from aster.evaluation.retrieval import ingest_public_corpus
from aster.domain.models import AgentRun, PipelineStage, AnswerClaim, MemorySnapshot
from aster.app.runtime import RunManager
from aster.domain.schemas import RunInput
from aster.domain.service import Service, plain
from aster.app.settings import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["auto", "lexical"], default="auto")
    parser.add_argument("--output", default=".local/evaluation/live-pipeline-report.json")
    parser.add_argument("--resume", help="复验失败项，保留已通过项与原始失败尝试")
    args = parser.parse_args()
    root = Path(".local/evaluation/live-pipeline").resolve()
    db = Database(f"sqlite:///{root / 'live.db'}", root)
    db.migrate()
    service = Service(db)
    corpus = ingest_public_corpus(service, ".local/evaluation/papers")
    manager = RunManager(service, replace(Settings.from_env(), retrieval_mode=args.backend))
    manager.save_model_settings({**manager.model_settings(), "max_tokens": 1400, "timeout": 600})
    sources = [corpus["sources"][key] for key in ["dpr", "colbert"]]
    cases = [
        (
            "lookup",
            "DPR 论文的核心检索方法是什么？只说明论文明确报告的方法，不推测效果。回答不超过150字。",
            "answer",
            True,
        ),
        (
            "followup",
            "它与 BM25 的表示方式有什么区别？请延续刚才的要求，回答不超过150字。",
            "answer",
            True,
        ),
        (
            "insufficient",
            "DPR 在2026年新冠患者临床试验中的存活率是多少？请给出该研究报告的具体数值。",
            "refuse",
            True,
        ),
        ("ambiguous", "它和另一个方法相比怎么样？", "clarify", False),
        ("boundary", "今天北京天气怎么样，适合出去玩吗？", "refuse", False),
    ]
    previous = json.loads(Path(args.resume).read_text()) if args.resume else {}
    rows = [r for r in previous.get("cases", []) if r["behavior_pass"]]
    previous_attempts = previous.get("previous_attempts", []) + [
        r for r in previous.get("cases", []) if not r["behavior_pass"]
    ]
    conversation = next((r["conversation_id"] for r in rows if r["case_id"] == "lookup"), None)
    try:
        for key, prompt, expected, reuse in cases:
            if any(r["case_id"] == key for r in rows):
                continue
            request = RunInput(
                engine="pipeline",
                prompt=prompt,
                source_ids=sources,
                conversation_id=conversation if reuse else None,
            )
            run = manager.create(corpus["project_id"], request)
            if reuse:
                conversation = run["conversation_id"]
            print("RUN", key, run["id"], flush=True)
            deadline = time.monotonic() + 720
            while time.monotonic() < deadline:
                with db.session() as s:
                    row = plain(s.get(AgentRun, run["id"]))
                if row["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.5)
            else:
                manager.cancel(run["id"])
                raise RuntimeError("live pipeline timeout")
            with db.session() as s:
                row["trace"] = [
                    plain(r)
                    for r in s.scalars(
                        select(PipelineStage)
                        .where(PipelineStage.run_id == run["id"])
                        .order_by(PipelineStage.number)
                    )
                ]
                row["claims"] = [
                    plain(r)
                    for r in s.scalars(select(AnswerClaim).where(AnswerClaim.run_id == run["id"]))
                ]
                row["memory"] = [
                    plain(r)
                    for r in s.scalars(
                        select(MemorySnapshot).where(MemorySnapshot.run_id == run["id"])
                    )
                ]
            actual = row.get("result", {}).get("answerability")
            passed = row["status"] == "completed" and actual == expected
            if expected == "answer":
                passed = passed and any(c["verdict"] == "supported" for c in row["claims"])
            row.update(case_id=key, expected=expected, behavior_pass=bool(passed))
            rows.append(row)
            report = {
                "kind": "live_model_engineering_regression",
                "corpus": corpus,
                "note": "Expected flow behavior only; automated claim audit is not human citation accuracy.",
                "retrieval_status": manager.retriever.status(),
                "cases": rows,
                "previous_attempts": previous_attempts,
                "metrics": {
                    "behavior_pass": sum(r["behavior_pass"] for r in rows),
                    "cases": len(rows),
                },
            }
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print("RESULT", key, row["status"], actual, "PASS" if passed else "FAIL", flush=True)
        assert all(r["behavior_pass"] for r in rows), "see report for failures"
    finally:
        manager.pool.shutdown(wait=True)
        db.engine.dispose()


if __name__ == "__main__":
    main()
