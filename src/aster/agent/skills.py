"""Instruction-only skills: lazy loading, versioned run snapshots, no shell grants."""

import hashlib
import json
from typing import Literal

from pydantic import Field
from aster.domain.models import AppSetting, uid
from aster.domain.schemas import Input
from aster.domain.service import Problem

SCIENTIFIC = "https://github.com/K-Dense-AI/scientific-agent-skills"


class SkillInput(Input):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    instructions: str = Field(min_length=1, max_length=16000)
    category: Literal["reading", "thinking", "experiment", "writing", "custom"] = "custom"
    enabled: bool = True
    source_url: str = Field(default="", max_length=500)


def builtin(key, name, description, category, instructions, reference=""):
    return {
        "id": key,
        "name": name,
        "description": description,
        "category": category,
        "instructions": instructions,
        "enabled": True,
        "builtin": True,
        "source_url": reference,
        "origin": "Aster 原创工作流；参考链接仅供方法对照",
    }


BUILTINS = [
    builtin(
        "paper-reading",
        "论文精读",
        "提取问题、方法、结果与局限，逐项保留原文位置",
        "reading",
        "先确认论文与版本，检索摘要、方法、结果、局限。按研究问题、数据与样本、方法、主要发现、局限、值得追问的问题组织笔记。每个具体发现关联实际读取的引用；数值保留单位、分母和条件。没读到全文或图表时直接标为缺失，不能补写图中信息。个人启发单列，不与作者结论混合。",
    ),
    builtin(
        "literature-review",
        "文献对照",
        "按研究问题比较多篇论文，整理证据表与分歧",
        "reading",
        "确定比较维度后分别检索各篇论文，形成研究对象、样本、方法、主要结果、适用条件、局限的对照表。标明实际纳入的论文与不足，保留来源冲突。只覆盖当前知识库，不能声称完成了全网系统综述或虚构PRISMA筛选数量。",
        SCIENTIFIC + "/tree/main/skills/literature-review",
    ),
    builtin(
        "critical-thinking",
        "证据审阅",
        "检查主张、设计、混杂与统计解释",
        "thinking",
        "先定位被审阅的主张和证据，再检查比较对象、实验单位、对照、混杂、多重检验、效应量及不确定性。用观察、引用、对结论的影响、可行补救四列呈现关键问题。区分报告不充分与确实没做；不能仅凭摘要断言方法错误，也不能把相关性写成因果。",
        SCIENTIFIC + "/tree/main/skills/scientific-critical-thinking",
    ),
    builtin(
        "hypothesis",
        "假设推敲",
        "把想法变成可证伪的假设与验证路线",
        "thinking",
        "先复述用户想法，分别写已有事实、尚未证实的解释和关键假设。提出至少一个竞争解释和能够区分它们的最小验证实验；说明观测什么结果会反驳假设。可以在没有论文时讨论思路；引入论文事实则先检索。不得虚构实验已经执行或预期效应量。",
    ),
    builtin(
        "experiment-design",
        "实验设计",
        "整理因素、对照、数据表、质控与分析计划",
        "experiment",
        "根据目标整理实验单位、主要终点、自变量、对照、随机化、批次、盲法、质控、排除规则、分析步骤、待决事项。缺少样本量依据时提供估算需要的输入，不编造功效结论。代谢组学项目考虑空白、混合QC、内标、注射顺序和漂移；其他领域按项目术语调整。输出明确为未执行方案。",
    ),
    builtin(
        "scientific-writing",
        "论文写作",
        "依据用户记录起草或修改段落，保留引用和待补内容",
        "writing",
        "先确认段落目的与现有提纲，再使用实际材料组织论点。方法写实际执行条件，结果只写已提供数据；空缺用待补标记。保留所有支持当前句子的真实引用，对推断和研究局限作明确表达。不编造实验、文献、DOI、显著性或贡献；未执行方案使用将来时。",
        SCIENTIFIC + "/tree/main/skills/scientific-writing",
    ),
    builtin(
        "reviewer-response",
        "审稿回复",
        "逐条整理意见、回应理由与修改位置",
        "writing",
        "拆分审稿意见，逐条列回应、需要补做的分析、已修改位置及待处理项。用户未提供修订证据时不能声称已修改或已补实验。不同意意见时以实际证据和适用范围说明理由，避免虚构页码、行号。",
    ),
]


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
