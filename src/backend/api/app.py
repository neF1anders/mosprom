from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings
from ..container import Container
from ..domain.errors import AppError
from .body_limit import RequestBodyLimit
from .middleware import LocalSecurity
from .routes import (
    answers,
    artifacts,
    attachments,
    control,
    diagnostics,
    events,
    jobs,
    messages,
    model,
    queue,
    sessions,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if len(settings.session_secret) < 32:
        raise RuntimeError("Set SESSION_SECRET using python scripts/bootstrap.py")
    container = Container(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await container.close()

    app = FastAPI(
        title="Mosprom Stage 1",
        version="1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.container = container
    app.add_middleware(RequestBodyLimit)
    app.add_middleware(LocalSecurity, origin=settings.app_origin, secret=settings.session_secret)

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse({"error": exc.message, "code": exc.code}, status_code=exc.status)

    for module in [
        jobs,
        messages,
        queue,
        answers,
        control,
        attachments,
        events,
        artifacts,
        diagnostics,
        model,
        sessions,
    ]:
        app.include_router(module.router, prefix="/api/v1")
    frontend = Path("src/web/dist")
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
