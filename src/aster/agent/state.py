"""Working state for one research turn; database models remain the durable record."""

from dataclasses import dataclass, field
from typing import Any

from aster.agent.llm import QueryPlan, EvidenceDecision
from mini_harness.state import AgentState as HarnessState


@dataclass
class AgentState:
    run_id: str
    project_id: str
    conversation_id: str
    question: str
    snapshot: dict
    allowed: dict = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    plan: QueryPlan | None = None
    decision: EvidenceDecision | None = None
    hits: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    answer: str = ""
    created: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    generation_result: Any = None
    harness: HarnessState = field(default_factory=HarnessState)

    def summary(self):
        return {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "engine": "mini-harness",
            "intent": self.plan.intent if self.plan else None,
            "query": self.plan.standalone_query if self.plan else self.question,
            "answerability": self.decision.action if self.decision else None,
            "evidence_ids": [hit.evidence.id for hit in self.hits],
            "artifact_ids": self.created,
            "usage": self.usage,
            "route": self.plan.route if self.plan else None,
            "execution": self.harness.public(),
        }
