"""Instruction-only skills: lazy loading, versioned run snapshots, no shell grants."""

import hashlib
import json
from typing import Literal

from pydantic import Field
from aster.domain.models import AppSetting, uid
from aster.domain.schemas import Input
from aster.domain.common import Problem
from aster.skills.catalog import BUILTINS


class SkillInput(Input):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    instructions: str = Field(min_length=1, max_length=16000)
    category: Literal["reading", "thinking", "slides", "custom"] = "custom"
    enabled: bool = True
    source_url: str = Field(default="", max_length=500)


class Skills:
    def __init__(self, db):
        self.db = db

    def all(self):
        with self.db.session() as s:
            row = s.get(AppSetting, "skills")
            custom = row.value.get("items", []) if row else []
        return [*BUILTINS, *custom]

    def snapshot(self):
        return [
            {
                **s,
                "revision": hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()[:16],
            }
            for s in self.all()
            if s["enabled"]
        ]

    def save(self, body, key=None):
        if key and any(s["id"] == key for s in BUILTINS):
            raise Problem("内置技能可复制为自定义版本")
        with self.db.session() as s:
            row = s.get(AppSetting, "skills")
            items = row.value.get("items", []) if row else []
            if key and not any(i["id"] == key for i in items):
                raise Problem("技能不存在", 404)
            item = {"id": key or uid(), **body.model_dump(), "builtin": False, "origin": "用户配置"}
            items = [i for i in items if i["id"] != key] + [item]
            s.merge(AppSetting(key="skills", value={"items": items}))
        return item

    def delete(self, key):
        if any(s["id"] == key for s in BUILTINS):
            raise Problem("内置技能不可删除")
        with self.db.session() as s:
            row = s.get(AppSetting, "skills")
            items = row.value.get("items", []) if row else []
            if not any(i["id"] == key for i in items):
                raise Problem("技能不存在", 404)
            row.value = {"items": [i for i in items if i["id"] != key]}
        return {"deleted": True}
