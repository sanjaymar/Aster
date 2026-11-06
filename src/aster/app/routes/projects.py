from aster.domain.schemas import (
    ProjectInput,
)


def configure(app):
    service = app.state.service

    @app.get("/api/projects")
    def projects():
        return service.projects()

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectInput):
        return service.save_project(**body.model_dump())

    @app.put("/api/projects/{project_id}")
    def edit_project(project_id: str, body: ProjectInput):
        return service.save_project(project_id=project_id, **body.model_dump())

    @app.get("/api/projects/{project_id}/overview")
    def overview(project_id: str):
        return service.overview(project_id)
