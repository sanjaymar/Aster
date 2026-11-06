"""Durable stage boundaries; stores decisions and evidence IDs, not hidden reasoning."""

import time
from dataclasses import dataclass, asdict
from datetime import datetime
from contextlib import contextmanager
from sqlalchemy import select, func
from aster.domain.models import PipelineStage, AgentRun, RunEvent, now

STAGES = ["Guardrails", "NLU", "Retrieve", "Rerank", "Reflect", "Generate", "Memory"]


@dataclass
class TurnTrace:
    run_id: str
    conversation_id: str
    number: int
    status: str
    duration_ms: float | None
    model: str | None
    engine: str
    usage: dict
    tool_calls: list


class PipelineTrace:
    def __init__(self, db, run_id, emit, cancelled=lambda: False):
        self.db, self.run_id, self.emit, self.cancelled = db, run_id, emit, cancelled

    @contextmanager
    def stage(self, name, inputs=None, attempt=1):
        if self.cancelled():
            raise KeyboardInterrupt
        with self.db.session() as s:
            number = (
                s.scalar(
                    select(func.max(PipelineStage.number)).where(
                        PipelineStage.run_id == self.run_id
                    )
                )
                or 0
            ) + 1
            row = PipelineStage(
                run_id=self.run_id, number=number, name=name, attempt=attempt, inputs=inputs or {}
            )
            s.add(row)
            s.flush()
            key = row.id
        self.emit("stage_start", {"id": key, "name": name, "attempt": attempt})
        start = time.monotonic()
        output = {}
        try:
            yield output
        except BaseException as e:
            output.update(
                status="cancelled" if isinstance(e, KeyboardInterrupt) else "failed",
                error=f"{type(e).__name__}: {str(e)[:500]}",
            )
            raise
        finally:
            elapsed = round((time.monotonic() - start) * 1000, 2)
            with self.db.session() as s:
                row = s.get(PipelineStage, key)
                row.status = output.get("status", "completed")
                row.outputs = {k: v for k, v in output.items() if k != "usage"}
                row.usage = output.get("usage", {})
                row.duration_ms = elapsed
                row.finished_at = now()
            self.emit(
                "stage_end",
                {
                    "id": key,
                    "name": name,
                    "status": output.get("status", "completed"),
                    "duration_ms": elapsed,
                    "attempt": attempt,
                },
            )

    def skip(self, name, reason):
        with self.stage(name) as out:
            out.update(status="skipped", reason=reason)

    def read(self):
        with self.db.session() as s:
            from aster.domain.service import plain

            return [
                plain(r)
                for r in s.scalars(
                    select(PipelineStage)
                    .where(PipelineStage.run_id == self.run_id)
                    .order_by(PipelineStage.number)
                )
            ]

    def turn(self):
        with self.db.session() as session:
            run = session.get(AgentRun, self.run_id)
            number = session.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(
                    AgentRun.conversation_id == run.conversation_id,
                    AgentRun.created_at <= run.created_at,
                )
            )
            events = session.scalars(
                select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.number)
            )
            calls, stage_stack, pending = [], [], {}
            for event in events:
                if event.kind == "stage_start":
                    stage_stack.append(event.payload.get("id"))
                elif event.kind == "stage_end":
                    stage_stack = [key for key in stage_stack if key != event.payload.get("id")]
                elif event.kind == "tool_start":
                    call = {
                        "stage_id": stage_stack[-1] if stage_stack else None,
                        "started_at": event.created_at,
                        **event.payload,
                    }
                    calls.append(call)
                    pending[event.payload.get("id") or event.payload.get("name")] = call
                elif event.kind == "tool_end":
                    call = pending.pop(event.payload.get("id") or event.payload.get("name"), None)
                    if call is not None:
                        call.update(finished_at=event.created_at, result=event.payload)
                        call["duration_ms"] = round(
                            (
                                datetime.fromisoformat(event.created_at)
                                - datetime.fromisoformat(call["started_at"])
                            ).total_seconds()
                            * 1000,
                            2,
                        )
            duration = (
                (
                    datetime.fromisoformat(run.finished_at) - datetime.fromisoformat(run.created_at)
                ).total_seconds()
                * 1000
                if run.finished_at
                else None
            )
            return asdict(
                TurnTrace(
                    run.id,
                    run.conversation_id,
                    number,
                    run.status,
                    duration,
                    run.context.get("model_config", {}).get("model"),
                    "mini-harness",
                    run.result.get("pipeline", {}).get("usage")
                    or {
                        "prompt_tokens": run.result.get("prompt_total", 0),
                        "completion_tokens": run.result.get("completion_total", 0),
                    },
                    calls,
                )
            )


# Existing integrations may still import Trace.
Trace = PipelineTrace


def trace_report(service, run_id, project_id=None):
    from aster.domain.models import AnswerClaim
    from aster.domain.service import plain, required, Problem

    with service.db.session() as session:
        run = required(session, AgentRun, run_id)
        service.project(session, run.project_id)
        if project_id and run.project_id != project_id:
            raise Problem("任务不属于当前项目", 404)
        status, result = run.status, run.result
        claims = [
            plain(row)
            for row in session.scalars(select(AnswerClaim).where(AnswerClaim.run_id == run_id))
        ]
    trace = PipelineTrace(service.db, run_id, lambda *_: None)
    return {
        "run_id": run_id,
        "status": status,
        "turn": trace.turn(),
        "stages": trace.read(),
        "claims": claims,
        "result": result,
    }
