"""Check grounded answers and explicit proposals against real papers with local Qwen."""

import argparse
import hashlib
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from aster.app.runtime import RunManager
from aster.app.settings import Settings
from aster.domain.models import AgentRun, AnswerClaim
from aster.domain.schemas import RunInput
from aster.domain.service import Service, plain
from aster.storage.database import Database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper", type=Path, required=True, help="A downloaded full-text Markdown")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    content = args.paper.read_bytes()
    report = {
        "kind": "live_model_engineering_regression",
        "paper": args.paper.name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "note": "Checks flow and visible separation of suggestions, not scientific accuracy.",
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="aster-discussion-") as temp:
        root = Path(temp)
        db = Database(f"sqlite:///{root / 'test.db'}", root)
        db.migrate()
        service = Service(db)
        project = service.save_project("Temporary reading check")
        source = service.import_source(project["id"], args.paper.name, content)
        settings = replace(Settings.from_env(), data_dir=root, database_url=db.url)
        manager = RunManager(service, settings)
        manager.save_model_settings(
            {**manager.model_settings(), "max_tokens": 1600, "timeout": 600}
        )
        cases = [
            (
                "grounded",
                "这篇论文代谢组学分析使用了什么技术？只说明原文明确报告的方法，保留引用，不超过150字。",
            ),
            (
                "discussion",
                "我想借鉴这篇论文的代谢组学分析，先用pooled QC检查批次漂移，再决定是否校正。"
                "设计还需要补充什么验证？请提出待验证的建议，不要声称任何校正已经完成，不超过250字。",
            ),
        ]
        try:
            for style, prompt in cases:
                started = time.monotonic()
                run = manager.create(
                    project["id"],
                    RunInput(
                        prompt=prompt,
                        source_ids=[source["id"]],
                        response_style=style,
                        engine="pipeline",
                    ),
                )
                print("RUN", style, run["id"], flush=True)
                while time.monotonic() - started < 720:
                    with db.session() as session:
                        row = plain(session.get(AgentRun, run["id"]))
                    if row["status"] not in {"queued", "running"}:
                        break
                    time.sleep(0.5)
                else:
                    manager.cancel(run["id"])
                    raise RuntimeError("Model flow timed out")
                with db.session() as session:
                    claims = [
                        plain(claim)
                        for claim in session.scalars(
                            select(AnswerClaim).where(AnswerClaim.run_id == run["id"])
                        )
                    ]
                passed = (
                    row["status"] == "completed" and row["result"].get("answerability") == "answer"
                )
                expected_verdict = "inference" if style == "discussion" else "supported"
                passed = passed and any(claim["verdict"] == expected_verdict for claim in claims)
                if style == "discussion":
                    passed = passed and "待验证的分析与建议" in row["result"].get(
                        "pipeline", {}
                    ).get("answer", "")
                report["cases"].append(
                    {
                        "style": style,
                        "prompt": prompt,
                        "status": row["status"],
                        "result": row["result"],
                        "error": row["error"],
                        "claims": claims,
                        "elapsed_seconds": round(time.monotonic() - started, 2),
                        "behavior_pass": bool(passed),
                    }
                )
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print("RESULT", style, "PASS" if passed else "FAIL", flush=True)
        finally:
            manager.pool.shutdown(wait=True)
            db.engine.dispose()
    assert all(row["behavior_pass"] for row in report["cases"]), "See report for behavior failures"


if __name__ == "__main__":
    main()
