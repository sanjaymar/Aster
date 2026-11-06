"""Transactional application services shared by HTTP and harness tools."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

from sqlalchemy import select

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
    AgentRun,
    RunEvent,
    Conversation,
    Message,
    SourceChunk,
    PipelineStage,
    MemorySnapshot,
    AnswerClaim,
    EvaluationRun,
    ReadingState,
    Annotation,
    TrashItem,
    now,
    uid,
)


from aster.domain.common import CITATION, Problem, plain


class ProjectArchive:
    def __init__(self, service):
        self.service, self.db, self.files = service, service.db, service.files

    def export(self, project_id, target=None):
        """Portable archive: immutable versions + all referenced files, no credentials."""
        with self.db.session() as s:
            # A backup must see one coherent snapshot even while the worker saves.
            if self.db.engine.dialect.name == "sqlite":
                s.connection().exec_driver_sql("BEGIN")
            else:
                s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            project = self.service.project(s, project_id)
            project_sources = list(
                s.scalars(select(ProjectSource).where(ProjectSource.project_id == project_id))
            )
            source_ids = [p.source_id for p in project_sources]
            versions = list(
                s.scalars(select(SourceVersion).where(SourceVersion.source_id.in_(source_ids)))
            )
            version_ids = [v.id for v in versions]
            artifacts = list(s.scalars(select(Artifact).where(Artifact.project_id == project_id)))
            art_versions = list(
                s.scalars(
                    select(ArtifactVersion).where(
                        ArtifactVersion.artifact_id.in_([a.id for a in artifacts])
                    )
                )
            )
            av_ids = [v.id for v in art_versions]
            exp = list(s.scalars(select(Experiment).where(Experiment.project_id == project_id)))
            groups = {
                "projects": [project],
                "trash_items": list(
                    s.scalars(select(TrashItem).where(TrashItem.project_id == project_id))
                ),
                "sources": list(s.scalars(select(Source).where(Source.id.in_(source_ids)))),
                "project_sources": project_sources,
                "reading_states": list(
                    s.scalars(select(ReadingState).where(ReadingState.project_id == project_id))
                ),
                "annotations": list(
                    s.scalars(select(Annotation).where(Annotation.project_id == project_id))
                ),
                "source_versions": versions,
                "source_spans": list(
                    s.scalars(
                        select(SourceSpan).where(SourceSpan.source_version_id.in_(version_ids))
                    )
                ),
                "source_chunks": list(
                    s.scalars(
                        select(SourceChunk).where(SourceChunk.source_version_id.in_(version_ids))
                    )
                ),
                "artifacts": artifacts,
                "artifact_versions": art_versions,
                "evidence_links": list(
                    s.scalars(
                        select(EvidenceLink).where(EvidenceLink.artifact_version_id.in_(av_ids))
                    )
                ),
                "artifact_assets": list(
                    s.scalars(
                        select(ArtifactAsset).where(ArtifactAsset.artifact_version_id.in_(av_ids))
                    )
                ),
                "experiments": exp,
                "experiment_runs": list(
                    s.scalars(
                        select(ExperimentRun).where(
                            ExperimentRun.experiment_id.in_([e.id for e in exp])
                        )
                    )
                ),
            }
            conversations = list(
                s.scalars(select(Conversation).where(Conversation.project_id == project_id))
            )
            runs = list(s.scalars(select(AgentRun).where(AgentRun.project_id == project_id)))
            groups.update(
                {
                    "conversations": conversations,
                    "messages": list(
                        s.scalars(
                            select(Message).where(
                                Message.conversation_id.in_([c.id for c in conversations])
                            )
                        )
                    ),
                    "agent_runs": runs,
                    "run_events": list(
                        s.scalars(select(RunEvent).where(RunEvent.run_id.in_([r.id for r in runs])))
                    ),
                    "pipeline_stages": list(
                        s.scalars(
                            select(PipelineStage).where(
                                PipelineStage.run_id.in_([r.id for r in runs])
                            )
                        )
                    ),
                    "memory_snapshots": list(
                        s.scalars(
                            select(MemorySnapshot).where(MemorySnapshot.project_id == project_id)
                        )
                    ),
                    "answer_claims": list(
                        s.scalars(
                            select(AnswerClaim).where(AnswerClaim.run_id.in_([r.id for r in runs]))
                        )
                    ),
                    "evaluation_runs": list(
                        s.scalars(
                            select(EvaluationRun).where(EvaluationRun.project_id == project_id)
                        )
                    ),
                }
            )
            asset_ids = {v.asset_id for v in versions} | {
                a.asset_id for a in groups["artifact_assets"]
            }
            assets = list(
                s.scalars(
                    select(Asset).where((Asset.project_id == project_id) | Asset.id.in_(asset_ids))
                )
            )
            groups["assets"] = assets
            manifest = {
                "format": "zhixu-project",
                "version": 1,
                "exported_at": now(),
                "tables": {k: [plain(r) for r in v] for k, v in groups.items()},
            }
            buffer = io.BytesIO() if target is None else target
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                for asset in assets:
                    path = self.files / asset.storage_key
                    if path.exists() and "files/" + asset.storage_key not in z.namelist():
                        z.write(path, "files/" + asset.storage_key)
                for a in artifacts:
                    v = next(
                        (
                            v
                            for v in art_versions
                            if v.artifact_id == a.id and v.number == a.revision
                        ),
                        None,
                    )
                    if v:
                        z.writestr(f"markdown/{a.kind}-{a.id}.md", f"# {a.title}\n\n{v.content}")

                def escape_bib(text):
                    return (
                        str(text)
                        .replace("\\", "\\textbackslash{}")
                        .replace("{", "\\{")
                        .replace("}", "\\}")
                        .replace("\n", " ")
                    )

                z.writestr(
                    "references.bib",
                    "\n\n".join(
                        "@misc{"
                        + a.id
                        + ",\n  title={"
                        + escape_bib(a.title)
                        + "},\n  author={"
                        + escape_bib(a.authors)
                        + "},\n  year={"
                        + escape_bib(a.year)
                        + "},\n  doi={"
                        + escape_bib(a.doi)
                        + "}\n}"
                        for a in groups["sources"]
                    ),
                )
            return buffer.getvalue() if target is None else str(target)

    def restore(self, data):
        table_models = {
            "sources": Source,
            "assets": Asset,
            "project_sources": ProjectSource,
            "source_versions": SourceVersion,
            "source_spans": SourceSpan,
            "source_chunks": SourceChunk,
            "reading_states": ReadingState,
            "annotations": Annotation,
            "artifacts": Artifact,
            "artifact_versions": ArtifactVersion,
            "evidence_links": EvidenceLink,
            "artifact_assets": ArtifactAsset,
            "experiments": Experiment,
            "experiment_runs": ExperimentRun,
            "conversations": Conversation,
            "messages": Message,
            "agent_runs": AgentRun,
            "run_events": RunEvent,
            "pipeline_stages": PipelineStage,
            "memory_snapshots": MemorySnapshot,
            "answer_claims": AnswerClaim,
            "evaluation_runs": EvaluationRun,
            "trash_items": TrashItem,
        }
        try:
            with zipfile.ZipFile(io.BytesIO(data) if isinstance(data, bytes) else data) as z:
                if sum(i.file_size for i in z.infolist()) > 8 * 1024 * 1024 * 1024:
                    raise Problem("备份解压后的内容不能超过 8 GB", 413)
                manifest = json.loads(z.read("manifest.json"))
                if manifest.get("format") != "zhixu-project" or manifest.get("version") != 1:
                    raise Problem("不支持的项目备份格式")
                tables = manifest["tables"]
                original = tables["projects"][0]
                mapping = {original["id"]: uid()}
                for name in table_models:
                    for row in tables.get(name, []):
                        if "id" in row:
                            mapping[row["id"]] = uid()
                for a in tables.get("assets", []):
                    key = a["storage_key"]
                    if not key or Path(key).name != key or key in {".", ".."} or "\\" in key:
                        raise Problem("附件标识无效")
                    content = z.read("files/" + key)
                    if hashlib.sha256(content).hexdigest() != a["sha256"]:
                        raise Problem("备份附件校验失败")
                    from aster.storage.paths import filename

                    restored_key = filename(a["name"])
                    path = self.files / restored_key
                    if (
                        path.exists()
                        and hashlib.sha256(path.read_bytes()).hexdigest() != a["sha256"]
                    ):
                        restored_key = f"{path.stem}-{uid()[:6]}{path.suffix}"
                    (self.files / restored_key).write_bytes(content)
                    a["storage_key"] = restored_key
                with self.db.session() as s:
                    project = Project(
                        id=mapping[original["id"]],
                        workspace_id="personal",
                        title=original["title"] + "（恢复）",
                        description=original["description"],
                        domain=original["domain"],
                        knowledge=original.get("knowledge", {}),
                    )
                    if project.domain not in EXTENSIONS:
                        raise Problem("备份中的领域扩展尚未安装")
                    s.add(project)
                    s.flush()
                    for name, model in table_models.items():
                        for row in tables.get(name, []):
                            values = dict(row)
                            for key, value in values.items():
                                if key == "workspace_id":
                                    values[key] = "personal"
                                elif key == "project_id":
                                    values[key] = project.id
                                elif (key == "id" or key.endswith("_id")) and value is not None:
                                    if value not in mapping:
                                        raise Problem("备份存在不完整的记录关联")
                                    values[key] = mapping[value]
                            if "content" in values:
                                values["content"] = CITATION.sub(
                                    lambda m: f"[[{m[1]}:{mapping.get(m[2], m[2])}]]",
                                    values["content"],
                                )
                            if name == "answer_claims":
                                values["text"] = CITATION.sub(
                                    lambda m: f"[[{m[1]}:{mapping.get(m[2], m[2])}]]",
                                    values["text"],
                                )

                            def remap(value):
                                if isinstance(value, dict):
                                    return {k: remap(v) for k, v in value.items()}
                                if isinstance(value, list):
                                    return [remap(v) for v in value]
                                if isinstance(value, str):
                                    if value in mapping:
                                        return mapping[value]
                                    return CITATION.sub(
                                        lambda m: f"[[{m[1]}:{mapping.get(m[2], m[2])}]]", value
                                    )
                                return value

                            for key in (
                                "fields",
                                "provenance",
                                "context",
                                "transcript",
                                "result",
                                "payload",
                                "state",
                                "inputs",
                                "outputs",
                                "citations",
                                "metrics",
                                "results",
                                "config",
                                "summary",
                            ):
                                if key in values:
                                    values[key] = remap(values[key])
                            if name == "agent_runs" and values["status"] in {"queued", "running"}:
                                values.update(
                                    status="interrupted",
                                    error="此任务来自项目备份，未自动重新执行。",
                                    finished_at=now(),
                                )
                            if name == "pipeline_stages" and values["status"] == "running":
                                values.update(status="interrupted", finished_at=now())
                            s.add(model(**values))
                        s.flush()
                    for v in s.scalars(
                        select(ArtifactVersion)
                        .join(Artifact)
                        .where(Artifact.project_id == project.id)
                    ):
                        for typ, key in CITATION.findall(v.content):
                            self.service.evidence(s, project.id, typ, key)
                    return plain(project)
        except Problem:
            raise
        except Exception as e:
            raise Problem("备份不完整或格式错误，未恢复项目") from e
