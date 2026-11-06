"""Provider selection without leaking credentials into durable run context."""

import httpx
from openai import OpenAI
from aster.models.codex import CodexClient


def model_client(profiles, config, cancelled=lambda: False):
    if config.get("provider") == "codex":
        return CodexClient(config, cancelled)
    return OpenAI(
        api_key=profiles.key(config),
        base_url=config["base_url"],
        max_retries=0,
        timeout=httpx.Timeout(config["timeout"], connect=10),
        http_client=httpx.Client(trust_env=False, timeout=config["timeout"]),
    )
