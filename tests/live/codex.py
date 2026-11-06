"""Synthetic Codex tool-decision check; never sends user research materials."""

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from mini_harness.agent import MiniHarnessAgent
from mini_harness.tool.box import ToolDefinition, ToolExecution
from aster.agent.config import ResearchConfig
from aster.domain.schemas import Input
from aster.models.codex import CodexClient
from aster.app.settings import Settings


class Lookup(Input):
    key: str


def main():
    calls = []

    def lookup(args):
        calls.append(args.key)
        return json.dumps({"value": "SYNTHETIC42"})

    with tempfile.TemporaryDirectory(prefix="aster-codex-test-") as directory:
        cfg = ResearchConfig(
            provider="codex",
            model_main="codex-default",
            model_sub="codex-default",
            work_space=Path(directory),
            max_turns_main=3,
            track_files=False,
        )

        class Agent(MiniHarnessAgent):
            def _save_memory(self, **_):
                pass

        agent = Agent(
            [
                ToolDefinition(
                    "lookup_value",
                    "Look up a synthetic value for the given key.",
                    Lookup,
                    lookup,
                    False,
                )
            ],
            cfg=cfg,
        )
        agent.message = [
            {
                "role": "system",
                "content": "For this synthetic test, always use lookup_value exactly once to look up the key 'test'. Then reply with just the returned value. Do not use any built-in tools.",
            },
            {"role": "user", "content": "What is the synthetic test value?"},
        ]
        with CodexClient({"model": "codex-default", "timeout": 90}) as client:
            result = agent._run_turn(
                client, ToolExecution(agent.regis, lambda *_a, **_k: False, cfg=cfg), cfg=cfg
            )
        answer = agent.message[-1].get("content", "")
        assert result.outcome == "completed" and calls == ["test"] and "SYNTHETIC42" in answer, (
            result,
            calls,
            answer,
        )
        report = {
            "kind": "synthetic_codex_tool_bridge",
            "result": asdict(result),
            "answer": answer,
            "calls": calls,
        }
        path = Settings.from_env().data_dir / "experiments/reading/codex.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2))
        print("Codex tool bridge passed", path)


if __name__ == "__main__":
    main()
