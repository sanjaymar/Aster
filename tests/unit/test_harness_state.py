from dataclasses import replace
from mini_harness.state import AgentState, anchors, context_size
from mini_harness.compact import CompactContent
from mini_harness.config import Config


def test_telemetry_excludes_model_reasoning_and_tool_text():
    state = AgentState()
    state.record("reasoning", {"text": "private"})
    state.record("text", {"text": "draft"})
    state.record("tool_start", {"name": "read", "id": "one"})
    state.record("tool_end", {"name": "read", "id": "one", "content": "large document", "ok": True})
    state.record("usage", {"prompt": 10, "completion": 3})
    assert state.public()["calls"] == 1
    assert state.usage == {"prompt_tokens": 10, "completion_tokens": 3}
    assert "private" not in str(state.public()) and "large document" not in str(state.public())
    for _ in range(250):
        state.record("turn", {"turn": 1})
    assert len(state.events) == 200


def test_compaction_preserves_tool_pairs_and_user_constraints(monkeypatch):
    history = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Do not change public APIs."},
        {
            "role": "assistant",
            "tool_calls": [{"id": "call", "function": {"name": "read", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call", "content": "file"},
        {"role": "assistant", "content": "result"},
    ]
    compact = CompactContent()
    cfg = replace(Config(), recent_keep=2)
    cut = compact._get_cut(history, cfg)
    assert cut == 2
    retained = anchors(history)
    monkeypatch.setenv("MINI_HARNESS_CONTEXT_POLICY", "adaptive")
    result = compact._compact_text(cut, "summary", history, cfg, retained)
    assert "Do not change public APIs." in result[1]["content"]
    assert result[2]["tool_calls"][0]["id"] == result[3]["tool_call_id"]
    second = compact._compact_text(cut, "another summary", result, cfg, retained)
    assert "Do not change public APIs." in second[1]["content"]
    monkeypatch.setenv("MINI_HARNESS_CONTEXT_POLICY", "baseline")
    assert (
        "Do not change public APIs."
        not in compact._compact_text(cut, "summary", history, cfg, retained)[1]["content"]
    )


def test_preflight_counts_new_large_tool_output_before_next_request():
    small = [{"role": "user", "content": "question"}]
    assert context_size(small + [{"role": "tool", "content": "中文" * 5000}]) > 10000
    assert context_size(small) < 100
