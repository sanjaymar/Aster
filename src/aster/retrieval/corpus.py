"""Immutable, page-anchored paragraph/window chunks and scoped evidence selection."""

import hashlib
import re
from dataclasses import dataclass, asdict
from uuid import uuid5, NAMESPACE_URL

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from aster.domain.models import (
    Source,
    SourceVersion,
    SourceSpan,
    SourceChunk,
    ProjectSource,
    Artifact,
    ArtifactVersion,
)
from aster.domain.service import Problem
from aster.domain.management import deleted_ids

CHUNKER = "paragraph-window-v1-1400-200"
HEADING = re.compile(
    r"(?im)^\s*(?:#{1,6}\s+[^\n]{1,150}|(?:\d+(?:\.\d+)*[.)]?\s+)?(?:abstract|introduction|background|related work|methods?|methodology|experiments?|results?|discussion|conclusions?|limitations?|references|摘要|引言|方法|实验|结果|讨论|结论|局限)(?:\s*[:：].{0,100})?)\s*$"
)


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    title: str
    text: str
    source_id: str
    version_id: str
    version: int
    page: int = 0
    section: str = ""
    authority: str = "source"

    @property
    def citation(self):
        return f"[[{self.kind}:{self.id}]]"

    def public(self, include_text=True):
        value = asdict(self)
        value["citation"] = self.citation
        if not include_text:
            value.pop("text")
        return value


def windows(text, maximum=1400, overlap=200):
    """Return exact character offsets; never normalize text after anchoring."""
    paragraphs = list(re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text))
    start, end = None, None
    ranges = []
    for paragraph in paragraphs:
        a, b = paragraph.span()
        if start is not None and b - start > maximum:
            ranges.append((start, end))
            start, end = None, None
        if b - a > maximum:
            if start is not None:
                ranges.append((start, end))
                start, end = None, None
            pos = a
            while pos < b:
                stop = min(pos + maximum, b)
                ranges.append((pos, stop))
                if stop == b:
                    break
                pos = stop - overlap
        elif start is None:
            start, end = a, b
        else:
            end = b
    if start is not None:
        ranges.append((start, end))
    return ranges


class Corpus:
    def __init__(self, service):
        self.service, self.db = service, service.db

    def snapshot(
        self, project_id, source_ids=(), artifact_ids=(), scope="selected", source_version_ids=()
    ):
        with self.db.session() as s:
            self.service.project(s, project_id)
            if scope == "project":
                source_ids = list(
                    s.scalars(
                        select(ProjectSource.source_id).where(
                            ProjectSource.project_id == project_id,
                            ~ProjectSource.source_id.in_(deleted_ids("source", project_id)),
                        )
                    )
                )
                artifact_ids = list(
                    s.scalars(
                        select(Artifact.id).where(
                            Artifact.project_id == project_id,
                            ~Artifact.id.in_(deleted_ids("artifact", project_id)),
                        )
                    )
                )
            pinned = {}
            if source_version_ids and scope != "selected":
                raise Problem("固定原文版本仅用于选定材料")
            for version_id in source_version_ids:
                version = s.get(SourceVersion, version_id)
                if not version or version.source_id not in source_ids:
                    raise Problem("原文版本不属于选定材料", 404)
                if version.source_id in pinned:
                    raise Problem("同一文献只能指定一个版本")
                self.service.source(s, project_id, version.source_id)
                pinned[version.source_id] = version
            source_versions, artifact_versions = [], []
            for key in dict.fromkeys(source_ids):
                source = self.service.source(s, project_id, key)
                preferred_id = source.provenance.get("retrieval_version_id")
                preferred = s.get(SourceVersion, preferred_id) if preferred_id else None
                if preferred and preferred.source_id != key:
                    raise Problem("检索文本版本不属于当前资料", 404)
                v = (
                    pinned.get(key)
                    or preferred
                    or s.scalar(
                        select(SourceVersion)
                        .where(SourceVersion.source_id == key)
                        .order_by(SourceVersion.number.desc())
                    )
                )
                if v:
                    source_versions.append(v.id)
            for key in dict.fromkeys(artifact_ids):
                a = self.service.artifact(s, project_id, key)
                v = s.scalar(
                    select(ArtifactVersion)
                    .where(ArtifactVersion.artifact_id == a.id)
                    .order_by(ArtifactVersion.number.desc())
                )
                if v:
                    artifact_versions.append(v.id)
            return {
                "scope": scope,
                "source_version_ids": source_versions,
                "artifact_version_ids": artifact_versions,
                "chunker": CHUNKER,
            }

    def ensure_chunks(self, project_id, version_ids):
        version_ids = sorted(set(version_ids))
        if not version_ids:
            return
        with self.db.session() as session:
            self.service.project(session, project_id)
            owned = set(
                session.scalars(
                    select(SourceVersion.id)
                    .join(ProjectSource, ProjectSource.source_id == SourceVersion.source_id)
                    .where(
                        ProjectSource.project_id == project_id,
                        SourceVersion.id.in_(version_ids),
                        ~ProjectSource.source_id.in_(deleted_ids("source", project_id)),
                    )
                )
            )
            if owned != set(version_ids):
                raise Problem("资料版本不属于当前项目", 404)
            present = set(
                session.scalars(
                    select(SourceChunk.source_version_id)
                    .where(
                        SourceChunk.source_version_id.in_(version_ids),
                        SourceChunk.chunker_version == CHUNKER,
                    )
                    .distinct()
                )
            )
        for version_id in [key for key in version_ids if key not in present]:
            try:
                with self.db.session() as s:
                    version = s.get(SourceVersion, version_id)
                    if not version:
                        raise Problem("资料版本不存在", 404)
                    self.service.source(s, project_id, version.source_id)
                    existing = s.scalar(
                        select(func.count())
                        .select_from(SourceChunk)
                        .where(
                            SourceChunk.source_version_id == version_id,
                            SourceChunk.chunker_version == CHUNKER,
                        )
                    )
                    if existing:
                        continue
                    ordinal = 0
                    section = ""
                    for span in s.scalars(
                        select(SourceSpan)
                        .where(SourceSpan.source_version_id == version_id)
                        .order_by(SourceSpan.page)
                    ):
                        headings = list(HEADING.finditer(span.text))
                        for start, end in windows(span.text):
                            earlier = [h for h in headings if h.start() <= start]
                            if earlier:
                                section = earlier[-1].group().strip()[:500]
                            text = span.text[start:end]
                            digest = hashlib.sha256(text.encode()).hexdigest()
                            key = uuid5(
                                NAMESPACE_URL,
                                f"zhixu:{version_id}:{span.id}:{start}:{end}:{CHUNKER}",
                            ).hex
                            s.add(
                                SourceChunk(
                                    id=key,
                                    source_version_id=version_id,
                                    source_span_id=span.id,
                                    ordinal=ordinal,
                                    section=section,
                                    page_start=span.page,
                                    page_end=span.page,
                                    char_start=start,
                                    char_end=end,
                                    text=text,
                                    text_hash=digest,
                                    chunker_version=CHUNKER,
                                )
                            )
                            ordinal += 1
            except IntegrityError:
                # Concurrent callers generate identical immutable IDs. The winner
                # commits the complete version in one transaction.
                with self.db.session() as s:
                    if not s.scalar(
                        select(SourceChunk.id)
                        .where(
                            SourceChunk.source_version_id == version_id,
                            SourceChunk.chunker_version == CHUNKER,
                        )
                        .limit(1)
                    ):
                        raise

    def items(self, project_id, snapshot):
        versions = snapshot.get("source_version_ids", [])
        self.ensure_chunks(project_id, versions)
        items = []
        with self.db.session() as s:
            self.service.project(s, project_id)
            rows = s.execute(
                select(SourceChunk, SourceVersion, Source)
                .join(SourceVersion, SourceVersion.id == SourceChunk.source_version_id)
                .join(Source, Source.id == SourceVersion.source_id)
                .join(ProjectSource, ProjectSource.source_id == Source.id)
                .where(
                    ProjectSource.project_id == project_id,
                    SourceChunk.source_version_id.in_(versions),
                    SourceChunk.chunker_version == CHUNKER,
                )
                .order_by(SourceChunk.source_version_id, SourceChunk.ordinal)
            )
            for chunk, v, source in rows:
                items.append(
                    Evidence(
                        chunk.id,
                        "C",
                        source.title,
                        chunk.text,
                        source.id,
                        v.id,
                        v.number,
                        chunk.page_start,
                        chunk.section,
                    )
                )
            for key in snapshot.get("artifact_version_ids", []):
                version = s.get(ArtifactVersion, key)
                if not version:
                    raise Problem("记录版本不存在", 404)
                record = self.service.artifact(s, project_id, version.artifact_id)
                # Stable record versions retain their original V citations.
                authority = (
                    "confirmed_record"
                    if record.status == "confirmed" and version.author == "human"
                    else ("assistant_draft" if version.author == "assistant" else "user_record")
                )
                items.append(
                    Evidence(
                        version.id,
                        "V",
                        record.title,
                        version.content[:16000],
                        record.id,
                        version.id,
                        version.number,
                        section=record.kind,
                        authority=authority,
                    )
                )
        order = {
            key: number
            for number, key in enumerate([*versions, *snapshot.get("artifact_version_ids", [])])
        }
        return sorted(items, key=lambda item: order[item.version_id])

    def overview(self, project_id):
        snapshot = self.snapshot(project_id, scope="project")
        items = self.items(project_id, snapshot)
        return {
            "sources": len(snapshot["source_version_ids"]),
            "records": len(snapshot["artifact_version_ids"]),
            "chunks": sum(e.kind == "C" for e in items),
            "chunker": CHUNKER,
            "source_versions": snapshot["source_version_ids"],
        }
