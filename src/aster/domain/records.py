"""Transactional application services shared by HTTP and harness tools."""

from sqlalchemy import select, update

from aster.domain.extensions import EXTENSIONS
from aster.domain.models import (
    Asset,
    Source,
    ProjectSource,
    SourceVersion,
    SourceSpan,
    Artifact,
    ArtifactVersion,
    EvidenceLink,
    ArtifactAsset,
    SourceChunk,
    now,
)


from aster.domain.common import CITATION, Problem, plain, required
from aster.domain.management import deleted_ids


class Records:
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
        for source_id in (fields or {}).get("source_ids", []):
            self.source(s, project_id, source_id, include_deleted=True)
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
