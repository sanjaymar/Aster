"""科研问答主线：七阶段编排。模型格式在 llm.py，生成核查在 generation.py。"""

import re
from dataclasses import asdict

from aster.domain.models import AgentRun
from aster.agent.trace import PipelineTrace
from aster.agent.memory import Memory
from aster.retrieval.corpus import Corpus
from aster.agent.llm import (
    QueryPlan,
    EvidenceDecision,
    ModelGateway,
    NLU_PROMPT,
    REFLECT_PROMPT,
    DISCUSSION_REFLECT_PROMPT,
)
from aster.agent.generation import AnswerGenerator, GenerationRequest
from aster.domain.service import CITATION
from aster.agent.state import AgentState


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
        trace = PipelineTrace(self.db, run_id, emit, cancelled)
        gateway = gateway or ModelGateway(client, cfg, cancelled)
        with self.db.session() as s:
            run = s.get(AgentRun, run_id)
            project_id, conversation_id, prompt, context, mode = (
                run.project_id,
                run.conversation_id,
                run.prompt,
                run.context,
                run.mode,
            )
        discussion = context.get("response_style") == "discussion"
        snapshot = context["corpus_snapshot"]
        state = AgentState(run_id, project_id, conversation_id, prompt, snapshot)

        def add_usage(value):
            for key in state.usage:
                state.usage[key] += value.get(key, 0)

        with trace.stage(
            "Guardrails", {"scope": snapshot, "project_id": project_id, "options": options}
        ) as out:
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
            out.update(
                eligible_chunks=sum(i.kind == "C" for i in items),
                eligible_records=sum(i.kind == "V" for i in items),
                catalog=catalog,
            )
        state.memory = self.memory.latest(project_id, conversation_id) if options["memory"] else {}
        if options["memory"]:
            state.memory = {
                **state.memory,
                "confirmed_project_records": self.memory.project_records(
                    project_id, snapshot.get("artifact_version_ids", [])
                )[:8],
            }
        if not items:
            state.answer = (
                "当前没有可读取的材料。请先选择文献或记录，或将检索范围切换为“本项目资料”。"
            )
            state.decision = EvidenceDecision(
                action="clarify", reason="empty_scope", missing_facets=["可读取的文献或记录"]
            )
            for name in ["NLU", "Retrieve", "Rerank", "Reflect", "Generate"]:
                trace.skip(name, "empty_scope")
        else:
            with trace.stage(
                "NLU", {"question": prompt, "memory": state.memory, "catalog": catalog}
            ) as out:
                if options["rewrite"]:
                    state.plan, tokens = gateway.structured(
                        QueryPlan,
                        NLU_PROMPT
                        + (
                            "\n用户在讨论尚未实施的研究思路。改写时保留计划、假设或建议的语气，不得把计划改写成已发生的实验。"
                            if discussion
                            else ""
                        ),
                        {
                            "question": prompt,
                            "catalog": catalog,
                            "scope": snapshot["scope"],
                            "memory": state.memory,
                        },
                        1000,
                    )
                    add_usage(tokens)
                    out["usage"] = tokens
                else:
                    state.plan = QueryPlan(
                        intent="lookup", standalone_query=prompt, queries=[prompt]
                    )
                unknown = set(state.plan.targets) - {i.source_id for i in items}
                vague = re.search(
                    r"它(?!们)|这个方法|该方法|那个方法|\bit\b|\bthis method\b", prompt, re.I
                )
                named = any(
                    entity and entity.lower() in prompt.lower()
                    for entity in state.plan.resolved_entities
                )
                if (
                    state.plan.intent != "out_of_scope"
                    and vague
                    and len(catalog) > 1
                    and not state.memory.get("focus")
                    and not named
                ):
                    state.plan.needs_clarification = True
                    state.plan.clarification = (
                        "你指的是哪篇文献或哪个方法？请给出名称，或明确选择一个比较对象。"
                    )
                    out["clarification_rule"] = "ungrounded_reference_without_history"
                if unknown:
                    state.plan.needs_clarification = True
                    state.plan.clarification = (
                        "你指的是当前所选范围之外的资料吗？请重新选择比较对象。"
                    )
                out["plan"] = state.plan.model_dump()
            if state.plan.intent == "out_of_scope" or state.plan.needs_clarification:
                state.decision = EvidenceDecision(
                    action="clarify" if state.plan.needs_clarification else "refuse",
                    reason=state.plan.clarification or "问题超出了当前科研资料问答范围",
                )
                state.answer = state.decision.reason
                for name in ["Retrieve", "Rerank", "Reflect", "Generate"]:
                    trace.skip(name, state.decision.action)
            else:
                queries = state.plan.queries
                for attempt in range(1, 3):
                    gathered = {}
                    with trace.stage(
                        "Retrieve",
                        {
                            "queries": queries,
                            "strategy": options.get("strategy", "hybrid"),
                            "scope": snapshot,
                        },
                        attempt,
                    ) as out:
                        raw_results = []
                        for query in queries[:3]:
                            result, meta = self.retriever.search(
                                project_id,
                                snapshot,
                                query,
                                top_k=24,
                                strategy=options.get("strategy", "hybrid"),
                                rerank=False,
                            )
                            for hit in result:
                                gathered.setdefault(hit.evidence.id, hit)
                            raw_results.append(
                                {
                                    "query": query,
                                    "retrieval": meta,
                                    "hits": [h.public(False) for h in result],
                                }
                            )
                        for hit in state.hits:
                            gathered.setdefault(hit.evidence.id, hit)
                        out["searches"] = raw_results
                    with trace.stage(
                        "Rerank",
                        {"candidate_ids": list(gathered), "question": state.plan.standalone_query},
                        attempt,
                    ) as out:
                        ranked = list(gathered.values())
                        if (
                            options["rerank"]
                            and self.retriever.status()["backend"] == "hybrid"
                            and ranked
                        ):
                            scores = self.retriever.models.rerank(
                                state.plan.standalone_query, [h.evidence.text for h in ranked]
                            )
                            for hit, score in zip(ranked, scores, strict=True):
                                hit.scores["rerank"] = float(score)
                            ranked.sort(key=lambda h: -h.scores["rerank"])
                            out["backend"] = "cross_encoder"
                        else:
                            out["backend"] = "rrf"
                            out["status"] = "skipped" if not options["rerank"] else "completed"
                        # Reserve evidence for each explicitly compared paper.
                        diverse = []
                        for target in state.plan.targets:
                            candidate = next(
                                (h for h in ranked if h.evidence.source_id == target), None
                            )
                            if candidate and candidate not in diverse:
                                diverse.append(candidate)
                        state.hits = (diverse + [h for h in ranked if h not in diverse])[:8]
                        out["hits"] = [h.public(False) for h in state.hits]
                    with trace.stage(
                        "Reflect",
                        {
                            "question": state.plan.standalone_query,
                            "evidence": [h.public() for h in state.hits],
                        },
                        attempt,
                    ) as out:
                        if not state.hits:
                            state.decision = EvidenceDecision(
                                action="retrieve_more" if attempt == 1 else "refuse",
                                reason="没有召回可用于回答的证据",
                                missing_facets=[state.plan.standalone_query],
                                queries=[state.plan.standalone_query],
                            )
                        elif options["reflect"]:
                            state.decision, tokens = gateway.structured(
                                EvidenceDecision,
                                DISCUSSION_REFLECT_PROMPT if discussion else REFLECT_PROMPT,
                                {
                                    "question": state.plan.standalone_query,
                                    "targets": state.plan.targets,
                                    "evidence": [h.public() for h in state.hits],
                                    "attempt": attempt,
                                    "remaining_retrievals": 2 - attempt,
                                },
                                1000,
                            )
                            add_usage(tokens)
                            out["usage"] = tokens
                        else:
                            state.decision = EvidenceDecision(
                                action="answer", reason="reflection_ablation"
                            )
                        if state.decision.action == "retrieve_more" and attempt == 2:
                            state.decision = state.decision.model_copy(
                                update={
                                    "action": "refuse",
                                    "reason": "补充检索后证据仍不足：" + state.decision.reason,
                                }
                            )
                        out["decision"] = state.decision.model_dump()
                    if state.decision.action != "retrieve_more":
                        break
                    queries = state.decision.queries or [state.plan.standalone_query]
                if state.decision.action != "answer":
                    state.answer = (
                        "需要澄清："
                        if state.decision.action == "clarify"
                        else "目前无法根据所选材料可靠回答："
                    ) + state.decision.reason
                    if state.decision.missing_facets:
                        state.answer += "\n\n待补充：" + "；".join(state.decision.missing_facets)
                    trace.skip("Generate", state.decision.action)
                else:
                    with trace.stage(
                        "Generate",
                        {
                            "question": state.plan.standalone_query,
                            "evidence_ids": [h.evidence.id for h in state.hits],
                        },
                    ) as out:
                        generated = self.generator.run(
                            GenerationRequest(
                                run_id=run_id,
                                project_id=project_id,
                                question=state.plan.standalone_query,
                                prompt=prompt,
                                mode=mode,
                                snapshot=snapshot,
                                allowed=state.allowed,
                                hits=state.hits,
                                memory=state.memory,
                                decision=state.decision,
                                discussion=discussion,
                            ),
                            client,
                            cfg,
                            gateway,
                            emit,
                            cancelled,
                        )
                        state.answer, state.claims, state.created = (
                            generated.answer,
                            generated.claims,
                            generated.artifact_ids,
                        )
                        state.generation_result = generated.harness
                        state.decision = generated.decision
                        add_usage(generated.usage)
                        out.update(generated.trace)
        with trace.stage(
            "Memory", {"enabled": options["memory"], "answerability": state.decision.action}
        ) as out:
            if options["memory"]:
                refs = [f"[[{typ}:{key}]]" for typ, key in CITATION.findall(state.answer)]
                out["snapshot"] = self.memory.update(
                    project_id,
                    conversation_id,
                    run_id,
                    prompt,
                    state.plan,
                    state.decision,
                    refs,
                    {i.citation for i in items},
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
