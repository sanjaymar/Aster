"""Transactional application services shared by HTTP and harness tools."""

import csv
import hashlib
import io
import math
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select, func

from aster.domain.models import (
    Asset,
    Source,
    ProjectSource,
    SourceVersion,
    SourceSpan,
    ReadingState,
    uid,
)


from aster.domain.common import Problem, plain, required
from aster.domain.management import deleted_ids


class Library:
    def _store_asset(self, session, project_id, name, data, media_type, maximum=25 * 1024 * 1024):
        if len(data) > maximum:
            raise Problem(f"文件不能超过 {maximum // (1024 * 1024)} MB", 413)
        digest = hashlib.sha256(data).hexdigest()
        from aster.storage.paths import filename

        storage_key = session.scalar(
            select(Asset.storage_key).where(Asset.sha256 == digest).limit(1)
        )
        if not storage_key:
            storage_key = filename(name)
            if (self.files / storage_key).exists():
                proposed = Path(storage_key)
                storage_key = f"{proposed.stem}-{uid()[:6]}{proposed.suffix}"
        path = self.files / storage_key
        if not path.exists():
            temporary = self.files / (uid() + ".tmp")
            try:
                temporary.write_bytes(data)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        asset = Asset(
            project_id=project_id,
            name=Path(name).name[:255] or "attachment",
            media_type=media_type,
            sha256=digest,
            size=len(data),
            storage_key=storage_key,
        )
        session.add(asset)
        session.flush()
        return asset

    def add_asset(self, project_id, name, data, media_type):
        with self.db.session() as s:
            self.project(s, project_id)
            return plain(self._store_asset(s, project_id, name, data, media_type))

    def import_source(
        self, project_id, name, data, title="", authors="", year="", doi="", source_id=None
    ):
        if not data:
            raise Problem("文件为空")
        if len(data) > 200 * 1024 * 1024:
            raise Problem("资料不能超过 200 MB", 413)
        is_pdf = data.startswith(b"%PDF-")
        if is_pdf:
            try:
                reader = PdfReader(io.BytesIO(data))
                if reader.is_encrypted and not reader.decrypt(""):
                    raise Problem("请先解密 PDF 后再导入")
                if len(reader.pages) > 1000:
                    raise Problem("PDF 页数不能超过 1000 页")
                pages = []
                extraction_errors = []
                total = 0
                for page in reader.pages:
                    try:
                        text = page.extract_text() or ""
                        extraction_errors.append("")
                    except Exception as error:
                        text = ""
                        extraction_errors.append(type(error).__name__)
                    total += len(text)
                    if total > 5_000_000:
                        raise Problem("文档文本过长，请拆分后导入")
                    pages.append(text)
                metadata = reader.metadata or {}
                title = title or str(metadata.get("/Title") or "")
                authors = authors or str(metadata.get("/Author") or "")
            except Problem:
                raise
            except Exception as e:
                raise Problem("无法解析 PDF，请检查文件是否损坏") from e
        else:
            if Path(name).suffix.lower() not in {".txt", ".md", ".csv"}:
                raise Problem("支持 PDF、TXT、Markdown 和 CSV 资料")
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError as e:
                raise Problem("文本文件需要使用 UTF-8 编码") from e
            if len(text) > 5_000_000:
                raise Problem("文档文本过长，请拆分后导入")
            pages = [text[i : i + 8000] for i in range(0, len(text), 8000)] or [""]
        title = (title.strip() or Path(name).stem)[:500]
        with self.db.session() as s:
            self.project(s, project_id)
            if source_id:
                source = self.source(s, project_id, source_id)
                source.provenance = {
                    key: value
                    for key, value in source.provenance.items()
                    if key != "retrieval_version_id"
                }
            else:
                source = Source(
                    workspace_id="personal", title=title, authors=authors, year=year, doi=doi
                )
                s.add(source)
                s.flush()
                s.add(ProjectSource(project_id=project_id, source_id=source.id))
            asset = self._store_asset(
                s,
                project_id,
                name,
                data,
                "application/pdf" if is_pdf else "text/plain; charset=utf-8",
                maximum=200 * 1024 * 1024,
            )
            number = (
                s.scalar(
                    select(func.max(SourceVersion.number)).where(
                        SourceVersion.source_id == source.id
                    )
                )
                or 0
            ) + 1
            version = SourceVersion(source_id=source.id, asset_id=asset.id, number=number)
            s.add(version)
            s.flush()
            for i, text in enumerate(pages, 1):
                s.add(
                    SourceSpan(
                        source_version_id=version.id,
                        page=i,
                        text=text,
                        extraction_error=extraction_errors[i - 1] if is_pdf else "",
                    )
                )
            s.flush()
            return {
                **plain(source),
                "version_id": version.id,
                "version": number,
                "page_count": len(pages),
                "text_available": any(p.strip() for p in pages),
            }

    def sources(self, project_id):
        with self.db.session() as s:
            self.project(s, project_id)
            latest = (
                select(SourceVersion.source_id, func.max(SourceVersion.number).label("number"))
                .group_by(SourceVersion.source_id)
                .subquery()
            )
            pages = (
                select(SourceSpan.source_version_id, func.count().label("count"))
                .group_by(SourceSpan.source_version_id)
                .subquery()
            )
            rows = s.execute(
                select(Source, SourceVersion, pages.c.count, ReadingState, Asset.media_type)
                .join(ProjectSource, ProjectSource.source_id == Source.id)
                .join(latest, latest.c.source_id == Source.id)
                .join(
                    SourceVersion,
                    (SourceVersion.source_id == Source.id)
                    & (SourceVersion.number == latest.c.number),
                )
                .join(Asset, Asset.id == SourceVersion.asset_id)
                .outerjoin(pages, pages.c.source_version_id == SourceVersion.id)
                .outerjoin(
                    ReadingState,
                    (ReadingState.source_id == Source.id) & (ReadingState.project_id == project_id),
                )
                .where(
                    ProjectSource.project_id == project_id,
                    ~ProjectSource.source_id.in_(deleted_ids("source", project_id)),
                )
                .order_by(Source.created_at.desc())
            )
            return [
                {
                    **plain(source),
                    **source.provenance,
                    "version_id": version.id,
                    "version": version.number,
                    "asset_id": version.asset_id,
                    "page_count": count or 0,
                    "content_type": media_type,
                    "reading": plain(reading)
                    if reading
                    else {"reading_status": "unread", "starred": False, "tags": [], "last_page": 1},
                }
                for source, version, count, reading, media_type in rows
            ]

    def source_pages(self, project_id, source_id, version_id=None):
        with self.db.session() as s:
            self.source(s, project_id, source_id)
            versions = list(
                s.scalars(
                    select(SourceVersion)
                    .where(SourceVersion.source_id == source_id)
                    .order_by(SourceVersion.number.desc())
                )
            )
            version = (
                next((v for v in versions if v.id == version_id), None)
                if version_id
                else versions[0]
            )
            if not version:
                raise Problem("文献版本不存在", 404)
            assets = {
                asset.id: asset
                for asset in s.scalars(
                    select(Asset).where(Asset.id.in_([v.asset_id for v in versions]))
                )
            }
            return {
                "versions": [
                    {**plain(v), "content_type": assets[v.asset_id].media_type} for v in versions
                ],
                "version": plain(version),
                "content_type": required(s, Asset, version.asset_id).media_type,
                "pages": [
                    plain(p)
                    for p in s.scalars(
                        select(SourceSpan)
                        .where(SourceSpan.source_version_id == version.id)
                        .order_by(SourceSpan.page)
                    )
                ],
            }

    def csv_preview(self, project_id, asset_id):
        with self.db.session() as s:
            self.project(s, project_id)
            a = required(s, Asset, asset_id)
            if a.project_id != project_id:
                raise Problem("附件不属于当前项目", 404)
            try:
                reader = csv.DictReader(
                    io.StringIO((self.files / a.storage_key).read_text(encoding="utf-8-sig"))
                )
                columns = reader.fieldnames or []
                rows = []
                for i, row in enumerate(reader):
                    if i >= 1000:
                        break
                    rows.append(row)
                numeric = {}
                for col in columns:
                    values = []
                    for row in rows:
                        try:
                            value = float(row.get(col, ""))
                            if math.isfinite(value):
                                values.append(value)
                        except (TypeError, ValueError):
                            pass
                    if values:
                        numeric[col] = {
                            "count": len(values),
                            "min": min(values),
                            "max": max(values),
                            "mean": sum(values) / len(values),
                        }
                return {
                    "columns": columns,
                    "rows": rows[:100],
                    "analyzed_rows": len(rows),
                    "limit": 1000,
                    "numeric": numeric,
                }
            except (UnicodeError, csv.Error) as e:
                raise Problem("无法读取 CSV，请使用 UTF-8 编码的标准 CSV 文件") from e
