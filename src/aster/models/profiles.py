"""Public model profiles in SQL; credentials in a private, unexported local file."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import Field, field_validator, model_validator

from aster.domain.models import AppSetting, uid
from aster.domain.schemas import Input
from aster.domain.service import Problem


class ProfileInput(Input):
    name: str = Field(min_length=1, max_length=100)
    provider: Literal["compatible", "openai", "codex"] = "compatible"
    base_url: str = Field(default="http://127.0.0.1:8000/v1", max_length=500)
    model: str = Field(default="auto", min_length=1, max_length=200)
    max_tokens: int = Field(default=4096, ge=128, le=16384)
    timeout: int = Field(default=180, ge=15, le=900)
    api_key: str | None = Field(default=None, max_length=4000)
    key_env: str = Field(default="", max_length=100)
    clear_key: bool = False
    disable_thinking: bool = False

    @field_validator("key_env")
    @classmethod
    def valid_env(cls, value):
        if value and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", value):
            raise ValueError("环境变量名仅支持大写字母、数字和下划线")
        return value

    @model_validator(mode="after")
    def valid_endpoint(self):
        if self.provider == "openai" and self.model == "auto":
            raise ValueError("OpenAI API请填写具体模型名称；auto仅用于兼容服务或Codex")
        if self.provider != "codex":
            url = urlparse(self.base_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("请填写不含密钥、查询参数的 HTTP 服务地址")
        self.base_url = self.base_url.rstrip("/")
        return self


class DefaultsInput(Input):
    assistant: str
    reader: str


class ModelProfiles:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.lock = threading.RLock()
        self.key_path = db.data_dir / "model-keys.json"

    def state(self):
        with self.db.session() as s:
            row = s.get(AppSetting, "model_profiles")
            if row:
                return row.value
            old = s.get(AppSetting, "model")
            local = {
                "id": "local",
                "name": "Local Qwen",
                "provider": "compatible",
                "base_url": self.settings.model_url,
                "model": self.settings.model_name,
                "max_tokens": 4096,
                "timeout": 180,
                "key_env": "",
                "disable_thinking": True,
                **(old.value if old else {}),
            }
            profiles = [local]
            if shutil.which("codex"):
                profiles.append(
                    {
                        "id": "codex",
                        "name": "Codex",
                        "provider": "codex",
                        "base_url": "",
                        "model": "auto",
                        "max_tokens": 4096,
                        "timeout": 600,
                        "key_env": "",
                        "disable_thinking": False,
                    }
                )
            return {"profiles": profiles, "defaults": {"assistant": "local", "reader": "local"}}

    def _write_state(self, value):
        with self.db.session() as s:
            s.merge(AppSetting(key="model_profiles", value=value))

    def get(self, profile_id=None, purpose="assistant"):
        state = self.state()
        key = profile_id or state["defaults"][purpose]
        for profile in state["profiles"]:
            if profile["id"] == key:
                return dict(profile)
        raise Problem("模型配置不存在，请重新选择", 404)

    def _keys(self):
        if not self.key_path.exists():
            return {}
        return json.loads(self.key_path.read_text())

    def _write_keys(self, keys):
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".model-keys-", dir=self.key_path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(keys, f)
            os.chmod(name, 0o600)
            os.replace(name, self.key_path)
        finally:
            Path(name).unlink(missing_ok=True)

    def key(self, profile):
        profile = {"id": "local", **profile}
        if profile.get("key_env"):
            return os.getenv(profile["key_env"], "")
        with self.lock:
            value = self._keys().get(profile["id"], "")
        return value or (self.settings.model_key if profile["id"] == "local" else "local")

    def public(self):
        with self.lock:
            state = self.state()
            keys = self._keys()
            return {
                **state,
                "profiles": [
                    {
                        **p,
                        "has_key": bool(
                            keys.get(p["id"]) or (p.get("key_env") and os.getenv(p["key_env"]))
                        ),
                    }
                    for p in state["profiles"]
                ],
            }

    def save(self, body, profile_id=None):
        with self.lock:
            state = self.state()
            if profile_id:
                self.get(profile_id)
            profile_id = profile_id or uid()
            profile = {"id": profile_id, **body.model_dump(exclude={"api_key", "clear_key"})}
            if profile["provider"] == "codex":
                profile.update(base_url="", key_env="")
            keys = self._keys()
            if body.clear_key or profile["provider"] == "codex":
                keys.pop(profile_id, None)
            elif body.api_key is not None and body.api_key.strip():
                keys[profile_id] = body.api_key.strip()
            self._write_keys(keys)
            state["profiles"] = [profile if p["id"] == profile_id else p for p in state["profiles"]]
            if not any(p["id"] == profile_id for p in state["profiles"]):
                state["profiles"].append(profile)
            self._write_state(state)
            return self.public()

    def defaults(self, body):
        with self.lock:
            state = self.state()
            self.get(body.assistant)
            self.get(body.reader)
            state["defaults"] = body.model_dump()
            self._write_state(state)
            return self.public()

    def delete(self, profile_id):
        with self.lock:
            state = self.state()
            self.get(profile_id)
            if len(state["profiles"]) < 2:
                raise Problem("至少保留一个模型配置")
            if profile_id in state["defaults"].values():
                raise Problem("请先更换默认模型，再删除此配置", 409)
            state["profiles"] = [p for p in state["profiles"] if p["id"] != profile_id]
            self._write_state(state)
            keys = self._keys()
            keys.pop(profile_id, None)
            self._write_keys(keys)
            return self.public()

    def health(self, profile_id=None):
        config = self.get(profile_id)
        if config["provider"] == "codex":
            binary = shutil.which("codex")
            if not binary:
                return {
                    "connected": False,
                    "models": [],
                    "selected": None,
                    "config": config,
                    "error": "未找到 Codex CLI",
                }
            try:
                result = subprocess.run(
                    [binary, "login", "status"], capture_output=True, text=True, timeout=10
                )
                ok = result.returncode == 0
                return {
                    "connected": ok,
                    "models": [],
                    "selected": config["model"],
                    "config": config,
                    **({} if ok else {"error": "请在终端运行 codex login"}),
                }
            except (OSError, subprocess.TimeoutExpired):
                return {
                    "connected": False,
                    "models": [],
                    "selected": None,
                    "config": config,
                    "error": "Codex CLI 状态检查失败",
                }
        try:
            with httpx.Client(timeout=5, trust_env=False) as client:
                r = client.get(
                    config["base_url"] + "/models",
                    headers={"Authorization": "Bearer " + self.key(config)},
                )
                r.raise_for_status()
                names = [m["id"] for m in r.json().get("data", [])]
            selected = names[0] if config["model"] == "auto" and names else config["model"]
            return {
                "connected": bool(selected and selected in names),
                "models": names,
                "selected": selected,
                "config": config,
            }
        except Exception as e:
            return {
                "connected": False,
                "models": [],
                "selected": None,
                "config": config,
                "error": f"连接检查失败（{type(e).__name__}）；可保存配置后测试回答",
            }

    def resolve(self, config):
        if config["provider"] == "codex":
            return {
                **config,
                "model": config["model"] if config["model"] != "auto" else "codex-default",
            }
        if config["model"] != "auto":
            return config
        with httpx.Client(timeout=10, trust_env=False) as client:
            r = client.get(
                config["base_url"] + "/models",
                headers={"Authorization": "Bearer " + self.key(config)},
            )
            r.raise_for_status()
            names = r.json().get("data", [])
        if not names:
            raise Problem("服务未返回模型列表，请手动填写模型名称")
        return {**config, "model": names[0]["id"]}
