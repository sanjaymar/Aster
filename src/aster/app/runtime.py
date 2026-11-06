"""Project-scoped agent execution using the mini-harness tool loop."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select, func

from aster.domain.models import (
    AgentRun,
    RunEvent,
    Conversation,
    Message,
    PipelineStage,
    now,
)
from aster.domain.management import is_deleted
from aster.domain.service import Problem, plain, required
from aster.retrieval.engine import Retriever
from aster.agent.pipeline import ResearchPipeline
from aster.agent.config import ResearchConfig
from aster.skills import Skills
from aster.models.profiles import ModelProfiles, ProfileInput
from aster.models.clients import model_client

log = logging.getLogger(__name__)


class RunManager:
    def __init__(self, service, settings):
        self.service, self.db, self.settings = service, service.db, settings
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aster")
        self.stops = {}
        self.guard = threading.Lock()
        self.submissions = threading.Lock()
        self.retriever = Retriever(service, settings)
        self.pipeline = ResearchPipeline(service, self.retriever)
        self.profiles = ModelProfiles(self.db, settings)
        self.skills = Skills(self.db)
        self.evaluation_options = None
        self.model_override = None

    def model_settings(self):
        return self.profiles.get()

    def save_model_settings(self, values):
        current = self.profiles.get("local")
        body = {k: v for k, v in {**current, **values}.items() if k in ProfileInput.model_fields}
        self.profiles.save(ProfileInput.model_validate(body), "local")
        return self.model_settings()

    def model_health(self):
        return self.profiles.health()

    def recover(self):
        with self.db.session() as s:
            for run in s.scalars(select(AgentRun).where(AgentRun.status == "running")):
                run.status, run.error, run.finished_at = (
                    "interrupted",
                    "应用重启，执行已中断。可查看已保存的过程后重新发起。",
                    now(),
                )
                for stage in s.scalars(
                    select(PipelineStage).where(
                        PipelineStage.run_id == run.id, PipelineStage.status == "running"
                    )
                ):
                    stage.status, stage.finished_at = "interrupted", now()
            queued = [
                r.id
                for r in s.scalars(
                    select(AgentRun)
                    .where(AgentRun.status == "queued")
                    .order_by(AgentRun.created_at)
                )
            ]
        for run_id in queued:
            self._submit(run_id)

    def create(self, project_id, request):
        profile = self.model_override or self.profiles.get(
            request.model_profile_id, "reader" if request.source_version_ids else "assistant"
        )
        skills = self.skills.snapshot()
        if request.skill_id and not any(s["id"] == request.skill_id for s in skills):
            raise Problem("所选技能未启用或已删除", 404)
        snapshot = self.retriever.corpus.snapshot(
            project_id,
            request.source_ids,
            request.artifact_ids,
            request.retrieval_scope,
            request.source_version_ids,
        )
        from aster.library.figures import pin

        figure_versions = pin(self.service, project_id, snapshot["source_version_ids"])
        with self.db.session() as s:
            project = self.service.project(s, project_id)
            if request.conversation_id:
                conversation = required(s, Conversation, request.conversation_id)
                if conversation.project_id != project_id or is_deleted(
                    s, project_id, "conversation", conversation.id
                ):
                    raise Problem("对话不属于当前项目", 404)
                active = s.scalar(
                    select(AgentRun.id)
                    .where(
                        AgentRun.conversation_id == conversation.id,
                        AgentRun.status.in_(["queued", "running"]),
                    )
                    .limit(1)
                )
                if active:
                    raise Problem("当前对话还有任务在执行", 409)
            else:
                conversation = Conversation(project_id=project_id, title=request.prompt[:80])
                s.add(conversation)
                s.flush()
            # Store fixed IDs and excerpts at submission, so queued work cannot silently
            # switch to newer document/record revisions.
            run = AgentRun(
                project_id=project_id,
                conversation_id=conversation.id,
                prompt=request.prompt,
                mode=request.mode,
                context={
                    "engine": "pipeline",
                    "response_style": request.response_style,
                    "retrieval_policy": request.retrieval_policy,
                    "corpus_snapshot": snapshot,
                    "skills": skills,
                    "skill_id": request.skill_id,
                    "source_ids": request.source_ids,
                    "figure_versions": figure_versions,
                    "artifact_ids": request.artifact_ids,
                    "project": {
                        "title": project.title,
                        "description": project.description,
                        "domain": project.domain,
                        "knowledge": project.knowledge,
                    },
                    "model_config": profile,
                },
            )
            s.add(run)
            s.add(Message(conversation_id=conversation.id, role="user", content=request.prompt))
            s.flush()
            result = plain(run)
        self._submit(result["id"])
        return result

    def _submit(self, run_id):
        with self.guard:
            self.stops[run_id] = threading.Event()
        self.pool.submit(self._execute, run_id)

    def cancel(self, run_id):
        with self.guard:
            stop = self.stops.get(run_id)
            if stop:
                stop.set()
        with self.db.session() as s:
            r = required(s, AgentRun, run_id)
            if r.status == "queued":
                r.status, r.finished_at = "cancelled", now()

    def _event(self, run_id, kind, payload):
        with self.db.session() as s:
            number = (
                s.scalar(select(func.max(RunEvent.number)).where(RunEvent.run_id == run_id)) or 0
            ) + 1
            s.add(RunEvent(run_id=run_id, number=number, kind=kind, payload=payload))

    def _execute(self, run_id):
        stop = self.stops.get(run_id) or threading.Event()
        text_buffer = []
        last_flush = time.monotonic()

        def flush():
            nonlocal last_flush
            if text_buffer:
                self._event(run_id, "text", {"text": "".join(text_buffer)})
                text_buffer.clear()
            last_flush = time.monotonic()

        def emit(kind, data):
            if kind == "draft_text":
                # The full candidate is in the transcript. Keep unverified
                # tokens out of the durable SSE feed and visible chat.
                return
            if kind == "text":
                text_buffer.append(data["text"])
                if sum(map(len, text_buffer)) >= 80 or time.monotonic() - last_flush > 0.4:
                    flush()
            else:
                flush()
                self._event(run_id, kind, data)

        try:
            with self.db.session() as s:
                run = required(s, AgentRun, run_id)
                if run.status != "queued" or stop.is_set():
                    return
                run.status = "running"
                conversation_id, prompt, context = (
                    run.conversation_id,
                    run.prompt,
                    run.context,
                )
            config = self.profiles.resolve(
                {"id": "local", "provider": "compatible", **context["model_config"]}
            )
            if context.get("engine") in {"pipeline", "assistant"}:
                cfg = ResearchConfig(
                    provider=config["provider"],
                    disable_thinking=config.get("disable_thinking", config["id"] == "local"),
                    api_key_value=self.profiles.key(config),
                    model_main=config["model"],
                    model_sub=config["model"],
                    base_url=config["base_url"],
                    max_tokens_main=config["max_tokens"],
                    max_tokens_sub=1024,
                    compact_limit=18000,
                    clip_limit=14000,
                    max_retry=2,
                    rate_retry=2,
                    retry_base=1,
                    rate_base=2,
                    rate_cap=5,
                    work_space=self.db.data_dir,
                    track_files=False,
                    temp_set=0.2,
                )
                with model_client(self.profiles, config, stop.is_set) as client:
                    result = self.pipeline.run(
                        run_id, client, cfg, emit, stop.is_set, ablation=self.evaluation_options
                    )
                flush()
                emit("answer_verified", {"text": result["answer"]})
                with self.db.session() as s:
                    row = required(s, AgentRun, run_id)
                    row.status = "cancelled" if stop.is_set() else "completed"
                    row.finished_at = now()
                    row.result = {
                        "engine": "pipeline",
                        "model": config["model"],
                        "provider": config["provider"],
                        "outcome": row.status,
                        "answerability": result["answerability"],
                        "artifact_ids": result["artifact_ids"],
                        "prompt_total": result["usage"]["prompt_tokens"],
                        "completion_total": result["usage"]["completion_tokens"],
                        "calls_by_tool": (result["harness"] or {}).get("calls_by_tool", {}),
                        "pipeline": result,
                    }
                    s.add(
                        Message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=result["answer"],
                        )
                    )
                    if not row.transcript:
                        row.transcript = [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": result["answer"]},
                        ]
                emit(
                    "done",
                    {
                        "status": row.status,
                        "artifact_ids": result["artifact_ids"],
                        "answerability": result["answerability"],
                    },
                )
                return
            raise Problem("旧运行入口已停用，请重新发送问题")
        except BaseException as e:
            flush()
            log.exception("Agent run failed: %s", run_id)
            with self.db.session() as s:
                r = required(s, AgentRun, run_id)
                r.status = "cancelled" if stop.is_set() else "error"
                r.error = f"{type(e).__name__}: {str(e)[:1000]}"
                r.finished_at = now()
            self._event(run_id, "done", {"status": r.status, "error": str(e)[:1000]})
        finally:
            with self.guard:
                self.stops.pop(run_id, None)

    def shutdown(self):
        with self.guard:
            for stop in self.stops.values():
                stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
