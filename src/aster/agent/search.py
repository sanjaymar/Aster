"""Bounded retrieve/rerank/reflect loop shared by the web and evaluations."""

from aster.agent.llm import (
    EvidenceDecision,
    REFLECT_PROMPT,
    DISCUSSION_REFLECT_PROMPT,
    READING_REFLECT_PROMPT,
)


def gather(state, retriever, trace, gateway, options, discussion, add_usage, direct=False):
    queries = state.plan.queries
    for attempt in range(1, 3):
        if direct and attempt == 1:
            trace.skip("Retrieve", "selected_excerpt")
            trace.skip("Rerank", "selected_excerpt")
        else:
            candidates = {}
            with trace.stage(
                "Retrieve", {"queries": queries, "scope": state.snapshot}, attempt
            ) as out:
                searches = []
                for query in queries[:3]:
                    hits, meta = retriever.search(
                        state.project_id,
                        state.snapshot,
                        query,
                        top_k=24,
                        strategy=options.get("strategy", "hybrid"),
                        rerank=False,
                    )
                    for hit in hits:
                        candidates.setdefault(hit.evidence.id, hit)
                    searches.append(
                        {"query": query, "retrieval": meta, "hits": [h.public(False) for h in hits]}
                    )
                for hit in state.hits:
                    candidates.setdefault(hit.evidence.id, hit)
                out["searches"] = searches
            with trace.stage("Rerank", {"candidate_ids": list(candidates)}, attempt) as out:
                ranked = list(candidates.values())
                if options["rerank"] and retriever.status()["backend"] == "hybrid" and ranked:
                    scores = retriever.models.rerank(
                        state.plan.standalone_query, [h.evidence.text for h in ranked]
                    )
                    for hit, score in zip(ranked, scores, strict=True):
                        hit.scores["rerank"] = float(score)
                    ranked.sort(key=lambda h: -h.scores["rerank"])
                    out["backend"] = "cross_encoder"
                else:
                    out.update(
                        backend="rrf", status="completed" if options["rerank"] else "skipped"
                    )
                selected = []
                for target in state.plan.targets:
                    hit = next((h for h in ranked if h.evidence.source_id == target), None)
                    if hit and hit not in selected:
                        selected.append(hit)
                state.hits = (selected + [h for h in ranked if h not in selected])[:8]
                if "reading_sources" in options and not options.get("no_search"):
                    from aster.reading.material import broaden

                    broaden(state, options["reading_sources"])
                    out["coverage"] = "selected_paper_sections"
                out["hits"] = [h.public(False) for h in state.hits]
        with trace.stage(
            "Reflect",
            {"question": state.plan.standalone_query, "evidence": [h.public() for h in state.hits]},
            attempt,
        ) as out:
            if not state.hits:
                state.decision = EvidenceDecision(
                    action="retrieve_more" if attempt == 1 else "refuse",
                    reason="没有找到支持该问题的资料",
                    queries=[state.plan.standalone_query],
                )
            elif options["reflect"]:
                state.decision, usage = gateway.structured(
                    EvidenceDecision,
                    READING_REFLECT_PROMPT
                    if "reading_sources" in options
                    else DISCUSSION_REFLECT_PROMPT
                    if discussion
                    else REFLECT_PROMPT,
                    {
                        "question": state.plan.standalone_query,
                        "targets": state.plan.targets,
                        "evidence": [h.public() for h in state.hits],
                        "attempt": attempt,
                        "remaining_retrievals": 2 - attempt,
                    },
                    1200,
                )
                add_usage(usage)
                out["usage"] = usage
            else:
                state.decision = EvidenceDecision(action="answer", reason="reflection_ablation")
            if state.decision.action == "retrieve_more" and (
                attempt == 2 or options.get("no_search")
            ):
                state.decision = state.decision.model_copy(
                    update={"action": "refuse", "reason": "现有资料不足：" + state.decision.reason}
                )
            out["decision"] = state.decision.model_dump()
        if state.decision.action != "retrieve_more":
            break
        queries = state.decision.queries or [state.plan.standalone_query]
