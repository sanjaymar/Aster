"""Transactional application services shared by HTTP and harness tools."""

import csv
import hashlib
import io
import math
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select, func, update

from aster.domain.extensions import EXTENSIONS
from aster.domain.models import (
    Project,
    Asset,
    Source,
    ProjectSource,
    SourceVersion,
    SourceSpan,
    Artifact,
    ArtifactVersion,
    EvidenceLink,
    ArtifactAsset,
    Experiment,
    ExperimentRun,
    SourceChunk,
    ReadingState,
    now,
    uid,
)


from aster.domain.common import CITATION, Problem, plain, required
from aster.domain.management import deleted_ids, is_deleted


class Service:
    def __init__(self, db):
        self.db = db
        self.files = db.data_dir / "files"
        self.files.mkdir(exist_ok=True)

    def project(self, session, project_id):
        project = required(session, Project, project_id)
        if project.workspace_id != "personal":
            raise Problem("没有访问此项目的权限", 403)
        if is_deleted(session, project_id, "project", project_id):
            raise Problem("项目已移到回收站", 404)
        return project

    def source(self, session, project_id, source_id, include_deleted=False):
        self.project(session, project_id)
        if not session.get(ProjectSource, (project_id, source_id)):
            raise Problem("资料不属于当前项目", 404)
        if not include_deleted and is_deleted(session, project_id, "source", source_id):
            raise Problem("资料已移到回收站", 404)
        return required(session, Source, source_id)

    def artifact(self, session, project_id, artifact_id, include_deleted=False):
        self.project(session, project_id)
        record = required(session, Artifact, artifact_id)
        if record.project_id != project_id:
            raise Problem("记录不属于当前项目", 404)
        if not include_deleted and is_deleted(session, project_id, "artifact", artifact_id):
            raise Problem("记录已移到回收站", 404)
        return record

    def projects(self):
        with self.db.session() as s:
            return [
                plain(p)
                for p in s.scalars(
                    select(Project)
                    .where(
                        Project.workspace_id == "personal", ~Project.id.in_(deleted_ids("project"))
                    )
                    .order_by(Project.updated_at.desc())
                )
            ]

    def save_project(
        self, title, description="", domain="research", project_id=None, knowledge=None
    ):
        if domain not in EXTENSIONS:
            raise Problem("不支持的领域扩展")
        with self.db.session() as s:
            if project_id:
                p = self.project(s, project_id)
                if domain != p.domain:
                    raise Problem("已有项目的领域不能直接更换，请创建新项目")
                p.title, p.description, p.updated_at = title, description, now()
            else:
                p = Project(
                    workspace_id="personal", title=title, description=description, domain=domain
                )
                s.add(p)
            if knowledge is not None:
                p.knowledge = knowledge
            s.flush()
            return plain(p)

    def overview(self, project_id):
        with self.db.session() as s:
            p = self.project(s, project_id)
            counts = dict(
                s.execute(
                    select(Artifact.kind, func.count())
                    .where(
                        Artifact.project_id == project_id,
                        ~Artifact.id.in_(deleted_ids("artifact", project_id)),
                    )
                    .group_by(Artifact.kind)
                ).all()
            )
            sources = s.scalar(
                select(func.count())
                .select_from(ProjectSource)
                .where(
                    ProjectSource.project_id == project_id,
                    ~ProjectSource.source_id.in_(deleted_ids("source", project_id)),
                )
            )
            experiments = s.scalar(
                select(func.count())
                .select_from(Experiment)
                .where(
                    Experiment.project_id == project_id,
                    ~Experiment.id.in_(deleted_ids("experiment", project_id)),
                )
            )
            recent = s.scalars(
                select(Artifact)
                .where(
                    Artifact.project_id == project_id,
                    ~Artifact.id.in_(deleted_ids("artifact", project_id)),
                )
                .order_by(Artifact.updated_at.desc())
                .limit(8)
            )
            return {
                "project": plain(p),
                "counts": {**counts, "sources": sources, "experiments": experiments},
                "recent": [self._artifact_dict(s, a) for a in recent],
            }

    def _store_asset(self, session, project_id, name, data, media_type, maximum=25 * 1024 * 1024):
        if len(data) > maximum:
            raise Problem(f"文件不能超过 {maximum // (1024 * 1024)} MB", 413)
        digest = hashlib.sha256(data).hexdigest()
        path = self.files / digest
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
            storage_key=digest,
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

    def _artifact_dict(self, s, artifact):
        version = s.scalar(
            select(ArtifactVersion)
            .where(ArtifactVersion.artifact_id == artifact.id)
            .order_by(ArtifactVersion.number.desc())
        )
        data = {**plain(artifact), "version": plain(version) if version else None}
        if version:
            data["attachments"] = [
                plain(a)
                for a in s.scalars(
                    select(Asset)
                    .join(ArtifactAsset)
                    .where(ArtifactAsset.artifact_version_id == version.id)
                )
            ]
        return data

    def artifacts(self, project_id, kind=None):
        with self.db.session() as s:
            self.project(s, project_id)
            stmt = select(Artifact).where(
                Artifact.project_id == project_id,
                ~Artifact.id.in_(deleted_ids("artifact", project_id)),
            )
            if kind:
                stmt = stmt.where(Artifact.kind == kind)
            return [
                self._artifact_dict(s, a)
                for a in s.scalars(stmt.order_by(Artifact.updated_at.desc()))
            ]

    def artifact_history(self, project_id, artifact_id):
        with self.db.session() as s:
            a = self.artifact(s, project_id, artifact_id)
            return {
                **self._artifact_dict(s, a),
                "versions": [
                    plain(v)
                    for v in s.scalars(
                        select(ArtifactVersion)
                        .where(ArtifactVersion.artifact_id == a.id)
                        .order_by(ArtifactVersion.number.desc())
                    )
                ],
            }

    def evidence(self, session, project_id, kind, key):
        if kind == "C":
            chunk = required(session, SourceChunk, key)
            version = required(session, SourceVersion, chunk.source_version_id)
            source = self.source(session, project_id, version.source_id, include_deleted=True)
            return {
                "kind": kind,
                "id": key,
                "title": source.title,
                "page": chunk.page_start,
                "page_end": chunk.page_end,
                "section": chunk.section,
                "version": version.number,
                "content": chunk.text,
                "asset_id": version.asset_id,
                "source_id": source.id,
                "source_span_id": chunk.source_span_id,
                "content_type": required(session, Asset, version.asset_id).media_type,
            }
        if kind == "S":
            span = required(session, SourceSpan, key)
            version = required(session, SourceVersion, span.source_version_id)
            source = self.source(session, project_id, version.source_id, include_deleted=True)
            return {
                "kind": kind,
                "id": key,
                "title": source.title,
                "page": span.page,
                "version": version.number,
                "content": span.text,
                "content_type": required(session, Asset, version.asset_id).media_type,
                "asset_id": version.asset_id,
                "source_id": source.id,
            }
        version = required(session, ArtifactVersion, key)
        artifact = self.artifact(session, project_id, version.artifact_id, include_deleted=True)
        return {
            "kind": kind,
            "id": key,
            "title": artifact.title,
            "version": version.number,
            "content": version.content,
            "fields": version.fields,
            "artifact_id": artifact.id,
        }

    def _save_record(
        self,
        s,
        project_id,
        title,
        kind,
        content,
        fields=None,
        artifact_id=None,
        expected_revision=None,
        author="human",
        status="draft",
        asset_ids=(),
    ):
        p = self.project(s, project_id)
        if kind not in EXTENSIONS[p.domain].artifact_kinds:
            raise Problem("当前领域不支持此记录类型")
        if artifact_id:
            a = self.artifact(s, project_id, artifact_id)
            if a.kind != kind:
                raise Problem("不能更改记录类型")
            if expected_revision is None:
                raise Problem("更新需要提供版本号", 409)
            changed = s.execute(
                update(Artifact)
                .where(Artifact.id == a.id, Artifact.revision == expected_revision)
                .values(
                    revision=Artifact.revision + 1, title=title, status=status, updated_at=now()
                )
            )
            if changed.rowcount != 1:
                raise Problem("内容已被更新，请重新加载后再保存", 409)
            s.refresh(a)
        else:
            a = Artifact(project_id=project_id, kind=kind, title=title, status=status, revision=1)
            s.add(a)
            s.flush()
        if (fields or {}).get("source_id"):
            self.source(s, project_id, str(fields["source_id"]), include_deleted=True)
        for linked_id in (fields or {}).get("related_record_ids", []):
            self.artifact(s, project_id, linked_id, include_deleted=True)
        evidence = set(CITATION.findall(content))
        for typ, key in evidence:
            self.evidence(s, project_id, typ, key)
        v = ArtifactVersion(
            artifact_id=a.id, number=a.revision, content=content, fields=fields or {}, author=author
        )
        s.add(v)
        s.flush()
        for typ, key in evidence:
            s.add(
                EvidenceLink(
                    artifact_version_id=v.id,
                    source_span_id=key if typ == "S" else None,
                    target_version_id=key if typ == "V" else None,
                    source_chunk_id=key if typ == "C" else None,
                )
            )
        for key in set(asset_ids):
            asset = required(s, Asset, key)
            if asset.project_id != project_id:
                raise Problem("附件不属于当前项目", 404)
            s.add(ArtifactAsset(artifact_version_id=v.id, asset_id=key))
        p.updated_at = now()
        s.flush()
        return self._artifact_dict(s, a)

    def save_record(self, project_id, **kwargs):
        with self.db.session() as s:
            return self._save_record(s, project_id, **kwargs)

    def experiments(self, project_id):
        with self.db.session() as s:
            self.project(s, project_id)
            items = []
            for exp in s.scalars(
                select(Experiment)
                .where(
                    Experiment.project_id == project_id,
                    ~Experiment.id.in_(deleted_ids("experiment", project_id)),
                )
                .order_by(Experiment.created_at.desc())
            ):
                plan = self._artifact_dict(s, required(s, Artifact, exp.plan_artifact_id))
                runs = []
                for run in s.scalars(
                    select(ExperimentRun)
                    .where(ExperimentRun.experiment_id == exp.id)
                    .order_by(ExperimentRun.created_at.desc())
                ):
                    if is_deleted(s, project_id, "artifact", run.result_artifact_id):
                        continue
                    runs.append(
                        {
                            **plain(run),
                            "plan_version": required(
                                s, ArtifactVersion, run.plan_version_id
                            ).number,
                            "result": self._artifact_dict(
                                s, required(s, Artifact, run.result_artifact_id)
                            ),
                        }
                    )
                items.append({**plain(exp), "plan": plan, "runs": runs})
            return items

    def save_experiment(
        self,
        project_id,
        title,
        content,
        fields,
        experiment_id=None,
        expected_revision=None,
        author="human",
        asset_ids=(),
    ):
        with self.db.session() as s:
            p = self.project(s, project_id)
            if not EXTENSIONS[p.domain].experiments:
                raise Problem("此项目没有启用科研扩展")
            exp = required(s, Experiment, experiment_id) if experiment_id else None
            if exp and exp.project_id != project_id:
                raise Problem("实验不属于当前项目", 404)
            if exp and is_deleted(s, project_id, "experiment", exp.id):
                raise Problem("方案已移到回收站", 404)
            plan = self._save_record(
                s,
                project_id,
                title,
                "plan",
                content,
                fields,
                exp.plan_artifact_id if exp else None,
                expected_revision,
                author=author,
                asset_ids=asset_ids,
            )
            if exp:
                exp.title = title
            else:
                exp = Experiment(project_id=project_id, title=title, plan_artifact_id=plan["id"])
                s.add(exp)
            s.flush()
            return {**plain(exp), "plan": plan}

    def record_result(
        self,
        project_id,
        experiment_id,
        plan_version_id,
        title,
        content,
        conditions="",
        fields=None,
        asset_ids=(),
    ):
        with self.db.session() as s:
            self.project(s, project_id)
            exp = required(s, Experiment, experiment_id)
            plan = required(s, ArtifactVersion, plan_version_id)
            if exp.project_id != project_id or plan.artifact_id != exp.plan_artifact_id:
                raise Problem("实验或方案版本不属于当前项目", 404)
            if is_deleted(s, project_id, "experiment", exp.id):
                raise Problem("方案已移到回收站", 404)
            result = self._save_record(
                s,
                project_id,
                title,
                "result",
                content,
                {**(fields or {}), "plan_version_id": plan.id, "conditions": conditions},
                asset_ids=asset_ids,
            )
            run = ExperimentRun(
                experiment_id=exp.id,
                plan_version_id=plan.id,
                result_artifact_id=result["id"],
                conditions=conditions,
            )
            s.add(run)
            s.flush()
            return {**plain(run), "result": result}

    def edit_result(
        self,
        project_id,
        experiment_id,
        result_id,
        *,
        expected_revision,
        plan_version_id,
        title,
        content,
        conditions="",
        fields=None,
        asset_ids=(),
    ):
        with self.db.session() as s:
            self.project(s, project_id)
            exp = required(s, Experiment, experiment_id)
            run = required(s, ExperimentRun, result_id)
            plan = required(s, ArtifactVersion, plan_version_id)
            if (
                exp.project_id != project_id
                or run.experiment_id != exp.id
                or plan.artifact_id != exp.plan_artifact_id
            ):
                raise Problem("结果或方案版本不属于当前项目", 404)
            if is_deleted(s, project_id, "experiment", exp.id):
                raise Problem("方案已移到回收站", 404)
            result = self._save_record(
                s,
                project_id,
                title,
                "result",
                content,
                {**(fields or {}), "plan_version_id": plan.id, "conditions": conditions},
                artifact_id=run.result_artifact_id,
                expected_revision=expected_revision,
                asset_ids=asset_ids,
            )
            run.plan_version_id, run.conditions = plan.id, conditions
            return {**plain(run), "result": result}

    def search(self, project_id, query, allowed=None):
        with self.db.session() as s:
            self.project(s, project_id)
            term = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            spans = s.execute(
                select(SourceSpan, Source.title)
                .join(SourceVersion, SourceVersion.id == SourceSpan.source_version_id)
                .join(Source, Source.id == SourceVersion.source_id)
                .join(ProjectSource)
                .where(
                    ProjectSource.project_id == project_id,
                    SourceSpan.text.ilike(term, escape="\\"),
                    ~Source.id.in_(deleted_ids("source", project_id)),
                )
                .where(
                    SourceSpan.id.in_([key for typ, key in allowed if typ == "S"])
                    if allowed is not None
                    else True
                )
                .limit(30)
            )
            records = s.execute(
                select(ArtifactVersion, Artifact.title)
                .join(Artifact)
                .where(
                    Artifact.project_id == project_id,
                    ~Artifact.id.in_(deleted_ids("artifact", project_id)),
                    ArtifactVersion.id.in_([key for typ, key in allowed if typ == "V"])
                    if allowed is not None
                    else ArtifactVersion.number == Artifact.revision,
                    (
                        ArtifactVersion.content.ilike(term, escape="\\")
                        | Artifact.title.ilike(term, escape="\\")
                    ),
                )
                .limit(30)
            )
            out = []
            for span, title in spans:
                pos = max(0, span.text.lower().find(query.lower()) - 80)
                out.append(
                    {
                        "kind": "S",
                        "id": span.id,
                        "title": title,
                        "page": span.page,
                        "excerpt": span.text[pos : pos + 350],
                        "citation": f"[[S:{span.id}]]",
                    }
                )
            for version, title in records:
                pos = max(0, version.content.lower().find(query.lower()) - 80)
                out.append(
                    {
                        "kind": "V",
                        "id": version.id,
                        "title": title,
                        "excerpt": version.content[pos : pos + 350],
                        "citation": f"[[V:{version.id}]]",
                    }
                )
            return out

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

    def export(self, project_id, target=None):
        from aster.storage.archive import ProjectArchive

        return ProjectArchive(self).export(project_id, target)

    def restore(self, data):
        from aster.storage.archive import ProjectArchive

        return ProjectArchive(self).restore(data)
