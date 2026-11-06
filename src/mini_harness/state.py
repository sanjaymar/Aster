"""Provider-independent run state and bounded observable execution history.

Used by both the research application and coding benchmarks. This records
operations, not private model reasoning, and does not grant extra tools.
"""

import json
import time
from dataclasses import dataclass, field


@dataclass
class AgentState:
    task: str = ""
    steps: int = 0
    calls: int = 0
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    events: list = field(default_factory=list)
    memory: dict = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    def record(self, kind, data):
        if kind in {"text", "draft_text", "reasoning"}:
            return
        if kind == "turn":
            self.steps = data.get("turn", self.steps)
        if kind == "tool_start":
            self.calls += 1
        if kind == "usage":
            self.usage["prompt_tokens"] += data.get("prompt", 0)
            self.usage["completion_tokens"] += data.get("completion", 0)
        # Keep metadata bounded; full tool output belongs to the transcript.
        details = {k: v for k, v in data.items() if k not in {"content", "text"}}
        self.events.append(
            {
                "kind": kind,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000, 2),
                **details,
            }
        )
        self.events[:] = self.events[-200:]

    def public(self):
        return {
            "steps": self.steps,
            "calls": self.calls,
            "usage": self.usage,
            "events": self.events,
        }


def context_size(messages):
    """Conservative preflight estimate; never reported as measured API usage."""
    text = json.dumps(messages, ensure_ascii=False)
    cjk = sum("\u3400" <= c <= "\u9fff" for c in text)
    return cjk + (len(text) - cjk + 2) // 3


def anchors(messages, budget=3000):
    """Verbatim user requirements survive lossy summaries; no inferred facts."""
    values = [str(m.get("content") or "") for m in messages if m.get("role") == "user"]
    chosen, size = [], 0
    # Preserve the task first, then the newest corrections. All text is verbatim.
    ordered = values[:1] + list(reversed(values[1:]))
    for value in ordered:
        if size + len(value) <= budget:
            chosen.append(value)
            size += len(value)
        elif not chosen and value:
            chosen.append(value[:budget])
            size = budget
    return list(dict.fromkeys(chosen))
