"""Optional Harbor integration checks; no task download or inference required.

PYTHONPATH=. uv run --no-project --with 'harbor==0.20.0' --with pytest \
    pytest -q tests/integration/test_bench_adapter.py
"""

import os
import pytest

pytest.importorskip("harbor")

from bench.adapter import MiniHarnessAgent


@pytest.fixture
def clean_settings(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MINI_HARNESS_") or name in {
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "LOCAL_API_KEY",
        }:
            monkeypatch.delenv(name)


def test_local_provider_reaches_guest_with_bounded_context(tmp_path, monkeypatch, clean_settings):
    agent = MiniHarnessAgent(
        logs_dir=tmp_path,
        model_name="local/qwen3.8-27b",
        base_url="http://127.0.0.1:8000/v1",
        max_tokens_main=4096,
        max_tokens_sub=2048,
        compact_limit=12000,
        clip_limit=12000,
    )
    assert agent._model_id == "qwen3.8-27b" and agent._api_key == "local"
    for name, value in agent._run_env.items():
        monkeypatch.setenv(name, value)
    from mini_harness.config import build_config

    cfg = build_config()
    assert cfg.provider == "local" and cfg.profile == "bench"
    assert cfg.model_main == cfg.model_sub == "qwen3.8-27b"
    assert cfg.clip_limit == cfg.compact_limit == 12000
    assert cfg.request_options()["max_tokens"] == 4096
    assert cfg.request_options()["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


@pytest.mark.parametrize("provider", ["openai", "deepseek"])
def test_cloud_provider_still_requires_credentials(tmp_path, clean_settings, provider):
    with pytest.raises(RuntimeError, match="set.*API_KEY"):
        MiniHarnessAgent(logs_dir=tmp_path, provider=provider)


def test_provider_mismatch_is_rejected(tmp_path, clean_settings):
    with pytest.raises(ValueError, match="conflicts"):
        MiniHarnessAgent(logs_dir=tmp_path, provider="local", model_name="openai/gpt-4.1")


def test_invalid_output_limit_is_rejected(tmp_path, clean_settings):
    with pytest.raises(ValueError, match="positive"):
        MiniHarnessAgent(logs_dir=tmp_path, provider="local", clip_limit=0)
