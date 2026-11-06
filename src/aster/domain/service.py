"""Transactional application services shared by HTTP and harness tools."""

from sqlalchemy import select, func

from aster.domain.extensions import EXTENSIONS
from aster.domain.models import (
    Project,
    Source,
    ProjectSource,
    Artifact,
    now,
)


from aster.domain.common import (
    CITATION as CITATION,
    Problem as Problem,
    plain as plain,
    required as required,
)
from aster.domain.management import deleted_ids, is_deleted


from aster.domain.library import Library
from aster.domain.records import Records


class Service(Library, Records):
    def __init__(self, db):
        self.db = db
        self.files = db.data_dir / "library" / "files"
        self.files.mkdir(parents=True, exist_ok=True)

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
                "counts": {**counts, "sources": sources},
                "recent": [self._artifact_dict(s, a) for a in recent],
            }

    def export(self, project_id, target=None):
        from aster.storage.archive import ProjectArchive

        return ProjectArchive(self).export(project_id, target)

    def restore(self, data):
        from aster.storage.archive import ProjectArchive

        return ProjectArchive(self).restore(data)
