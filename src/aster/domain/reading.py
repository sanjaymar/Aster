"""Reading preferences, source-anchored annotations and linked personal notes."""

from sqlalchemy import select, or_
from aster.domain.models import (
    ReadingState,
    Annotation,
    SourceVersion,
    SourceSpan,
    SourceChunk,
    ArtifactVersion,
    Artifact,
    EvidenceLink,
    now,
)
from aster.domain.service import Problem, plain, required
from aster.domain.management import deleted_ids


class ReadingLibrary:
    def __init__(self, service):
        self.service, self.db = service, service.db

    def update(self, project_id, source_id, values):
        with self.db.session() as session:
            self.service.source(session, project_id, source_id)
            if values.get("last_version_id"):
                version = required(session, SourceVersion, values["last_version_id"])
                if version.source_id != source_id:
                    raise Problem("阅读位置不属于当前文献", 404)
            state = session.get(ReadingState, (project_id, source_id))
            if state is None:
                state = ReadingState(project_id=project_id, source_id=source_id)
                session.add(state)
            for key, value in values.items():
                setattr(state, key, value)
            state.updated_at = now()
            session.flush()
            return plain(state)

    def annotations(self, project_id, source_id, version_id=None):
        with self.db.session() as session:
            self.service.source(session, project_id, source_id)
            versions = select(SourceVersion.id).where(SourceVersion.source_id == source_id)
            if version_id:
                version = required(session, SourceVersion, version_id)
                if version.source_id != source_id:
                    raise Problem("版本不属于当前文献", 404)
                versions = versions.where(SourceVersion.id == version_id)
            rows = session.execute(
                select(Annotation, SourceSpan.page, SourceVersion.number)
                .join(SourceSpan, SourceSpan.id == Annotation.source_span_id)
                .join(SourceVersion, SourceVersion.id == Annotation.source_version_id)
                .where(
                    Annotation.project_id == project_id, Annotation.source_version_id.in_(versions)
                )
                .order_by(SourceSpan.page, Annotation.start_offset)
            )
            return [{**plain(row), "page": page, "version": version} for row, page, version in rows]

    def annotate(self, project_id, source_id, values):
        with self.db.session() as session:
            self.service.source(session, project_id, source_id)
            span = required(session, SourceSpan, values["source_span_id"])
            version = required(session, SourceVersion, span.source_version_id)
            if version.source_id != source_id:
                raise Problem("标注不属于当前文献", 404)
            start, end = values["start_offset"], values["end_offset"]
            if end <= start or end > len(span.text) or span.text[start:end] != values["quote"]:
                raise Problem("选中文本与原文位置不一致，请重新选择")
            row = Annotation(project_id=project_id, source_version_id=version.id, **values)
            session.add(row)
            session.flush()
            return {**plain(row), "page": span.page, "version": version.number}

    def edit_annotation(self, project_id, source_id, annotation_id, comment):
        with self.db.session() as session:
            self.service.source(session, project_id, source_id)
            row = required(session, Annotation, annotation_id)
            version = required(session, SourceVersion, row.source_version_id)
            if row.project_id != project_id or version.source_id != source_id:
                raise Problem("标注不属于当前文献", 404)
            row.comment = comment
            session.flush()
            return plain(row)

    def remove(self, project_id, source_id, annotation_id):
        with self.db.session() as session:
            self.service.source(session, project_id, source_id)
            row = required(session, Annotation, annotation_id)
            version = required(session, SourceVersion, row.source_version_id)
            if row.project_id != project_id or version.source_id != source_id:
                raise Problem("标注不属于当前文献", 404)
            session.delete(row)
        return {"deleted": True}

    def notes(self, project_id, source_id):
        with self.db.session() as session:
            self.service.source(session, project_id, source_id)
            versions = select(SourceVersion.id).where(SourceVersion.source_id == source_id)
            ids = (
                select(Artifact.id)
                .join(
                    ArtifactVersion,
                    (ArtifactVersion.artifact_id == Artifact.id)
                    & (ArtifactVersion.number == Artifact.revision),
                )
                .outerjoin(EvidenceLink, EvidenceLink.artifact_version_id == ArtifactVersion.id)
                .outerjoin(SourceSpan, SourceSpan.id == EvidenceLink.source_span_id)
                .outerjoin(SourceChunk, SourceChunk.id == EvidenceLink.source_chunk_id)
                .where(
                    Artifact.project_id == project_id,
                    ~Artifact.id.in_(deleted_ids("artifact", project_id)),
                    Artifact.kind == "note",
                    or_(
                        SourceSpan.source_version_id.in_(versions),
                        SourceChunk.source_version_id.in_(versions),
                        ArtifactVersion.fields["source_id"].as_string() == source_id,
                    ),
                )
            )
            return [
                self.service._artifact_dict(session, row)
                for row in session.scalars(
                    select(Artifact)
                    .where(Artifact.id.in_(ids))
                    .order_by(Artifact.updated_at.desc())
                )
            ]
