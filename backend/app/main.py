from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .db import create_pool
from .finance import router as finance_router
from .imports import router as imports_router
from .inventory_intake import router as inventory_intake_router
from .inventory_state import router as inventory_state_router
from .purchase_lots import router as purchase_lots_router
from .refunds import router as refunds_router
from .settings import get_settings
from .storage_locations import router as storage_locations_router


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _valid_request_id(value: str | None) -> str:
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


def _dashboard_html() -> str:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    scripts = (
        '<script src="/assets/inventory-intake.js" defer></script>',
        '<script src="/assets/inventory-imports.js" defer></script>',
        '<script src="/assets/founder-finance.js" defer></script>',
    )
    for script in scripts:
        if script not in html:
            html = html.replace("</body>", f"  {script}\n</body>")
    return html


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
        version="1.2.0",
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
            response = JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; style-src 'self'; img-src 'self' data:; "
            f"connect-src 'self' {settings.supabase_url}; "
            "font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.get("/", include_in_schema=False)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(_dashboard_html())

    @app.get("/api/v1/public-config", include_in_schema=False)
    async def public_config() -> dict:
        return {
            "supabase_url": settings.supabase_url,
            "publishable_key": settings.supabase_publishable_key,
        }

    @app.get("/health/live")
    async def live() -> dict:
        return {"status": "ok", "service": "drop-rate-api", "environment": settings.environment}

    @app.get("/health/ready")
    async def ready(request: Request):
        try:
            async with request.app.state.db_pool.acquire() as connection:
                value = await connection.fetchval("select 1")
            if value != 1:
                raise RuntimeError("Unexpected readiness response")
        except Exception:
            return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unavailable"})
        return {"status": "ready", "database": "connected"}

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
    app.include_router(router)
    app.include_router(finance_router)
    app.include_router(refunds_router)
    app.include_router(imports_router)
    app.include_router(inventory_intake_router)
    app.include_router(inventory_state_router)
    app.include_router(purchase_lots_router)
    app.include_router(storage_locations_router)
    return app
