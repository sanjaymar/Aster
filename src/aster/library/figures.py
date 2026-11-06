"""Original PDF visuals, pinned to a version and a source page.

Embedded figures are extracted unchanged. Vector-only pages are rendered as
whole pages and labelled as such; we never reconstruct experimental plots.
PDFium calls share one lock because its library is not thread safe.
"""

import io
import re
import threading

from pypdf import PdfReader
from sqlalchemy import select
from aster.domain.models import Asset, AppSetting, SourceVersion, SourceSpan
from aster.domain.common import Problem, required

LOCK = threading.RLock()
CAPTION = re.compile(
    r"(?im)^\s*((?:Figure|Fig\.?|图)\s*\d+[.：:]?[^\n]*(?:\n(?!\s*(?:Figure|Fig\.?|图)\s*\d)[^\n]+){0,5})"
)


def document(service, project_id, source_id, version_id=None):
    with service.db.session() as session:
        source = service.source(session, project_id, source_id)
        version = (
            session.get(SourceVersion, version_id)
            if version_id
            else session.scalar(
                select(SourceVersion)
                .where(SourceVersion.source_id == source_id)
                .order_by(SourceVersion.number.desc())
                .limit(1)
            )
        )
        if not version or version.source_id != source.id:
            raise Problem("论文版本不存在", 404)
        asset = required(session, Asset, version.asset_id)
        if asset.media_type != "application/pdf":
            raise Problem("此文献没有原始 PDF", 422)
        spans = list(
            session.scalars(
                select(SourceSpan)
                .where(SourceSpan.source_version_id == version.id)
                .order_by(SourceSpan.page)
            )
        )
        return (
            service.files / asset.storage_key,
            version.id,
            source.title,
            [{"id": s.id, "page": s.page, "text": s.text} for s in spans],
        )


def render(path, page, width=1200):
    import pypdfium2 as pdfium

    with LOCK:
        with pdfium.PdfDocument(str(path)) as pdf:
            if not 1 <= page <= len(pdf):
                raise Problem("页码超出范围", 422)
            sheet = pdf[page - 1]
            bitmap = sheet.render(scale=min(width / sheet.get_width(), 3))
            image = bitmap.to_pil().copy()
            bitmap.close()
            sheet.close()
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def thumbnail(service, project_id, source_id, version_id=None, page=1):
    path, version, _, spans = document(service, project_id, source_id, version_id)
    if page not in {s["page"] for s in spans}:
        raise Problem("页码不存在", 404)
    cache = service.db.data_dir / "cache/previews" / version / f"page-{page}.png"
    with LOCK:
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(render(path, page, 900))
    return cache


def extract(service, project_id, source_id, version_id=None):
    path, version, title, spans = document(service, project_id, source_id, version_id)
    key = f"aster:figures:{project_id}:{version}"
    with LOCK:
        with service.db.session() as session:
            cached = session.get(AppSetting, key)
            if cached:
                value = cached.value
                for figure in value["figures"]:
                    figure["url"] = f"/api/assets/{figure['asset_id']}?inline=true"
                return value
        pdf = PdfReader(path)
        figures, seen = [], set()
        for span in spans[:80]:
            captions = CAPTION.findall(span["text"])
            if not captions:
                continue
            page = pdf.pages[span["page"] - 1]
            pictures = []
            for embedded in page.images:
                image = embedded.image
                if image.width < 200 or image.height < 120 or image.width * image.height < 90000:
                    continue
                if not 0.2 < image.width / image.height < 7:
                    continue
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG")
                data = output.getvalue()
                # Repeated publisher logos / panels appear only once.
                import hashlib

                digest = hashlib.blake2b(data, digest_size=16).digest()
                if digest not in seen:
                    pictures.append((data, "figure"))
                    seen.add(digest)
            if not pictures:
                pictures = [(render(path, span["page"]), "page")]
            for data, kind in pictures[:4]:
                asset = service.add_asset(
                    project_id, f"{path.stem}-figure-{len(figures) + 1}.png", data, "image/png"
                )
                figures.append(
                    {
                        "id": asset["id"],
                        "asset_id": asset["id"],
                        "source_id": source_id,
                        "version_id": version,
                        "title": title,
                        "page": span["page"],
                        "caption": " ".join(captions)[:1000],
                        "kind": kind,
                        "label": f"{'原文配图' if kind == 'figure' else '原文整页'} · p.{span['page']}",
                        "citation": f"[[S:{span['id']}]]",
                        "url": f"/api/assets/{asset['id']}?inline=true",
                    }
                )
            if len(figures) >= 20:
                break
        result = {"source_id": source_id, "version_id": version, "figures": figures[:20]}
        with service.db.session() as session:
            session.merge(AppSetting(key=key, value=result))
        return result


def selected(service, project_id, source_versions, limit=16):
    values = []
    for source_id, version_id in pin(service, project_id, [v for _, v in source_versions[:4]]):
        try:
            values.extend(extract(service, project_id, source_id, version_id)["figures"])
        except Problem as error:
            if error.status != 422:
                raise
    return values[:limit]


def pin(service, project_id, version_ids):
    """Pair clean retrieval text with its recorded original PDF, never a later upload."""
    pairs = []
    with service.db.session() as session:
        for key in version_ids:
            version = required(session, SourceVersion, key)
            source = service.source(session, project_id, version.source_id)
            asset = required(session, Asset, version.asset_id)
            if asset.media_type != "application/pdf":
                provenance = source.provenance
                if provenance.get("retrieval_version_id") != version.id:
                    continue
                original = provenance.get("original_pdf", {}).get("source_version_id")
                version = session.get(SourceVersion, original) if original else None
                if not version or version.source_id != source.id:
                    continue
                asset = required(session, Asset, version.asset_id)
            if asset.media_type == "application/pdf":
                pairs.append((source.id, version.id))
    return list(dict.fromkeys(pairs))
