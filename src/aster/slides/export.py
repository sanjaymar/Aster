"""Editable scientific layouts: source figures, tables, method flows and summaries."""

from io import BytesIO
import math
from PIL import Image
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml.xmlchemy import OxmlElement
from aster.domain.models import Asset
from aster.domain.common import CITATION


def pptx(deck, sources, service, project_id):
    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = Inches(13.333), Inches(7.5)
    presentation.core_properties.title, presentation.core_properties.author = deck.title, "Aster"
    dark = deck.theme == "ink"
    bg, ink, muted = ("181D27", "F4F6FA", "A6B0C2") if dark else ("FFFFFF", "23334C", "7B8798")
    accent = "86A9E4" if dark else ("183E77" if deck.theme == "academic" else "283646")
    soft, line = ("242E3F", "3A465A") if dark else ("EDF3FA", "D7E2F0")

    def rect(slide, x, y, w, h, fill, stroke=None, shape=MSO_SHAPE.RECTANGLE):
        r = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
        r.fill.solid()
        r.fill.fore_color.rgb = RGBColor.from_string(fill)
        r._element.spPr.append(OxmlElement("a:effectLst"))
        for effect in r._element.xpath("./p:style/a:effectRef"):
            effect.set("idx", "0")
        if stroke:
            r.line.color.rgb = RGBColor.from_string(stroke)
            r.line.width = Pt(0.7)
        else:
            r.line.fill.background()
        return r

    def text(slide, value, x, y, w, h, size=18, color=ink, bold=False):
        value = CITATION.sub("", value).strip()
        shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = shape.text_frame
        frame.word_wrap = True
        frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
        frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        weight = sum(1 if ord(c) > 255 else 0.52 for c in value)
        capacity = max(1, (w * 72 / size) * (h * 72 / (size * 1.45)))
        size = max(min(11, size), min(size, size * math.sqrt(capacity / max(weight, capacity))))
        for index, line_text in enumerate(value.split("\n")):
            p = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            p.text = line_text
            p.font.name = "Noto Sans CJK SC"
            p.font.size = Pt(size)
            p.font.bold = bold
            p.font.color.rgb = RGBColor.from_string(color)
            p.space_after = Pt(9)
            p.line_spacing = 1.22
        return shape

    def picture(slide, asset_id, x, y, w, h):
        with service.db.session() as session:
            asset = session.get(Asset, asset_id)
            path = service.files / asset.storage_key
        with Image.open(path) as original:
            image = original.convert("RGBA")
            ratio = image.width / image.height
            output = BytesIO()
            image.save(output, format="PNG")
            output.seek(0)
        iw = min(w, h * ratio)
        ih = iw / ratio
        slide.shapes.add_picture(
            output,
            Inches(x + (w - iw) / 2),
            Inches(y + (h - ih) / 2),
            width=Inches(iw),
            height=Inches(ih),
        )

    def table(slide, item, x, y, w, h):
        headers = item.table.headers
        rows = item.table.rows
        if not headers:
            return
        cell_h = h / (len(rows) + 1)
        for rowno, row in enumerate([headers, *rows]):
            for col, value in enumerate(row):
                cx = x + col * w / len(headers)
                cy = y + rowno * cell_h
                rect(
                    slide,
                    cx,
                    cy,
                    w / len(headers),
                    cell_h,
                    accent if rowno == 0 else (soft if rowno % 2 else bg),
                    line,
                )
                text(
                    slide,
                    value,
                    cx + 0.16,
                    cy + 0.13,
                    w / len(headers) - 0.32,
                    cell_h - 0.2,
                    16,
                    "FFFFFF" if rowno == 0 and not dark else ink,
                    rowno == 0,
                )

    for number, item in enumerate(deck.slides, 1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(bg)
        rect(slide, 0.65, 0.48, 0.48, 0.045, accent)
        text(slide, item.title, 0.65, 0.77, 12, 1.0, 31, accent, True)
        if item.subtitle:
            text(slide, item.subtitle, 0.67, 1.8, 11.9, 0.45, 15, muted)
        layout = item.layout
        if layout == "cover":
            rect(slide, 0.65, 2.55, 0.045, 2.9, accent)
            text(slide, deck.title, 0.95, 2.55, 8.1, 1.75, 34, accent, True)
            text(slide, "\n".join(item.bullets), 0.98, 4.55, 8.1, 1.1, 17, muted)
            rect(slide, 10, 2.7, 2.55, 2.65, soft)
            text(slide, "RESEARCH\nBRIEFING", 10.25, 3.2, 2.1, 1.1, 21, accent, True)
        elif layout == "flow" and item.steps:
            alone = not (item.image_asset_id or item.table.headers or item.bullets)
            left = 2.8 if alone else 0.7
            width = 7.7 if alone else 4.0 if item.image_asset_id or item.table.headers else 5.7
            step_h = min(0.76, (3.6 - 0.10 * (len(item.steps) - 1)) / len(item.steps))
            for i, step in enumerate(item.steps):
                y = 2.55 + i * (step_h + 0.10)
                rect(slide, left, y, width, step_h, soft, line)
                text(slide, f"{i + 1:02}", left + 0.16, y + 0.12, 0.5, 0.3, 18, accent, True)
                text(slide, step.label, left + 0.74, y + 0.06, width - 0.9, 0.26, 16, accent, True)
                if step.detail:
                    limit = int((width - 0.9) * 5)
                    detail = (
                        step.detail if len(step.detail) <= limit else step.detail[: limit - 1] + "…"
                    )
                    text(
                        slide, detail, left + 0.74, y + 0.33, width - 0.9, step_h - 0.34, 10, muted
                    )
                if i < len(item.steps) - 1:
                    rect(
                        slide,
                        left + width / 2 - 0.035,
                        y + step_h + 0.025,
                        0.07,
                        0.07,
                        accent,
                        shape=MSO_SHAPE.DOWN_ARROW,
                    )
            x = 0.7 + width + 0.45
            w = 12 - x
            if item.table.headers:
                table(slide, item, x, 2.55, w, 2.05)
            if item.image_asset_id:
                picture(
                    slide,
                    item.image_asset_id,
                    x,
                    4.75 if item.table.headers else 2.55,
                    w,
                    1.5 if item.table.headers else 3.6,
                )
            elif not item.table.headers and item.bullets:
                text(slide, "\n".join("• " + b for b in item.bullets), x, 2.65, w, 3.5, 20)
        elif layout == "table" and item.table.headers:
            table(slide, item, 0.7, 2.55, 11.9, 2.8)
            if item.bullets:
                text(
                    slide,
                    "\n".join("• " + b for b in item.bullets[:2]),
                    0.8,
                    5.55,
                    11.6,
                    0.7,
                    15,
                    muted,
                )
        elif item.image_asset_id:
            if item.bullets:
                text(slide, "\n".join("• " + b for b in item.bullets), 0.7, 2.6, 3.45, 3.25, 17)
            x, width = (4.65, 7.9) if item.bullets else (0.7, 11.9)
            picture(slide, item.image_asset_id, x, 2.35, width, 3.7)
            if item.image_caption:
                text(slide, item.image_caption, x, 6.08, width, 0.32, 9, muted)
        elif layout == "comparison":
            for col in range(2):
                x = 0.7 + col * 6.05
                rect(slide, x, 2.55, 5.7, 3.55, soft)
                values = item.bullets[col::2]
                text(slide, "\n".join("• " + b for b in values), x + 0.3, 2.92, 5.1, 2.85, 21)
        elif layout == "closing":
            rect(slide, 0.7, 2.55, 11.9, 1.2, soft)
            text(
                slide,
                item.takeaway or (item.bullets[0] if item.bullets else item.title),
                1.0,
                2.83,
                11.2,
                0.75,
                23,
                accent,
                True,
            )
            text(
                slide,
                "\n".join(f"{i + 1:02}   {b}" for i, b in enumerate(item.bullets)),
                0.85,
                4.15,
                11.5,
                2.0,
                20,
            )
        else:
            for i, b in enumerate(item.bullets):
                y = 2.55 + i * 0.84
                rect(slide, 0.75, y + 0.09, 0.08, 0.08, accent)
                text(slide, b, 1.0, y, 11.3, 0.72, 21)
        if item.takeaway and layout not in {"cover", "closing"}:
            rect(slide, 0.7, 6.45, 11.9, 0.42, soft)
            text(slide, item.takeaway, 0.87, 6.53, 11.5, 0.25, 12, accent, True)
        rect(slide, 0.7, 7.02, 11.9, 0.012, line)
        refs = [
            f"[{i + 1}] {sources[ref].get('title', '')} · p.{sources[ref].get('page', '—')} {ref}"
            for i, ref in enumerate(item.citations)
        ]
        footer = " / ".join(CITATION.sub("", r) for r in refs)
        text(slide, (footer or deck.title)[:180], 0.7, 7.12, 11.2, 0.23, 8, muted)
        text(slide, f"{number:02}", 12.08, 7.10, 0.5, 0.25, 10, accent)
        steps = "\n".join(step.label + "：" + step.detail for step in item.steps)
        slide.notes_slide.notes_text_frame.text = (
            item.notes + ("\n\n方法步骤：\n" + steps if steps else "") + "\n\n" + "\n".join(refs)
        )
    output = BytesIO()
    presentation.save(output)
    return output.getvalue()
