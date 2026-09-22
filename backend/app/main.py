from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import router
from .db import create_pool
from .settings import get_settings


def _valid_request_id(value: str | None) -> str:
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db_pool = await create_pool(settings)
        try:
            yield
        finally:
            await app.state.db_pool.close()

    app = FastAPI(
        title="Drop Rate API",
        version="0.3.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = _valid_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error",
                    "request_id": request_id,
                },
            )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health/live")
    async def live() -> dict:
        return {
            "status": "ok",
            "service": "drop-rate-api",
            "environment": settings.environment,
        }

    @app.get("/health/ready")
    async def ready(request: Request):
        try:
            async with request.app.state.db_pool.acquire() as connection:
                value = await connection.fetchval("select 1")
            if value != 1:
                raise RuntimeError("Unexpected readiness response")
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "database": "unavailable"},
            )
        return {"status": "ready", "database": "connected"}

    app.include_router(router)
    return app
