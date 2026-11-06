"""Read-only diagnostics using the same services as the web interface."""

import json
import shlex
from aster.agent.memory import Memory
from aster.domain.service import Problem
from aster.agent.trace import trace_report


def diagnostic_console(service, retriever, project_id, read=input, write=print):
    with service.db.session() as session:
        service.project(session, project_id)
    write("/corpus · /memory [conversation_id] · /trace RUN_ID · /quit")
    while True:
        try:
            parts = shlex.split(read("aster> ").strip())
            if not parts:
                continue
            command, *args = parts
            if command in {"/quit", "/exit"}:
                return
            if command == "/corpus" and not args:
                value = {**retriever.corpus.overview(project_id), "retrieval": retriever.status()}
            elif command == "/memory" and len(args) <= 1:
                value = Memory(service).inspect(project_id, args[0] if args else None)
            elif command == "/trace" and len(args) == 1:
                value = trace_report(service, args[0], project_id)
            elif command == "/help":
                write("/corpus · /memory [conversation_id] · /trace RUN_ID · /quit")
                continue
            else:
                write("未知命令或参数错误；输入 /help 查看命令。")
                continue
            write(json.dumps(value, ensure_ascii=False, indent=2))
        except (EOFError, KeyboardInterrupt):
            return
        except (Problem, ValueError) as error:
            write(str(error))
