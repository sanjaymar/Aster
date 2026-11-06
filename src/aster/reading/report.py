"""Readable, editable reports assembled from checked claims and original figures."""

from collections import OrderedDict
from aster.domain.common import CITATION
from aster.library.figures import selected


def section_title(claim):
    if claim.section:
        return claim.section
    text = claim.text
    if any(word in text for word in ("局限", "缺乏", "未进行", "进一步", "需通过")):
        return "局限与边界"
    if any(word in text for word in ("旨在", "目的", "研究问题")):
        return "研究问题"
    if any(word in text for word in ("队列", "样本量", "纳入", "例患者", "例未经")):
        return "样本与研究设计"
    if any(word in text for word in ("AUC", "显著", "升高", "降低", "鉴定", "发现")):
        return "主要结果"
    if any(word in text for word in ("技术", "方法", "平台", "分析", "质谱", "筛选")):
        return "方法与分析"
    return "主要结果"


def create(service, state, fields, artifact_id=None, expected_revision=None):
    versions = list(
        dict.fromkeys(
            (h.evidence.source_id, h.evidence.version_id)
            for h in state.hits
            if h.evidence.kind in {"C", "S"}
        )
    )
    visuals = selected(service, state.project_id, fields.get("figure_versions", versions), limit=5)
    papers = {s["id"]: s for s in service.sources(state.project_id)}
    source_ids = [sid for sid, _ in versions]
    title = (
        papers[source_ids[0]]["title"] if len(source_ids) == 1 else state.question[:120]
    ) + " · 精读笔记"
    groups = OrderedDict()
    for claim in state.claims:
        if claim.verdict == "supported":
            groups.setdefault(section_title(claim), []).append(claim)
    parts = [
        "## 文献信息",
        "| 文献 | 年份 | DOI |",
        "| --- | --- | --- |",
    ]
    for sid in source_ids:
        source = papers[sid]
        parts.append(
            f"| {source['title'].replace('|', '/')} | {source['year']} | {source['doi'] or '未记录'} |"
        )
    parts.extend(["", "## 核心要点"])
    supported = [c for group in groups.values() for c in group]
    for c in supported[:3]:
        parts.append("- " + CITATION.sub("", c.text).strip() + " " + " ".join(c.citations))
    for heading, claims in groups.items():
        parts.append("\n## " + heading)
        if any(word in heading for word in ["方法", "数据", "设计", "参数"]):
            parts += ["| 方法 / 设计要点 | 原文依据 |", "| --- | --- |"]
            parts.extend(
                "| "
                + CITATION.sub("", c.text).replace("|", "/").replace("\n", " ")
                + " | "
                + " ".join(c.citations)
                + " |"
                for c in claims
            )
        else:
            parts.extend(
                CITATION.sub("", c.text).strip() + " " + " ".join(c.citations) + "\n"
                for c in claims
            )
    if not groups:
        parts.append(state.answer)
    if visuals:
        parts.append("\n## 原文图版")
        for fig in visuals:
            parts.extend(
                [
                    f"\n### {fig['label']}",
                    f"![{fig['label']}]({fig['url']})",
                    f"同页图注：{fig['caption']}\n\n{fig['citation']}",
                ]
            )
    parts += [
        "\n## 我的理解与疑问",
        "- [ ] 这项工作最值得借鉴的设计是什么？",
        "- [ ] 哪些结论需要结合原图与补充材料再次核对？",
        "- [ ] 对我的研究有哪些启发？",
        "\n## 阅读范围",
        f"本次使用 {len(state.hits)} 段证据。"
        + ("图像来自固定版本 PDF，图注为同页原文。" if visuals else "所选版本未提取图版。")
        + "自动核查不替代阅读全文。",
    ]
    return service.save_record(
        state.project_id,
        title=title[:300],
        kind="note",
        content="\n\n".join(parts).replace("|\n\n|", "|\n|"),
        fields={
            **fields,
            "layout": "report",
            "origin": "generated",
            "source_ids": source_ids,
            "source_id": source_ids[0] if len(source_ids) == 1 else None,
        },
        author="assistant",
        asset_ids=[f["asset_id"] for f in visuals],
        artifact_id=artifact_id,
        expected_revision=expected_revision,
    )
