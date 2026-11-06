"""Working state, compact session snapshots, and versioned confirmed project records."""

import json
from sqlalchemy import select
from aster.domain.models import MemorySnapshot, Artifact, ArtifactVersion


def compact_state(state, budget=6000):
    """Compact expendable history, retaining user constraints and current focus."""
    state = {**state}
    before = len(json.dumps(state, ensure_ascii=False))
    if before > budget:
        state["recent_questions"] = state.get("recent_questions", [])[-2:]
        state["evidence_refs"] = state.get("evidence_refs", [])[:16]
        state["compacted"] = True
    return state


class Memory:
    def __init__(self, service, budget=6000):
        self.service, self.db, self.budget = service, service.db, budget

    def latest(self, project_id, conversation_id):
        with self.db.session() as s:
            self.service.project(s, project_id)
            row = s.scalar(
                select(MemorySnapshot)
                .where(
                    MemorySnapshot.project_id == project_id,
                    MemorySnapshot.conversation_id == conversation_id,
                )
                .order_by(MemorySnapshot.created_at.desc())
                .limit(1)
            )
            return (
                row.state
                if row
                else {
                    "schema_version": 1,
                    "focus": [],
                    "constraints": [],
                    "open_questions": [],
                    "recent_questions": [],
                    "evidence_refs": [],
                    "turns": 0,
                }
            )

    def project_records(self, project_id, allowed_version_ids):
        with self.db.session() as s:
            self.service.project(s, project_id)
            return [
                {"id": v.id, "title": a.title, "content": v.content[:1000]}
                for v, a in s.execute(
                    select(ArtifactVersion, Artifact)
                    .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                    .where(
                        Artifact.project_id == project_id,
                        Artifact.status == "confirmed",
                        ArtifactVersion.id.in_(allowed_version_ids),
                        ArtifactVersion.author == "human",
                    )
                )
            ]

    def update(self, project_id, conversation_id, run_id, prompt, plan, decision, refs, scope_ids):
        old = self.latest(project_id, conversation_id)
        constraints = list(old.get("constraints", []))
        relevant = plan is not None and getattr(plan, "intent", None) != "out_of_scope"
        # Only a verbatim user statement may become a durable user constraint.
        for text in getattr(plan, "constraints", []) if relevant else []:
            if text and text in prompt and text not in constraints:
                constraints.append(text)
        focus = [e for e in (getattr(plan, "resolved_entities", []) if relevant else []) if e]
        if not focus:
            focus = old.get("focus", [])
        state = {
            "schema_version": 1,
            "focus": focus[:12],
            "constraints": constraints,
            "open_questions": list(getattr(decision, "missing_facets", []) if decision else []),
            "recent_questions": [*old.get("recent_questions", []), prompt][-6:],
            "evidence_refs": list(dict.fromkeys(r for r in refs if r in scope_ids)),
            "turns": old.get("turns", 0) + 1,
            "answerability": getattr(decision, "action", "clarify") if decision else "clarify",
            "compacted": False,
        }
        state = compact_state(state, self.budget)
        # Constraints are not silently dropped to meet a token budget. If user
        # constraints themselves are large, store all and report the actual size.
        summary = (
            "当前对象："
            + "、".join(state["focus"])
            + "\n用户约束："
            + "；".join(state["constraints"])
            + "\n待解决："
            + "；".join(state["open_questions"])
        )
        estimate = max(1, len(json.dumps(state, ensure_ascii=False)) // 2)
        with self.db.session() as s:
            row = MemorySnapshot(
                project_id=project_id,
                conversation_id=conversation_id,
                run_id=run_id,
                state=state,
                summary=summary,
                token_estimate=estimate,
            )
            s.add(row)
            s.flush()
            return {"id": row.id, **state, "token_estimate": estimate, "summary": summary}

    def inspect(self, project_id, conversation_id=None):
        with self.db.session() as s:
            self.service.project(s, project_id)
            stmt = select(MemorySnapshot).where(MemorySnapshot.project_id == project_id)
            if conversation_id:
                stmt = stmt.where(MemorySnapshot.conversation_id == conversation_id)
            from aster.domain.service import plain

            return [
                plain(r)
                for r in s.scalars(stmt.order_by(MemorySnapshot.created_at.desc()).limit(30))
            ]
