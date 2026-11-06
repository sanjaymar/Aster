from pathlib import Path
import tempfile

from fastapi import UploadFile, File, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from aster.domain.schemas import (
    RecordInput,
    ExperimentInput,
    ResultInput,
)
from aster.domain.service import Problem


def configure(app):
    service = app.state.service
    db = app.state.db

    @app.get("/api/projects/{project_id}/artifacts")
    def artifacts(project_id: str, kind: str | None = None):
        return service.artifacts(project_id, kind)

    @app.post("/api/projects/{project_id}/artifacts", status_code=201)
    def create_artifact(project_id: str, body: RecordInput):
        return service.save_record(project_id, **body.model_dump())

    @app.put("/api/projects/{project_id}/artifacts/{artifact_id}")
    def update_artifact(project_id: str, artifact_id: str, body: RecordInput):
        return service.save_record(project_id, artifact_id=artifact_id, **body.model_dump())

    @app.get("/api/projects/{project_id}/artifacts/{artifact_id}/history")
    def artifact_history(project_id: str, artifact_id: str):
        return service.artifact_history(project_id, artifact_id)

    @app.get("/api/projects/{project_id}/evidence/{kind}/{key}")
    def evidence(project_id: str, kind: str, key: str):
        if kind not in {"S", "C", "V"}:
            raise Problem("不支持的依据类型")
        with db.session() as s:
            service.project(s, project_id)
            return service.evidence(s, project_id, kind, key)

    @app.get("/api/projects/{project_id}/experiments")
    def experiments(project_id: str):
        return service.experiments(project_id)

    @app.post("/api/projects/{project_id}/experiments", status_code=201)
    def create_experiment(project_id: str, body: ExperimentInput):
        return service.save_experiment(project_id, **body.model_dump())

    @app.put("/api/projects/{project_id}/experiments/{experiment_id}")
    def update_experiment(project_id: str, experiment_id: str, body: ExperimentInput):
        return service.save_experiment(project_id, experiment_id=experiment_id, **body.model_dump())

    @app.post("/api/projects/{project_id}/experiments/{experiment_id}/results", status_code=201)
    def record_result(project_id: str, experiment_id: str, body: ResultInput):
        return service.record_result(project_id, experiment_id, **body.model_dump())

    @app.get("/api/projects/{project_id}/search")
    def search(project_id: str, q: str = Query(min_length=1, max_length=200)):
        return service.search(project_id, q)

    @app.get("/api/projects/{project_id}/export")
    def export(project_id: str):
        with tempfile.NamedTemporaryFile(
            prefix="aster-backup-", suffix=".zip", delete=False
        ) as temporary:
            path = Path(temporary.name)
        try:
            service.export(project_id, path)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return FileResponse(
            path,
            media_type="application/zip",
            filename=f"aster-{project_id}.zip",
            background=BackgroundTask(path.unlink, missing_ok=True),
        )

    @app.post("/api/restore", status_code=201)
    def restore(file: UploadFile = File(...)):
        file.file.seek(0, 2)
        if file.file.tell() > 4 * 1024 * 1024 * 1024:
            raise Problem("备份文件不能超过 4 GB", 413)
        file.file.seek(0)
        return service.restore(file.file)
