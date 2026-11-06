"""Check the presentation transformation for facts absent from verified material."""

from typing import Literal
from pydantic import Field
from aster.domain.schemas import Input
from aster.domain.common import Problem
from aster.slides.schema import Table


class Issue(Input):
    page: int = Field(ge=0, description="1-based slide number; 0 is the deck title")
    part: Literal[
        "title", "subtitle", "bullets", "steps", "table", "takeaway", "notes", "image_caption"
    ]
    reason: str = Field(max_length=240)


class Review(Input):
    issues: list[Issue] = Field(default_factory=list, max_length=30)


def check(deck, material, figures, gateway):
    review, usage = gateway.structured(
        Review,
        "检查汇报草稿是否增添了核对材料没有支持的科学事实。材料与原文图注是唯一事实基础。"
        "逐页检查标题、要点、流程、表格、结论、讲稿和图片说明；指出错误或无依据的part。"
        "尤其检查样本量、数值、平台覆盖范围、因果推断与临床外推，不能用常识补成本文实测结果。"
        "标题等纯导航文字、忠实概括和明确标为待验证的问题不算错误。引用编号本身不证明新主张。"
        "issues仅列必须移除的内容，page从1计数，part是整个字段名；总体标题有错误时page=0、part=title。"
        "不需要复述正确内容。",
        {"verified_material": material, "original_figures": figures, "draft": deck.model_dump()},
        2000,
    )
    # Never silently keep an unsupported scientific assertion just to fill a layout.
    for issue in review.issues:
        if issue.page == 0 and issue.part == "title":
            deck.title = "文献汇报"
            continue
        if not 1 <= issue.page <= len(deck.slides):
            raise Problem("汇报核查返回了无效页码，未保存结果")
        slide = deck.slides[issue.page - 1]
        if issue.part == "title":
            slide.title = "研究证据"
        elif issue.part == "table":
            slide.table = Table()
            slide.layout = "figure" if slide.image_asset_id else "bullets"
        elif issue.part in {"bullets", "steps"}:
            setattr(slide, issue.part, [])
            if issue.part == "steps":
                slide.layout = "figure" if slide.image_asset_id else "bullets"
        else:
            setattr(slide, issue.part, "")
    return review.model_dump(), usage
