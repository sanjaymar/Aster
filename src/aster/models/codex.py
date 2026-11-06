"""Codex CLI as a text/tool-decision provider for the *outer* mini-harness loop.

Each call is ephemeral and runs in an empty directory. User plugins, shell,
browser and hooks are disabled. Only Aster executes the returned business tools.
"""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from openai.types.chat import ChatCompletion
from aster.domain.service import Problem

DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "content": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"name": {"type": "string"}, "arguments": {"type": "string"}},
                "required": ["name", "arguments"],
            },
        },
    },
    "required": ["content", "tool_calls"],
}


class CodexClient:
    def __init__(self, config, cancelled=lambda: False):
        self.config, self.cancelled = config, cancelled
        self.chat = SimpleNamespace(completions=self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def create(self, messages, tools=None, **options):
        binary = shutil.which("codex")
        if not binary:
            raise Problem("未找到 Codex CLI；请先安装并运行 codex login")
        prompt = (
            "You are a text backend for Aster. Do not inspect files, use built-in tools or access the network. "
            "The outer Aster application executes tools. Given the conversation and tool schemas below, "
            "return one JSON decision. To use tools, leave content empty and emit tool_calls with a valid tool name and JSON-encoded arguments. "
            "Otherwise put your final answer in content and return an empty tool_calls array. "
            "Follow the system messages inside the conversation for the actual research task. "
            "If a JSON answer is requested, put that JSON string inside content.\n"
            + json.dumps(
                {
                    "conversation": messages,
                    "tools": tools or [],
                    "max_output_tokens": options.get("max_tokens", 4096),
                },
                ensure_ascii=False,
            )
        )
        with tempfile.TemporaryDirectory(prefix="aster-codex-") as directory:
            root = Path(directory)
            (root / "schema.json").write_text(json.dumps(DECISION_SCHEMA))
            command = [
                binary,
                "exec",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "-C",
                directory,
                "-c",
                'approval_policy="never"',
                "-c",
                "features.shell_tool=false",
                "-c",
                "features.apps=false",
                "-c",
                "features.hooks=false",
                "-c",
                "features.browser_use=false",
                "-c",
                "features.computer_use=false",
                "-c",
                'web_search="disabled"',
                "--output-schema",
                str(root / "schema.json"),
                "--output-last-message",
                str(root / "answer.json"),
                "--json",
            ]
            if self.config["model"] not in {"auto", "codex-default"}:
                command.extend(["--model", self.config["model"]])
            command.append("-")
            # No prompt, credential, stdout or stderr is exposed in process arguments/logs.
            with (root / "events.jsonl").open("w+") as out, (root / "stderr").open("w+") as err:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=out,
                    stderr=err,
                    text=True,
                    start_new_session=True,
                )
                start = time.monotonic()
                try:
                    process.stdin.write(prompt)
                    process.stdin.close()
                    while process.poll() is None:
                        if self.cancelled():
                            raise KeyboardInterrupt
                        if time.monotonic() - start > self.config["timeout"]:
                            raise Problem("Codex 回答超时，请重试或调整等待时间")
                        time.sleep(0.1)
                    if process.returncode or not (root / "answer.json").is_file():
                        raise Problem("Codex 未返回回答，请检查登录状态、模型名称和账户额度")
                    decision = json.loads((root / "answer.json").read_text())
                    usage = {}
                    for line in (root / "events.jsonl").read_text().splitlines():
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("type") == "turn.completed":
                            usage = event.get("usage", {})
                    calls = [
                        {
                            "id": "call_" + uuid4().hex,
                            "type": "function",
                            "function": {"name": c["name"], "arguments": c["arguments"]},
                        }
                        for c in decision["tool_calls"]
                    ]
                    # A CLI-produced decision never gains tools beyond this call's registry.
                    names = {t["function"]["name"] for t in tools or []}
                    if any(c["function"]["name"] not in names for c in calls):
                        raise Problem("Codex 请求了当前未开放的工具")
                    return ChatCompletion.model_validate(
                        {
                            "id": "codex-" + uuid4().hex,
                            "object": "chat.completion",
                            "created": int(time.time()),
                            "model": self.config["model"],
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": "tool_calls" if calls else "stop",
                                    "message": {
                                        "role": "assistant",
                                        "content": decision["content"],
                                        "tool_calls": calls or None,
                                    },
                                }
                            ],
                            "usage": {
                                "prompt_tokens": usage.get("input_tokens", 0),
                                "completion_tokens": usage.get("output_tokens", 0),
                                "total_tokens": usage.get("input_tokens", 0)
                                + usage.get("output_tokens", 0),
                            },
                        }
                    )
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()

    def stream(self, **options):
        return CompletionStream(self.create(**options))


class CompletionStream:
    def __init__(self, completion):
        self.completion = completion

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        content = self.completion.choices[0].message.content
        if content:
            yield SimpleNamespace(type="content.delta", delta=content)

    def get_final_completion(self):
        return self.completion
