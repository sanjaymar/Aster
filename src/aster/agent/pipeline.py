"""One seven-stage pipeline for reading, discussion, notes and evaluations."""

from dataclasses import asdict
from dataclasses import replace
from aster.domain.models import AgentRun
from aster.domain.common import CITATION
from aster.agent.trace import PipelineTrace
from aster.agent.memory import Memory
from aster.retrieval.corpus import Corpus
from aster.retrieval.engine import Hit
from aster.agent.llm import EvidenceDecision, ModelGateway
from aster.agent.generation import AnswerGenerator, GenerationRequest
from aster.agent.state import AgentState
from aster.agent.planning import history, excerpts, plan_question
from aster.agent.search import gather
from aster.agent.discussion import discuss


class ResearchPipeline:
    def __init__(self, service, retriever):
        self.service, self.db, self.retriever = service, service.db, retriever
        self.corpus = Corpus(service)
        self.memory = Memory(service)
        self.generator = AnswerGenerator(service, retriever)

    def run(self, run_id, client, cfg, emit, cancelled=lambda: False, gateway=None, ablation=None):
        options = {
            "rewrite": True,
            "rerank": True,
            "reflect": True,
            "memory": True,
            **(ablation or {}),
        }
        gateway = gateway or ModelGateway(client, cfg, cancelled)
        with self.db.session() as session:
            row = session.get(AgentRun, run_id)
            project_id, conversation_id, prompt, context, mode = (
                row.project_id,
                row.conversation_id,
                row.prompt,
                row.context,
                row.mode,
            )
        snapshot = context["corpus_snapshot"]
        state = AgentState(run_id, project_id, conversation_id, prompt, snapshot)

        def event(kind, data):
            state.harness.record(kind, data)
            emit(kind, data)

        trace = PipelineTrace(self.db, run_id, event, cancelled)

        def add_usage(value):
            for key in state.usage:
                state.usage[key] += value.get(key, 0)

        with trace.stage("Guardrails", {"scope": snapshot, "options": options}) as out:
            items = self.corpus.items(project_id, snapshot)
            state.allowed = {i.id: i for i in items}
            catalog = list(
                {
                    i.source_id: {
                        "source_id": i.source_id,
                        "title": i.title,
                        "version": i.version,
                        "authority": i.authority,
                    }
                    for i in items
                }.values()
            )
            supplied = excerpts(self.service, project_id, prompt, snapshot, items)
            state.allowed.update({i.id: i for i in supplied})
            out.update(
                eligible_chunks=sum(i.kind == "C" for i in items),
                eligible_records=sum(i.kind == "V" for i in items),
                supplied=len(supplied),
            )
        state.memory = self.memory.latest(project_id, conversation_id) if options["memory"] else {}
        if options["memory"]:
            state.memory = {
                **state.memory,
                "confirmed_project_records": self.memory.project_records(
                    project_id, snapshot.get("artifact_version_ids", [])
                )[:8],
            }
        messages = history(self.service, conversation_id)
        context = {**context, "mode": mode}
        with trace.stage("NLU", {"question": prompt, "memory": state.memory}) as out:
            state.plan, usage = plan_question(
                gateway, state, context, catalog, messages, options["rewrite"]
            )
            add_usage(usage)
            # Explicit policy is enforced in code, not only a prompt preference.
            if context.get("retrieval_policy") == "off":
                state.plan.route = "context" if supplied else "discuss"
                options["no_search"] = True
            elif (
                context.get("response_style", "grounded") == "grounded"
                and state.plan.route == "discuss"
            ):
                state.plan.route = "retrieve"
            if state.plan.route == "context" and not supplied:
                state.plan.route = "retrieve" if items else "discuss"
            if mode in {"reading", "slides"} and items and not options.get("no_search"):
                state.plan.route = "retrieve"
            out.update(plan=state.plan.model_dump(), usage=usage)
        if state.plan.needs_clarification or state.plan.intent == "out_of_scope":
            state.decision = EvidenceDecision(
                action="clarify" if state.plan.needs_clarification else "refuse",
                reason=state.plan.clarification or "无法按此要求提供可靠的回答",
            )
            for stage in ["Retrieve", "Rerank", "Reflect"]:
                trace.skip(stage, state.decision.action)
        elif state.plan.route == "discuss":
            trace.skip("Retrieve", "general_discussion")
            trace.skip("Rerank", "general_discussion")
            with trace.stage("Reflect", {"route": "discuss"}) as out:
                state.decision = EvidenceDecision(
                    action="answer", reason="通用讨论；不声称有论文证据"
                )
                out.update(decision=state.decision.model_dump(), audit="general_knowledge")
        else:
            state.hits = [Hit(i, {}) for i in supplied]
            if mode in {"reading", "slides"} and not options.get("no_search"):
                options["reading_sources"] = context.get("source_ids", [])
            gather(
                state,
                self.retriever,
                trace,
                gateway,
                options,
                context.get("response_style") in {"auto", "discussion"},
                add_usage,
                direct=state.plan.route == "context",
            )
        if state.decision.action != "answer":
            state.answer = state.decision.reason
            if state.decision.missing_facets:
                state.answer += "\n\n待补充：" + "；".join(state.decision.missing_facets)
            trace.skip("Generate", state.decision.action)
        else:
            with trace.stage(
                "Generate",
                {"route": state.plan.route, "evidence_ids": [h.evidence.id for h in state.hits]},
            ) as out:
                if state.plan.route == "discuss":
                    state.answer, state.generation_result = discuss(
                        self.service, state, context, messages, client, cfg, event, cancelled
                    )
                    out.update(audit="general_knowledge", answer=state.answer)
                else:
                    generated = self.generator.run(
                        GenerationRequest(
                            run_id,
                            project_id,
                            state.plan.standalone_query,
                            prompt,
                            mode,
                            snapshot,
                            {h.evidence.id: h.evidence for h in state.hits}
                            if options.get("no_search")
                            else state.allowed,
                            state.hits,
                            state.memory,
                            state.decision,
                            context.get("response_style") in {"auto", "discussion"},
                            context.get("skills", []),
                            context.get("skill_id"),
                            messages,
                            not options.get("no_search", False),
                        ),
                        client,
                        replace(cfg, max_tokens_main=max(cfg.max_tokens_main, 5000))
                        if mode in {"reading", "slides"}
                        else cfg,
                        gateway,
                        event,
                        cancelled,
                    )
                    state.answer, state.claims, state.generation_result, state.decision = (
                        generated.answer,
                        generated.claims,
                        generated.harness,
                        generated.decision,
                    )
                    add_usage(generated.usage)
                    out.update(generated.trace)
                if cancelled():
                    raise KeyboardInterrupt
                if state.decision.action == "answer" and mode != "chat":
                    record = self.save_output(state, context, mode, gateway, add_usage)
                    state.created.append(record["id"])
                    event(
                        "artifact",
                        {"id": record["id"], "title": record["title"], "kind": record["kind"]},
                    )
        with trace.stage("Memory", {"enabled": options["memory"]}) as out:
            if options["memory"]:
                refs = [f"[[{kind}:{key}]]" for kind, key in CITATION.findall(state.answer)]
                out["snapshot"] = self.memory.update(
                    project_id,
                    conversation_id,
                    run_id,
                    prompt,
                    state.plan,
                    state.decision,
                    refs,
                    {i.citation for i in state.allowed.values()},
                )
            else:
                out.update(status="skipped", reason="memory_ablation")
        if state.generation_result:
            state.usage["prompt_tokens"] += state.generation_result.prompt_total
            state.usage["completion_tokens"] += state.generation_result.completion_total
        return {
            "state": state.summary(),
            "answer": state.answer,
            "artifact_ids": state.created,
            "answerability": state.decision.action,
            "usage": state.usage,
            "stages": len(trace.read()),
            "claims": [c.model_dump() for c in state.claims],
            "harness": asdict(state.generation_result) if state.generation_result else None,
        }

    def save_output(self, state, context, mode, gateway, add_usage):
        sources = context.get("source_ids", [])
        fields = {
            "source_id": sources[0] if len(sources) == 1 else None,
            "source_ids": sources,
            "skill_id": context.get("skill_id"),
            "note_type": "reading",
            "run_id": state.run_id,
        }
        if "figure_versions" in context:
            fields["figure_versions"] = context["figure_versions"]
        if mode == "slides":
            from aster.slides.service import Slides

            record, usage = Slides(self.service).generate(
                state.project_id, state.question, state.answer, state.allowed, gateway, fields
            )
            add_usage(usage)
            return record
        from aster.reading.report import create

        return create(self.service, state, fields)
