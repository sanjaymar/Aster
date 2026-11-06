"""Isolated daily-assistant behavior checks with the configured local API."""

import argparse
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from aster.app.settings import Settings
from aster.app.runtime import RunManager
from aster.storage.database import Database
from aster.domain.service import Service, plain
from aster.domain.models import AgentRun
from aster.domain.schemas import RunInput
from aster.agent.trace import PipelineTrace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "kind": "daily_assistant_live_behavior",
        "independent_accuracy_evaluation": False,
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="aster-assistant-live-") as directory:
        root = Path(directory)
        original = Settings.from_env()
        if (original.data_dir / "models").is_dir():
            (root / "models").symlink_to(original.data_dir / "models", target_is_directory=True)
        settings = replace(original, data_dir=root, database_url=f"sqlite:///{root / 'live.db'}")
        db = Database(settings.database_url, root)
        db.migrate()
        service = Service(db)
        project = service.save_project(
            "Daily assistant live check", knowledge={"subject": "Metabolomics", "language": "zh"}
        )
        manager = RunManager(service, settings)

        def execute(name, prompt, conversation=None):
            run = manager.create(
                project["id"],
                RunInput(
                    prompt=prompt,
                    engine="assistant",
                    retrieval_scope="project",
                    response_style="discussion",
                    conversation_id=conversation,
                ),
            )
            deadline = time.monotonic() + 720
            while time.monotonic() < deadline:
                with db.session() as session:
                    row = plain(session.get(AgentRun, run["id"]))
                if row["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.3)
            else:
                manager.cancel(run["id"])
                raise RuntimeError("Live check timed out")
            report["cases"].append(
                {
                    "case": name,
                    "status": row["status"],
                    "error": row["error"],
                    "result": row["result"],
                    "retrieval_stages": [
                        s
                        for s in PipelineTrace(db, row["id"], lambda *_: None).read()
                        if s["name"] == "Retrieve"
                    ],
                }
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(name, row["status"], row["result"].get("calls_by_tool", {}), flush=True)
            assert row["status"] == "completed", row["error"]
            return row

        try:
            empty = execute(
                "empty_library_discussion",
                "我还没导入论文，想先记录一个研究假设。请用三句话说明怎样把一个想法变成可验证的实验问题；不用检索资料，不要假装已经做过实验。",
            )
            assert not empty["result"].get("calls_by_tool", {}).get("search_knowledge")
            service.import_source(
                project["id"], args.paper.name, args.paper.read_bytes(), title=args.paper.stem
            )
            evidence = execute(
                "project_rag",
                "请使用search_knowledge检索本知识库中这篇论文的研究问题与方法证据，再简述其研究问题与方法。英文论文用英文关键词检索。依据论文原文给出真实引用，控制在200字以内。",
            )
            assert evidence["result"].get("calls_by_tool", {}).get("search_knowledge", 0) > 0
            assert "[[C:" in evidence["result"]["answer"] or "[[S:" in evidence["result"]["answer"]
            execute(
                "followup",
                "刚才提到的方法，如果要用在新的研究中，我应先核对哪些条件？给出两个待验证建议，不要声称实验已经完成。",
                evidence["conversation_id"],
            )
        finally:
            manager.shutdown()
            db.engine.dispose()
    print(args.output)


if __name__ == "__main__":
    main()
