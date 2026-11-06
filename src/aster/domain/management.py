"""Recoverable data management without invalidating scientific evidence or shared sources."""

from sqlalchemy import select, delete
from aster.domain.common import Problem, plain, required
from aster.domain.models import (
    Project,
    Artifact,
    Experiment,
    ExperimentRun,
    AgentRun,
    TrashItem,
    Conversation,
    uid,
)


def deleted_ids(kind, project_id=None):
    query = select(TrashItem.object_id).where(TrashItem.kind == kind)
    return query.where(TrashItem.project_id == project_id) if project_id else query


def is_deleted(session, project_id, kind, object_id):
    return (
        session.scalar(
            select(TrashItem.id).where(
                TrashItem.project_id == project_id,
                TrashItem.kind == kind,
                TrashItem.object_id == object_id,
            )
        )
        is not None
    )


class DataManagement:
    def __init__(self, service):
        self.service, self.db = service, service.db

    def remove(self, project_id, kind, object_id):
        with self.db.session() as session:
            self.service.project(session, project_id)
            if session.scalar(
                select(AgentRun.id)
                .where(
                    AgentRun.project_id == project_id, AgentRun.status.in_(["running", "queued"])
                )
                .limit(1)
            ):
                raise Problem("请先停止或等待当前项目的问答任务完成，再删除资料", 409)
            if is_deleted(session, project_id, kind, object_id):
                return {"deleted": True}
            if kind == "source":
                row = self.service.source(session, project_id, object_id)
            elif kind == "artifact":
                row = self.service.artifact(session, project_id, object_id)
                if row.kind == "plan":
                    experiment = session.scalar(
                        select(Experiment).where(Experiment.plan_artifact_id == row.id)
                    )
                    if experiment:
                        kind, row = "experiment", experiment
            elif kind == "experiment":
                row = required(session, Experiment, object_id)
                if row.project_id != project_id:
                    raise Problem("实验不属于当前项目", 404)
            elif kind == "conversation":
                row = required(session, Conversation, object_id)
                if row.project_id != project_id:
                    raise Problem("对话不属于当前项目", 404)
            elif kind == "project" and object_id == project_id:
                row = self.service.project(session, project_id)
            else:
                raise Problem("不支持的删除对象", 404)
            batch = uid()

            def mark(item_kind, item, visible=True):
                if not is_deleted(session, project_id, item_kind, item.id):
                    session.add(
                        TrashItem(
                            project_id=project_id,
                            kind=item_kind,
                            object_id=item.id,
                            title=item.title,
                            batch=batch,
                            visible=visible,
                        )
                    )
                    session.flush()

            mark(kind, row)
            if kind == "experiment":
                mark("artifact", required(session, Artifact, row.plan_artifact_id), False)
                for result_id in session.scalars(
                    select(ExperimentRun.result_artifact_id).where(
                        ExperimentRun.experiment_id == row.id
                    )
                ):
                    mark("artifact", required(session, Artifact, result_id), False)
        return {"deleted": True, "recoverable": True}

    def trash(self, project_id=None):
        with self.db.session() as session:
            if project_id:
                self.service.project(session, project_id)
            query = (
                select(TrashItem)
                .join(Project, Project.id == TrashItem.project_id)
                .where(Project.workspace_id == "personal", TrashItem.visible.is_(True))
            )
            query = (
                query.where(
                    (TrashItem.kind == "project")
                    | (
                        (TrashItem.project_id == project_id)
                        & ~TrashItem.project_id.in_(deleted_ids("project"))
                    )
                )
                if project_id
                else query.where(TrashItem.kind == "project")
            )
            return [
                plain(row) for row in session.scalars(query.order_by(TrashItem.deleted_at.desc()))
            ]

    def restore(self, item_id):
        with self.db.session() as session:
            item = required(session, TrashItem, item_id)
            project = required(session, Project, item.project_id)
            if project.workspace_id != "personal":
                raise Problem("没有访问此项目的权限", 403)
            if item.kind != "project":
                self.service.project(session, item.project_id)
            session.execute(
                delete(TrashItem).where(
                    TrashItem.batch == item.batch, TrashItem.project_id == item.project_id
                )
            )
        return {"restored": True, "project_id": project.id}

    def edit_source(self, project_id, source_id, values):
        with self.db.session() as session:
            source = self.service.source(session, project_id, source_id)
            for key, value in values.items():
                setattr(source, key, value)
            session.flush()
            return plain(source)

    def edit_conversation(self, project_id, conversation_id, title):
        with self.db.session() as session:
            self.service.project(session, project_id)
            row = required(session, Conversation, conversation_id)
            if row.project_id != project_id or is_deleted(
                session, project_id, "conversation", conversation_id
            ):
                raise Problem("对话不属于当前项目或已删除", 404)
            row.title = title
            session.flush()
            return plain(row)
