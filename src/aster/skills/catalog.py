"""Reviewed instruction workflows. No upstream scripts run implicitly.

Methods adapted for Aster's evidence tools; not full upstream skill runtimes.
Upstream MIT projects checked on 2026-11-06: K-Dense scientific-agent-skills
(56,252 stars), ningzimu/codex-ppt-skill (7,674 stars). Stars are discovery
signals, not a scientific-quality rating. See each source's own license.
"""

SCIENCE = "https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/"


def skill(key, name, description, category, output, instructions, source="", requires="论文或选段"):
    return dict(
        id=key,
        name=name,
        description=description,
        category=category,
        output=output,
        instructions=instructions,
        source_url=source,
        requires=requires,
        enabled=True,
        builtin=True,
        origin="Aster 证据工具适配；不是上游完整运行环境",
        license="MIT · 方法参考" if source else "Aster",
    )


BUILTINS = [
    skill(
        "paper-reading",
        "论文精读",
        "整理研究问题、方法、发现和局限",
        "reading",
        "分章节阅读笔记",
        "先明确论文与版本。检索研究问题、方法、数据、结果、局限，按这些标题组织笔记。具体发现和数值逐项关联原文引用，保留样本量、单位和适用条件。没读到的图表或补充数据标为待核对。最后列我的理解和待追问问题，推断不得写成作者结论。",
        SCIENCE + "scientific-critical-thinking",
    ),
    skill(
        "method-card",
        "方法卡片",
        "提取方法的输入、步骤、参数与边界",
        "reading",
        "方法步骤与参数表",
        "只提取实际报告的方法，组织为目的、输入、数据处理、关键参数、输出、验证和局限。参数表保留值、单位、适用条件和引用，缺项写未报告；不能猜测默认值或从摘要推断实验细节。",
    ),
    skill(
        "literature-review",
        "文献对照",
        "对照所选论文的设计与结论",
        "reading",
        "比较表与分歧说明",
        "确定比较维度，分别检索各篇论文，形成研究对象、数据、方法、结果、局限的对照。保留条件差异与冲突，每项具体事实有对应引用。说明当前纳入范围，不把本地库内比较声称为全网系统综述，也不生成虚构筛选数量。",
        SCIENCE + "literature-review",
        requires="至少两篇论文",
    ),
    skill(
        "critical-thinking",
        "证据审阅",
        "检查研究设计、混杂与结论范围",
        "thinking",
        "优点、局限与追问清单",
        "先找到被审阅的主张及其依据，再检查独立实验单位、对照、选择偏倚、混杂、多重检验、效应量和不确定性。按原文观察、引用、对结论的影响、待确认问题组织。区分报告不足与确实没做，区分相关性与因果。不能仅凭摘要断言论文错误。",
        SCIENCE + "scientific-critical-thinking",
    ),
    skill(
        "hypothesis",
        "想法推敲",
        "讨论解释、反例与验证思路",
        "thinking",
        "待验证假设与下一步",
        "复述用户想法，分开已有依据、尚未证实的解释、竞争解释。建议一个最小验证及能够反驳假设的观察结果。可以讨论通用知识，但不能编造文献、实验已经完成或预期效果数值。",
        requires="一个问题或想法",
    ),
    skill(
        "research-slides",
        "组会汇报",
        "把论文与笔记组织成可编辑汇报",
        "slides",
        "幻灯片提纲、讲稿与 PPTX",
        "围绕一个研究问题组织汇报：背景、数据与设计、方法、关键发现、局限、讨论。一页一个核心问题，最多四条短要点，细节进讲者备注。结论须有原文引用，缺失结果留待补。先给可审阅提纲，不把生成内容称作已经验证的实验。",
        "https://github.com/ningzimu/codex-ppt-skill",
        requires="论文或已保存笔记；整页生图需另配图片模型",
    ),
]
