from fastapi import UploadFile, File, Form
from fastapi.responses import FileResponse

from aster.domain.models import (
    Asset,
)
from aster.domain.schemas import (
    ReadingInput,
    AnnotationInput,
)
from aster.domain.service import Problem, required


def configure(app):
    @app.get("/api/projects/{project_id}/sources/{source_id}/figures")
    def figures(project_id: str, source_id: str, version_id: str | None = None):
        from aster.library.figures import extract
        return extract(app.state.service, project_id, source_id, version_id)

    @app.get("/api/projects/{project_id}/sources/{source_id}/preview")
    def preview(project_id: str, source_id: str, version_id: str | None = None, page: int = 1):
        from aster.library.figures import thumbnail
        return FileResponse(thumbnail(app.state.service, project_id, source_id, version_id, page), media_type="image/png")

    @app.get("/api/projects/{project_id}/map")
    def literature_map(project_id: str):
        from aster.library.map import build_map

        return build_map(app.state.service, project_id)

    service = app.state.service
    db = app.state.db
    reading = app.state.reading

    @app.get("/api/projects/{project_id}/sources")
    def sources(project_id: str):
        return service.sources(project_id)

    @app.post("/api/projects/{project_id}/sources", status_code=201)
    def import_source(
        project_id: str,
        file: UploadFile = File(...),
        title: str = Form(""),
        authors: str = Form(""),
        year: str = Form(""),
        doi: str = Form(""),
        source_id: str | None = Form(None),
    ):
        return service.import_source(
            project_id,
            file.filename or "document.pdf",
            file.file.read(200 * 1024 * 1024 + 1),
            title=title,
            authors=authors,
            year=year,
            doi=doi,
            source_id=source_id,
        )

    @app.get("/api/projects/{project_id}/sources/{source_id}/pages")
    def source_pages(project_id: str, source_id: str, version_id: str | None = None):
        return service.source_pages(project_id, source_id, version_id)

    @app.patch("/api/projects/{project_id}/sources/{source_id}/reading")
    def update_reading(project_id: str, source_id: str, body: ReadingInput):
        return reading.update(project_id, source_id, body.model_dump(exclude_unset=True))

    @app.get("/api/projects/{project_id}/sources/{source_id}/annotations")
    def source_annotations(project_id: str, source_id: str, version_id: str | None = None):
        return reading.annotations(project_id, source_id, version_id)

    @app.post("/api/projects/{project_id}/sources/{source_id}/annotations", status_code=201)
    def add_annotation(project_id: str, source_id: str, body: AnnotationInput):
        return reading.annotate(project_id, source_id, body.model_dump())

    @app.delete("/api/projects/{project_id}/sources/{source_id}/annotations/{annotation_id}")
    def delete_annotation(project_id: str, source_id: str, annotation_id: str):
        return reading.remove(project_id, source_id, annotation_id)

    @app.get("/api/projects/{project_id}/sources/{source_id}/notes")
    def source_notes(project_id: str, source_id: str):
        return reading.notes(project_id, source_id)

    @app.post("/api/projects/{project_id}/sources/{source_id}/link", status_code=201)
    def link_source(project_id: str, source_id: str, body: dict):
        from aster.domain.models import ProjectSource

        target_id = str(body.get("target_project_id", ""))
        with db.session() as s:
            service.source(s, project_id, source_id)
            service.project(s, target_id)
            if not s.get(ProjectSource, (target_id, source_id)):
                s.add(ProjectSource(project_id=target_id, source_id=source_id))
        return {"linked": True}

    @app.post("/api/projects/{project_id}/assets", status_code=201)
    def upload_asset(project_id: str, file: UploadFile = File(...)):
        return service.add_asset(
            project_id,
            file.filename or "attachment",
            file.file.read(25 * 1024 * 1024 + 1),
            file.content_type or "application/octet-stream",
        )

    @app.get("/api/projects/{project_id}/assets/{asset_id}/csv")
    def csv_data(project_id: str, asset_id: str):
        return service.csv_preview(project_id, asset_id)

    @app.get("/api/assets/{asset_id}")
    def asset(asset_id: str, inline: bool = False):
        with db.session() as s:
            a = required(s, Asset, asset_id)
            service.project(s, a.project_id)
            path = service.files / a.storage_key
            if not path.is_file():
                raise Problem("附件文件缺失", 404)
            allowed = {
                "application/pdf",
                "image/png",
                "image/jpeg",
                "image/webp",
                "text/plain",
                "text/plain; charset=utf-8",
            }
            media = (
                a.media_type if inline and a.media_type in allowed else "application/octet-stream"
            )
            return FileResponse(
                path,
                filename=a.name,
                media_type=media,
                content_disposition_type="inline"
                if inline and a.media_type in allowed
                else "attachment",
            )
