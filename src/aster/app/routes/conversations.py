import asyncio
import json

from fastapi import Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from aster.domain.models import (
    AgentRun,
    RunEvent,
    Conversation,
    Message,
)
from aster.domain.schemas import (
    RunInput,
)
from aster.domain.service import Problem, plain, required
from aster.domain.management import deleted_ids, is_deleted


def configure(app):
    service, db, manager = app.state.service, app.state.db, app.state.manager

    def get_run(s, run_id):
        r = required(s, AgentRun, run_id)
        service.project(s, r.project_id)
        return r

    @app.get("/api/projects/{project_id}/conversations")
    def conversations(project_id: str):
        with db.session() as s:
            service.project(s, project_id)
            return [
                plain(c)
                for c in s.scalars(
                    select(Conversation)
                    .where(
                        Conversation.project_id == project_id,
                        ~Conversation.id.in_(deleted_ids("conversation", project_id)),
                    )
                    .order_by(Conversation.created_at.desc())
                )
            ]

    @app.get("/api/projects/{project_id}/conversations/{conversation_id}")
    def messages(project_id: str, conversation_id: str):
        with db.session() as s:
            service.project(s, project_id)
            c = required(s, Conversation, conversation_id)
            if c.project_id != project_id or is_deleted(
                s, project_id, "conversation", conversation_id
            ):
                raise Problem("对话不属于当前项目", 404)
            return [
                plain(m)
                for m in s.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at)
                )
            ]

    @app.post("/api/projects/{project_id}/runs", status_code=202)
    def start_run(project_id: str, body: RunInput):
        with manager.submissions:
            return manager.create(project_id, body)

    @app.get("/api/projects/{project_id}/runs")
    def runs(project_id: str, active_only: bool = False):
        with db.session() as s:
            service.project(s, project_id)
            query = select(AgentRun).where(AgentRun.project_id == project_id)
            if active_only:
                query = query.where(AgentRun.status.in_(["queued", "running"]))
            return [
                {k: v for k, v in plain(r).items() if k not in {"transcript", "context"}}
                for r in s.scalars(query.order_by(AgentRun.created_at.desc()).limit(50))
            ]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        with db.session() as s:
            return plain(get_run(s, run_id))

    @app.post("/api/runs/{run_id}/cancel")
    def cancel(run_id: str):
        with db.session() as s:
            get_run(s, run_id)
        manager.cancel(run_id)
        return {"requested": True}

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after: int = Query(default=0, ge=0)):
        with db.session() as s:
            get_run(s, run_id)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            cursor = after

        async def stream():
            nonlocal cursor
            idle = 0
            while not await request.is_disconnected():
                with db.session() as s:
                    r = required(s, AgentRun, run_id)
                    status = r.status
                    batch = list(
                        s.scalars(
                            select(RunEvent)
                            .where(RunEvent.run_id == run_id, RunEvent.number > cursor)
                            .order_by(RunEvent.number)
                            .limit(100)
                        )
                    )
                    items = [plain(e) for e in batch]
                for e in items:
                    cursor = e["number"]
                    yield f"id: {cursor}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                if status not in {"queued", "running"} and len(items) < 100:
                    yield "event: finished\ndata: " + json.dumps({"status": status}) + "\n\n"
                    break
                idle += 1
                if idle % 30 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.3)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
