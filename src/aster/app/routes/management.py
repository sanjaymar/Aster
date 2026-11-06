"""Data editing, recoverable deletion and project-scoped trash."""

from aster.domain.management import DataManagement
from aster.domain.schemas import (
    SourceInput,
    ResultEditInput,
    AnnotationCommentInput,
    ConversationInput,
)


def configure(app):
    data = DataManagement(app.state.service)

    def remove(project_id, kind, object_id):
        with app.state.manager.submissions:
            return data.remove(project_id, kind, object_id)

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str):
        return remove(project_id, "project", project_id)

    @app.put("/api/projects/{project_id}/sources/{source_id}")
    def edit_source(project_id: str, source_id: str, body: SourceInput):
        return data.edit_source(project_id, source_id, body.model_dump())

    @app.delete("/api/projects/{project_id}/sources/{source_id}")
    def delete_source(project_id: str, source_id: str):
        return remove(project_id, "source", source_id)

    @app.delete("/api/projects/{project_id}/artifacts/{artifact_id}")
    def delete_record(project_id: str, artifact_id: str):
        return remove(project_id, "artifact", artifact_id)

    @app.delete("/api/projects/{project_id}/experiments/{experiment_id}")
    def delete_experiment(project_id: str, experiment_id: str):
        return remove(project_id, "experiment", experiment_id)

    @app.put("/api/projects/{project_id}/experiments/{experiment_id}/results/{result_id}")
    def edit_result(project_id: str, experiment_id: str, result_id: str, body: ResultEditInput):
        return app.state.service.edit_result(
            project_id, experiment_id, result_id, **body.model_dump()
        )

    @app.patch("/api/projects/{project_id}/sources/{source_id}/annotations/{annotation_id}")
    def edit_annotation(
        project_id: str, source_id: str, annotation_id: str, body: AnnotationCommentInput
    ):
        return app.state.reading.edit_annotation(project_id, source_id, annotation_id, body.comment)

    @app.get("/api/trash")
    def trash(project_id: str | None = None):
        return data.trash(project_id)

    @app.put("/api/projects/{project_id}/conversations/{conversation_id}")
    def edit_conversation(project_id: str, conversation_id: str, body: ConversationInput):
        return data.edit_conversation(project_id, conversation_id, body.title)

    @app.delete("/api/projects/{project_id}/conversations/{conversation_id}")
    def delete_conversation(project_id: str, conversation_id: str):
        return remove(project_id, "conversation", conversation_id)

    @app.post("/api/trash/{item_id}/restore")
    def restore(item_id: str):
        return data.restore(item_id)
