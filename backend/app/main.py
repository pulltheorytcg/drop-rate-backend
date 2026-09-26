from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .db import create_pool
from .access_control import router as access_control_router
from .finance import router as finance_router
from .founder_onboarding import router as founder_onboarding_router
from .ebay_privacy import router as ebay_privacy_router
from .ebay_sales import router as ebay_sales_router
from .ebay_oauth import router as ebay_oauth_router
from .imports import router as imports_router
from .import_review import router as import_review_router
from .inventory_intake import router as inventory_intake_router
from .inventory_intelligence import router as inventory_intelligence_router
from .inventory_market_values import router as inventory_market_values_router
from .inventory_state import router as inventory_state_router
from .identity_review import router as identity_review_router
from .condition_review import router as condition_review_router
from .market_adapter_config import configure_market_adapters
from .market_ingestion import router as market_ingestion_router
from .market_discovery import router as market_discovery_router
from .market_mappings import router as market_mappings_router
from .marketplace_listings import router as marketplace_listings_router
from .market_provider_probe import router as market_provider_probe_router
from .market_smoke import router as market_smoke_router
from .pricing import router as pricing_router
from .payout_preferences import router as payout_preferences_router
from .imported_benchmark_pricing import router as imported_benchmark_pricing_router
from .ebay_sold_pricing import router as ebay_sold_pricing_router
from .pricing_preview import router as pricing_preview_router
from .purchase_lots import router as purchase_lots_router
from .refunds import router as refunds_router
from .settings import get_settings
from .shopify import router as shopify_router
from .shopify_client import ShopifyApiError
from .shopify_pipeline import router as shopify_pipeline_router
from .shopify_readiness import router as shopify_readiness_router
from .storage_locations import router as storage_locations_router
from .stripe_connect import router as stripe_connect_router


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
        '<script src="/assets/dashboard-shell.js" defer></script>',
        '<script src="/assets/identity-review.js" defer></script>',
        '<script src="/assets/shopify-settings.js" defer></script>',
        '<script src="/assets/media-condition.js" defer></script>',
        '<script src="/assets/market-smoke-panel.js" defer></script>',
        '<script src="/assets/market-mapping-workbench.js" defer></script>',
        '<script src="/assets/market-value-column.js" defer></script>',
    )
    for script in scripts:
        if script not in html:
            html = html.replace("</body>", f"  {script}\n</body>")
    return html


def _database_error_response(exc: asyncpg.PostgresError, request_id: str) -> JSONResponse:
    """Translate known database guard failures without exposing SQL/provider details."""

    if exc.sqlstate == "55000":
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Operation conflicts with an immutable or historical record state",
                "request_id": request_id,
            },
        )
    if exc.sqlstate == "23505":
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Operation conflicts with an existing record",
                "request_id": request_id,
            },
        )
    if exc.sqlstate == "23503":
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Operation conflicts with a referenced record",
                "request_id": request_id,
            },
        )
    if exc.sqlstate in {"23514", "23502"}:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Operation violates a data integrity rule",
                "request_id": request_id,
            },
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_market_adapters(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db_pool = await create_pool(settings)
        try:
            yield
        finally:
            await app.state.db_pool.close()

    app = FastAPI(
        title="Drop Rate API",
        version="1.5.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = _valid_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        if (
            request.method.upper() == "POST"
            and request.url.path.startswith("/api/v1/market/ingestion/")
            and not settings.market_ingestion_enabled
        ):
            response = JSONResponse(
                status_code=409,
                content={
                    "detail": "Production market ingestion is disabled until provider access is explicitly approved",
                    "request_id": request_id,
                },
            )
        else:
            try:
                response = await call_next(request)
            except asyncpg.PostgresError as exc:
                response = _database_error_response(exc, request_id)
            except ShopifyApiError as exc:
                response = JSONResponse(
                    status_code=502,
                    content={
                        "detail": "Shopify operation failed",
                        "retryable": exc.retryable,
                        "request_id": request_id,
                    },
                )
            except Exception:
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "Internal server error", "request_id": request_id},
                )
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

    @app.get("/join", include_in_schema=False)
    async def founder_join() -> HTMLResponse:
        return HTMLResponse((STATIC_DIR / "join.html").read_text(encoding="utf-8"))

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
    app.include_router(access_control_router)
    app.include_router(finance_router)
    app.include_router(founder_onboarding_router)
    app.include_router(ebay_privacy_router)
    app.include_router(ebay_sales_router)
    app.include_router(ebay_oauth_router)
    app.include_router(refunds_router)
    app.include_router(pricing_router)
    app.include_router(payout_preferences_router)
    app.include_router(imported_benchmark_pricing_router)
    app.include_router(ebay_sold_pricing_router)
    app.include_router(pricing_preview_router)
    app.include_router(market_ingestion_router)
    app.include_router(market_mappings_router)
    app.include_router(marketplace_listings_router)
    app.include_router(market_discovery_router)
    app.include_router(market_provider_probe_router)
    app.include_router(market_smoke_router)
    app.include_router(imports_router)
    app.include_router(import_review_router)
    app.include_router(inventory_intake_router)
    app.include_router(inventory_intelligence_router)
    app.include_router(inventory_market_values_router)
    app.include_router(inventory_state_router)
    app.include_router(identity_review_router)
    app.include_router(condition_review_router)
    app.include_router(shopify_router)
    app.include_router(shopify_pipeline_router)
    app.include_router(shopify_readiness_router)
    app.include_router(purchase_lots_router)
    app.include_router(storage_locations_router)
    app.include_router(stripe_connect_router)
    return app
