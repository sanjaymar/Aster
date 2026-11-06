"""Question planning and authorization of excerpts already supplied by the reader."""

import re
from sqlalchemy import select
from aster.domain.models import Message, SourceSpan, SourceVersion
from aster.domain.common import CITATION, Problem
from aster.retrieval.corpus import Evidence
from aster.agent.llm import QueryPlan, NLU_PROMPT


def history(service, conversation_id):
    with service.db.session() as session:
        rows = list(
            session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(13)
            )
        )[::-1]
        return [{"role": row.role, "content": row.content[:8000]} for row in rows]


def excerpts(service, project_id, prompt, snapshot, items):
    by_ref = {(i.kind, i.id): i for i in items}
    result = []
    with service.db.session() as session:
        for kind, key in dict.fromkeys(CITATION.findall(prompt)):
            if (kind, key) in by_ref:
                result.append(by_ref[(kind, key)])
            elif kind == "S":
                span = session.get(SourceSpan, key)
                if not span or span.source_version_id not in snapshot["source_version_ids"]:
                    raise Problem("选段不在本次资料范围内", 404)
                version = session.get(SourceVersion, span.source_version_id)
                source = service.source(session, project_id, version.source_id)
                result.append(
                    Evidence(
                        key,
                        "S",
                        source.title,
                        span.text,
                        source.id,
                        version.id,
                        version.number,
                        span.page,
                    )
                )
            else:
                raise Problem("引用不在本次资料范围内", 404)
    return result


def plan_question(gateway, state, context, catalog, messages, rewrite=True):
    if not rewrite:
        return QueryPlan(
            intent="lookup", standalone_query=state.question, queries=[state.question]
        ), {}
    # Bound the title directory; exact selected versions and recent named titles
    # win over unrelated papers. The full corpus remains available to retrieval.
    terms = set(re.findall(r"[\w\u3400-\u9fff]+", state.question.lower()))
    ranked = sorted(catalog, key=lambda c: -sum(t in c["title"].lower() for t in terms))[:40]
    instruction = NLU_PROMPT
    if context.get("response_style", "grounded") != "grounded":
        instruction += "\n当前允许通用讨论。概念、想法、语言编辑不作为out_of_scope；只有明确要求伪造依据或执行越权动作才拒绝。讨论路线可没有资料。"
    plan, usage = gateway.structured(
        QueryPlan,
        instruction,
        {
            "question": state.question,
            "memory": state.memory,
            "history": messages[-9:],
            "catalog": ranked,
            "scope": state.snapshot.get("scope", "selected"),
            "style": context.get("response_style", "grounded"),
            "policy": context.get("retrieval_policy", "auto"),
            "project": context.get("project", {}),
            "task": context.get("mode", "chat"),
        },
        1400,
    )
    if set(plan.targets) - {c["source_id"] for c in catalog}:
        plan.needs_clarification, plan.clarification = True, "请明确当前资料范围内的比较对象。"
    vague = re.search(
        r"它(?!们)|这个方法|该方法|那个方法|\bit\b|\bthis method\b", state.question, re.I
    )
    named = any(e.lower() in state.question.lower() for e in plan.resolved_entities if e)
    if (
        vague
        and len(catalog) > 1
        and not state.memory.get("focus")
        and not named
        and len(messages) <= 1
    ):
        plan.needs_clarification, plan.clarification = True, "你指的是哪篇论文或哪个方法？"
    return plan, usage
