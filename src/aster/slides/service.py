"""Presentation drafts remain editable records; every citation is checked in scope."""

import io
import json
import zipfile
from aster.domain.common import CITATION, Problem
from aster.domain.models import Asset
from aster.slides.schema import Deck


class Slides:
    def __init__(self, service):
        self.service = service

    def validate(self, project_id, deck):
        for slide in deck.slides:
            if slide.table.rows and (
                not slide.table.headers
                or any(len(row) != len(slide.table.headers) for row in slide.table.rows)
            ):
                raise Problem("表格每行须与表头列数一致")
            if any(
                len(cell) > 120 for row in [slide.table.headers, *slide.table.rows] for cell in row
            ):
                raise Problem("表格单元格最多120字")
            if any(len(b) > 500 for b in slide.bullets):
                raise Problem("每条要点最多500字")
            for citation in slide.citations:
                if not CITATION.fullmatch(citation):
                    raise Problem("幻灯片引用格式无效")
            if slide.image_asset_id:
                with self.service.db.session() as session:
                    asset = session.get(Asset, slide.image_asset_id)
                    if (
                        not asset
                        or asset.project_id != project_id
                        or not asset.media_type.startswith("image/")
                    ):
                        raise Problem("图片不属于当前项目", 404)
                    from PIL import Image, UnidentifiedImageError

                    try:
                        with Image.open(self.service.files / asset.storage_key) as image:
                            if image.format not in {"PNG", "JPEG", "WEBP"}:
                                raise Problem("配图支持 PNG、JPEG、WebP")
                            image.verify()
                    except (OSError, UnidentifiedImageError) as error:
                        raise Problem("配图损坏或格式不支持") from error

    def save(
        self,
        project_id,
        deck,
        artifact_id=None,
        expected_revision=None,
        fields=None,
        author="human",
    ):
        deck = Deck.model_validate(deck)
        self.validate(project_id, deck)
        if artifact_id:
            with self.service.db.session() as session:
                previous = self.service._artifact_dict(
                    session, self.service.artifact(session, project_id, artifact_id)
                )
            fields = {**previous["version"]["fields"], **(fields or {})}
        content = "\n\n".join(
            "## "
            + s.title
            + "\n\n"
            + "\n".join("- " + b for b in s.bullets)
            + "\n\n"
            + s.subtitle
            + "\n\n"
            + s.takeaway
            + "\n\n"
            + "\n".join(step.label + "：" + step.detail for step in s.steps)
            + "\n\n"
            + "\n".join(" | ".join(row) for row in [s.table.headers, *s.table.rows])
            + "\n\n"
            + s.notes
            + "\n\n"
            + " ".join(s.citations)
            for s in deck.slides
        )
        return self.service.save_record(
            project_id,
            title=deck.title,
            kind="deck",
            content=content,
            fields={**(fields or {}), "deck": deck.model_dump()},
            artifact_id=artifact_id,
            expected_revision=expected_revision,
            author=author,
            asset_ids=[s.image_asset_id for s in deck.slides if s.image_asset_id],
        )

    def generate(self, project_id, question, answer, allowed, gateway, fields):
        from aster.library.figures import selected

        used_refs = list(dict.fromkeys(f"[[{k}:{v}]]" for k, v in CITATION.findall(answer)))
        versions = list(
            dict.fromkeys(
                (e.source_id, e.version_id)
                for e in allowed.values()
                if e.citation in used_refs and e.kind in {"C", "S"}
            )
        )
        figures = selected(self.service, project_id, fields.get("figure_versions", versions))
        figure_aliases = {f"F{i + 1}": fig for i, fig in enumerate(figures)}
        answer_refs = list(dict.fromkeys([*used_refs, *(f["citation"] for f in figures)]))
        valid = {e.citation for e in allowed.values()} | {f["citation"] for f in figures}
        aliases = {f"R{i + 1}": ref for i, ref in enumerate(answer_refs)}
        material = answer
        for alias, ref in aliases.items():
            material = material.replace(ref, "[" + alias + "]")
        deck, usage = gateway.structured(
            Deck,
            "把已核对材料规划成8到12页专业科研汇报，除非用户指定其他页数。主题academic蓝白学术风。"
            "先组织叙事：问题→研究设计→方法流程→关键结果与原图→证据局限→讨论。每页一句明确结论作为标题，subtitle说明上下文，takeaway是页底核心判断。"
            "选择合适layout：cover封面，flow方法流程，table结果对照，figure原文图解，comparison比较，closing讨论。不得每页都堆bullet。"
            "至少一页flow且使用steps(label,detail)，有明确对照数据时使用table(headers,rows)。优先使用提供的F编号原图；不能编造实验图表或数值。"
            "表格只组织已核对的样本量、AUC或其他明确报告的事实，不从常识猜测GC-MS/LC-MS覆盖范围、仪器参数或工作原理。"
            "每页最多4条短要点，每条不超过45字；flow步骤最多5项。details与讲稿在notes，解释适用条件和局限，避免重复念要点。"
            "citations只填写R编号；image_asset_id只能填F编号或null，image_caption写对该原图的谨慎说明。正文不放引用标记。不可从图注猜测没报告的数值。",
            {
                "question": question,
                "checked_answer": material,
                "allowed_references": list(aliases),
                "figures": [
                    {"id": key, "caption": fig["caption"], "page": fig["page"], "kind": fig["kind"]}
                    for key, fig in figure_aliases.items()
                ],
            },
            6500,
        )
        from aster.slides.review import check

        review, review_usage = check(deck, material, list(figure_aliases.values()), gateway)
        for key, value in review_usage.items():
            usage[key] = usage.get(key, 0) + value
        fields = {**fields, "review": review}
        for slide in deck.slides:
            slide.citations = [aliases.get(ref.strip("[]"), ref) for ref in slide.citations]
            if set(slide.citations) - valid or set(slide.citations) - set(answer_refs):
                raise Problem("汇报生成了未经核对的引用，请重试")
            if slide.image_asset_id:
                fig = figure_aliases.get(slide.image_asset_id)
                if not fig:
                    raise Problem("汇报使用了未知配图，请重试")
                slide.image_asset_id = fig["asset_id"]
                slide.image_caption = slide.image_caption or fig["label"]
                if fig["citation"] not in slide.citations:
                    slide.citations.append(fig["citation"])
            for alias, ref in aliases.items():
                slide.bullets = [b.replace("[" + alias + "]", ref) for b in slide.bullets]
                slide.notes = slide.notes.replace("[" + alias + "]", ref)
        return self.save(project_id, deck, fields=fields, author="assistant"), usage

    def load(self, project_id, artifact_id):
        with self.service.db.session() as session:
            record = self.service._artifact_dict(
                session, self.service.artifact(session, project_id, artifact_id)
            )
        if record["kind"] != "deck":
            raise Problem("不是汇报文档")
        deck = Deck.model_validate(record["version"]["fields"]["deck"])
        self.validate(project_id, deck)
        return deck

    def sources(self, project_id, deck):
        refs = set(c for slide in deck.slides for c in slide.citations)
        with self.service.db.session() as session:
            return {
                ref: self.service.evidence(session, project_id, *CITATION.fullmatch(ref).groups())
                for ref in refs
            }

    def export(self, project_id, artifact_id):
        from aster.slides.export import pptx

        deck = self.load(project_id, artifact_id)
        return pptx(deck, self.sources(project_id, deck), self.service, project_id)

    def pack(self, project_id, artifact_id):
        deck = self.load(project_id, artifact_id)
        sources = self.sources(project_id, deck)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            outline = deck.model_dump()
            for index, slide in enumerate(deck.slides):
                if slide.image_asset_id:
                    with self.service.db.session() as session:
                        asset = session.get(Asset, slide.image_asset_id)
                        path = self.service.files / asset.storage_key
                    filename = f"figures/slide-{index + 1}{path.suffix}"
                    archive.write(path, filename)
                    outline["slides"][index]["image_file"] = filename
            archive.writestr("outline.json", json.dumps(outline, ensure_ascii=False, indent=2))
            archive.writestr(
                "sources.json", json.dumps(sources, ensure_ascii=False, indent=2, default=str)
            )
            archive.writestr(
                "TASK.md",
                "# "
                + deck.title
                + "\n\n使用已安装的 codex-ppt skill，读取 outline.json 和 sources.json。\n"
                "只使用这些已选材料；不得添加未经证实的研究结果。先输出大纲和一页视觉样稿供确认，再生成完整汇报。\n"
                "图片模型与凭据需在运行 skill 的环境中配置；本压缩包不含密钥。\n"
                "引用保留在讲者备注中。原文配图在 figures/ 中，按 outline.json 的 image_file 放置；不得用生图重绘或改变实验曲线与数值。\n"
                "视觉要求：蓝白学术风，深蓝行动标题、留白、流程图、轻量对照表、原文图版；一页一个结论，不堆列表。\n\n"
                "上游：https://github.com/ningzimu/codex-ppt-skill\n",
            )
        return output.getvalue()
