import hashlib
import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from aster.storage.database import Database
from aster.domain.extensions import EXTENSIONS
from aster.app.runtime import RunManager
from aster.domain.schemas import (
    ModelInput,
)
from aster.domain.service import Service, Problem
from aster.app.settings import Settings


def create_app(settings=None):
    settings = settings or Settings.from_env()
    db = Database(settings.database_url, settings.data_dir)
    service = Service(db)
    manager = RunManager(service, settings)
    from aster.domain.reading import ReadingLibrary

    reading = ReadingLibrary(service)

    @asynccontextmanager
    async def lifespan(app):
        db.migrate()
        manager.recover()
        yield
        manager.shutdown()

    app = FastAPI(title="Aster API", version="0.1.0", lifespan=lifespan)
    app.state.db, app.state.service, app.state.manager = db, service, manager
    app.state.reading = reading
    from aster.app.routes import (
        projects,
        library,
        documents,
        conversations,
        diagnostics,
        management,
        preferences,
    )

    for routes in (
        projects,
        library,
        documents,
        conversations,
        diagnostics,
        management,
        preferences,
    ):
        routes.configure(app)

    @app.exception_handler(Problem)
    async def problem_handler(request, error):
        return JSONResponse({"detail": error.message}, status_code=error.status)

    @app.middleware("http")
    async def boundary(request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if (
                request.method not in {"GET", "HEAD", "OPTIONS"}
                and origin
                and origin != f"{request.url.scheme}://{request.headers.get('host')}"
            ):
                return JSONResponse({"detail": "不接受来自其他站点的修改请求"}, status_code=403)
            if settings.access_token and request.url.path != "/api/session":
                bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
                expected = hmac.new(
                    settings.access_token.encode(), b"zhixu-session", hashlib.sha256
                ).hexdigest()
                cookie = request.cookies.get("zhixu_session", "")
                if not (
                    hmac.compare_digest(bearer, settings.access_token)
                    or hmac.compare_digest(cookie, expected)
                ):
                    return JSONResponse({"detail": "请先登录Aster"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.get("/api/session")
    def session_state(request: Request):
        expected = hmac.new(
            settings.access_token.encode(), b"zhixu-session", hashlib.sha256
        ).hexdigest()
        return {
            "required": bool(settings.access_token),
            "authenticated": not settings.access_token
            or hmac.compare_digest(request.cookies.get("zhixu_session", ""), expected),
        }

    @app.post("/api/session")
    async def login(request: Request):
        data = await request.json()
        if not hmac.compare_digest(str(data.get("token", "")), settings.access_token):
            raise Problem("访问口令不正确", 401)
        value = hmac.new(
            settings.access_token.encode(), b"zhixu-session", hashlib.sha256
        ).hexdigest()
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            "zhixu_session",
            value,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=86400,
        )
        return response

    @app.delete("/api/session")
    def logout():
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("zhixu_session")
        return response

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "name": "Aster",
            "version": "0.1.0",
            "database": db.engine.dialect.name,
        }

    @app.get("/api/extensions")
    def extensions():
        return [
            {
                "key": e.key,
                "label": e.label,
                "artifact_kinds": e.artifact_kinds,
                "experiments": e.experiments,
            }
            for e in EXTENSIONS.values()
        ]

    @app.get("/api/model")
    def model():
        return manager.model_health()

    @app.put("/api/model")
    def save_model(body: ModelInput):
        return manager.save_model_settings(body.model_dump())

    static = settings.static_dir
    if static.is_dir():
        assets = static / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="static-assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                raise Problem("接口不存在", 404)
            if path == "favicon.svg":
                return FileResponse(static / path)
            # The shell points to versioned assets and must revalidate on navigation.
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app
