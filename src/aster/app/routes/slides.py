from fastapi.responses import Response
from aster.slides.schema import DeckSave
from aster.slides.service import Slides


def configure(app):
    slides = Slides(app.state.service)

    @app.post("/api/projects/{project_id}/decks", status_code=201)
    def create(project_id: str, body: DeckSave):
        return slides.save(project_id, body.model_dump(exclude={"expected_revision"}))

    @app.put("/api/projects/{project_id}/decks/{artifact_id}")
    def update(project_id: str, artifact_id: str, body: DeckSave):
        return slides.save(
            project_id,
            body.model_dump(exclude={"expected_revision"}),
            artifact_id,
            body.expected_revision,
        )

    @app.get("/api/projects/{project_id}/decks/{artifact_id}/export")
    def export(project_id: str, artifact_id: str):
        return Response(
            slides.export(project_id, artifact_id),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": 'attachment; filename="presentation.pptx"'},
        )

    @app.get("/api/projects/{project_id}/decks/{artifact_id}/pack")
    def pack(project_id: str, artifact_id: str):
        return Response(
            slides.pack(project_id, artifact_id),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="codex-ppt.zip"'},
        )
