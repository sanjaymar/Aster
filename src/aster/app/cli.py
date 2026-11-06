import argparse
import os
import json

from aster.app.settings import Settings


def main():
    home = Settings.from_env().data_dir
    parser = argparse.ArgumentParser(description="Aster · Research Assistant")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", help="本地数据库与附件目录")
    parser.add_argument("--migrate-only", action="store_true")
    commands = parser.add_subparsers(dest="command")
    collect = commands.add_parser("collect", help="采集近期开放获取期刊论文与原始PDF")
    collect.add_argument("--topic", choices=["metabolomics", "ai4bio"], required=True)
    collect.add_argument("--limit", type=int, default=30)
    collect.add_argument("--since", default="2024-01-01")
    collect.add_argument("--project")
    models = commands.add_parser("models", help="检查或下载固定版本的本地检索模型")
    models.add_argument("--download", action="store_true")
    corpus = commands.add_parser("corpus", help="查看项目语料与分块统计")
    corpus.add_argument("--project", required=True)
    index = commands.add_parser("index", help="构建项目范围内的检索索引")
    index.add_argument("--project", required=True)
    trace = commands.add_parser("trace", help="查看一次任务的阶段追踪")
    trace.add_argument("run_id")
    memory = commands.add_parser("memory", help="查看会话记忆快照")
    memory.add_argument("--project", required=True)
    memory.add_argument("--conversation")
    console = commands.add_parser("console", help="交互式 /corpus /memory /trace 命令")
    console.add_argument("--project", required=True)
    suite = commands.add_parser("evaluate-suite", help="运行代谢组学组件评测与消融")
    suite.add_argument("suite_args", nargs=argparse.REMAINDER)
    evaluate = commands.add_parser("evaluate", help="在独立示例库或指定项目上运行检索消融")
    evaluate.add_argument("--project")
    evaluate.add_argument("--papers", default=str(home / "archive/retrieval/papers"))
    evaluate.add_argument("--dataset", default="eval/retrieval.json")
    evaluate.add_argument("--strategies", default="bm25,dense,hybrid,hybrid-rerank")
    evaluate.add_argument("--output", default=str(home / "experiments/retrieval/report.json"))
    import sys

    if "evaluate-suite" in sys.argv:
        from aster.evaluation.suite import main as suite_main

        position = sys.argv.index("evaluate-suite")
        prefix = parser.parse_args(sys.argv[1:position])
        if prefix.data_dir:
            from pathlib import Path

            os.environ["ASTER_HOME"] = str(Path(prefix.data_dir).resolve())
            os.environ["ASTER_DATABASE_URL"] = "sqlite:///" + str(
                Path(prefix.data_dir).resolve() / "library/aster.db"
            )
        sys.argv = [sys.argv[0], *sys.argv[position + 1 :]]
        return suite_main()
    args = parser.parse_args()
    if args.data_dir:
        from pathlib import Path

        os.environ["ASTER_HOME"] = str(Path(args.data_dir).resolve())
        os.environ["ASTER_DATABASE_URL"] = "sqlite:///" + str(
            Path(args.data_dir).resolve() / "library/aster.db"
        )
    settings = Settings.from_env()
    if args.command:
        from aster.storage.database import Database
        from aster.domain.service import Service
        from aster.retrieval.engine import Retriever, LocalModels, prepare_models

        if args.command == "models":
            value = prepare_models(settings) if args.download else LocalModels(settings).status()
        else:
            db = Database(settings.database_url, settings.data_dir)
            db.migrate()
            service = Service(db)
            retriever = Retriever(service, settings)
            if args.command == "collect":
                from aster.library.collect import collect

                value = collect(service, args.topic, args.limit, args.since, args.project)
                print(json.dumps(value, ensure_ascii=False, indent=2))
                return
            if args.command == "evaluate":
                from aster.evaluation.retrieval import ingest_public_corpus, evaluate_retrieval
                from pathlib import Path

                corpus = (
                    ingest_public_corpus(service, args.papers)
                    if not args.project
                    else {"project_id": args.project, "sources": {}}
                )
                value = evaluate_retrieval(
                    retriever,
                    corpus["project_id"],
                    args.dataset,
                    corpus["sources"],
                    args.strategies.split(","),
                )
                destination = Path(args.output)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps(value, ensure_ascii=False, indent=2))
                print(
                    json.dumps(
                        {"report": str(destination), "corpus": corpus, "metrics": value["metrics"]},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return
            if args.command == "corpus":
                value = {**retriever.corpus.overview(args.project), "retrieval": retriever.status()}
            elif args.command == "index":
                snapshot = retriever.corpus.snapshot(args.project, scope="project")
                _, value = retriever.search(
                    args.project, snapshot, "index preparation", top_k=1, rerank=False
                )
            elif args.command == "memory":
                from aster.agent.memory import Memory

                value = Memory(service).inspect(args.project, args.conversation)
            elif args.command == "console":
                from aster.app.console import diagnostic_console

                return diagnostic_console(service, retriever, args.project)
            else:
                from aster.agent.trace import trace_report

                value = trace_report(service, args.run_id)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if args.migrate_only:
        from aster.storage.database import Database

        Database(settings.database_url, settings.data_dir).migrate()
        print("Aster：数据库结构已更新。")
        return
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not settings.access_token:
        parser.error("对外监听时请先设置 ASTER_ACCESS_TOKEN 访问口令")
    import uvicorn

    print(f"Aster · http://{args.host}:{args.port}")
    print(f"资料目录：{settings.data_dir}")
    uvicorn.run("aster.app.api:create_app", factory=True, host=args.host, port=args.port, workers=1)
