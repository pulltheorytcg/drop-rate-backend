from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .db import create_pool
from .seller_channel_sync import router as seller_channel_sync_router
from .owner_inventory import router as owner_inventory_router
from .founder_accounts import router as founder_accounts_router
from .access_control import require_platform_admin_request, router as access_control_router
from .action_required import router as action_required_router
from .automation_control import router as automation_control_router
from .automation_commands import router as automation_commands_router
from .automation_recovery import router as automation_recovery_router
from .finance import router as finance_router
from .founder_onboarding import router as founder_onboarding_router
from .free_canonical_media import router as free_canonical_media_router
from .grading_certificates import router as grading_certificates_router
from .ebay_privacy import router as ebay_privacy_router
from .ebay_sales import router as ebay_sales_router
from .ebay_oauth import router as ebay_oauth_router
from .imports import router as imports_router
from .import_enrichment import router as import_enrichment_router
from .import_review import router as import_review_router
from .inventory_intake import router as inventory_intake_router
from .catalogue_browser import router as catalogue_browser_router
from .inventory_intelligence import router as inventory_intelligence_router
from .inventory_market_values import router as inventory_market_values_router
from .inventory_state import router as inventory_state_router
from .inventory_sale_intent import router as inventory_sale_intent_router
from .identity_review import router as identity_review_router
from .condition_review import router as condition_review_router
from .competitive_intelligence_api import router as competitive_intelligence_router
from .competitive_intelligence_automation import router as competitive_intelligence_automation_router
from .collectible_identity import router as collectible_identity_router
from .market_adapter_config import configure_market_adapters
from .market_ingestion import router as market_ingestion_router
from .market_discovery import router as market_discovery_router
from .market_mappings import router as market_mappings_router
from .marketplace_listings import router as marketplace_listings_router
from .market_provider_probe import router as market_provider_probe_router
from .market_smoke import router as market_smoke_router
from .pricing import router as pricing_router
from .live_market_refresh import run_live_market_refresh
from .payout_preferences import router as payout_preferences_router
from .owner_login import router as owner_login_router
from .owner_portal_api import router as owner_portal_api_router
from .owner_portal_finance import router as owner_portal_finance_router
from .owner_onboarding import router as owner_onboarding_router
from .imported_benchmark_pricing import router as imported_benchmark_pricing_router
from .ebay_sold_pricing import router as ebay_sold_pricing_router
from .pricing_preview import router as pricing_preview_router
from .recognition import router as recognition_router
from .recognition_vision import close_shared_vision_http_client
from .recognition_images import close_reference_http_client
from .catalogue_artwork import close_artwork_tasks
from .reference_library import router as reference_library_router
from .purchase_lots import router as purchase_lots_router
from .refunds import router as refunds_router
from .settings import get_settings
from .shopify import router as shopify_router
from .shopify_client import ShopifyApiError
from .shopify_catalogue_bootstrap import run_shopify_catalogue_bootstrap
from .shopify_linked_draft_reconciliation import run_linked_draft_reconciliation
from .shopify_pipeline import router as shopify_pipeline_router
from .shopify_pooling import router as shopify_pooling_router
from .shopify_published_pooling import router as shopify_published_pooling_router
from .shopify_readiness import router as shopify_readiness_router
from .storage_locations import router as storage_locations_router

logger = logging.getLogger(__name__)
from .stripe_connect import router as stripe_connect_router
from .tcggraph_media import router as tcggraph_media_router


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
        '<script src="/assets/dashboard-shell.js?v=4" defer></script>',
        '<script src="/assets/seller-invites.js" defer></script>',
        '<script src="/assets/identity-review.js" defer></script>',
        '<script src="/assets/scanner-flow.js?v=5" defer></script>',
        '<script src="/assets/recognition-scanner.js?v=3" defer></script>',
        '<script src="/assets/reference-library.js?v=2" defer></script>',
        '<script src="/assets/shopify-settings.js" defer></script>',
        '<script src="/assets/media-condition.js" defer></script>',
        '<script src="/assets/market-smoke-panel.js" defer></script>',
        '<script src="/assets/market-mapping-workbench.js" defer></script>',
        '<script src="/assets/market-value-column.js?v=2" defer></script>',
        '<script src="/assets/founder-workspace.js" defer></script>',
        '<script src="/assets/founder-accounts.js" defer></script>',
        '<script src="/assets/catalogue-title-art.js?v=3" defer></script>',
        '<script src="/assets/catalogue-browser.js?v=14" defer></script>',
        '<script src="/assets/catalogue-browser-entry.js?v=5" defer></script>',
        '<script src="/assets/workspace-shell.js?v=3" defer></script>',
        '<script src="/assets/collector-worlds.js?v=3" defer></script>',
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
        bootstrap_task: asyncio.Task | None = None
        linked_draft_task: asyncio.Task | None = None
        market_task: asyncio.Task | None = None
        maintenance_tasks=[]
        app.state.shopify_sync_wakeup = None
        from .catalogue_maintenance import run_loop
        for enabled,shopify in ((settings.catalogue_daily_refresh_enabled,False),(settings.shopify_auto_sync_enabled,True)):
            if enabled and settings.catalogue_maintenance_actor_user_id:
                wakeup = asyncio.Event() if shopify else None
                if shopify:app.state.shopify_sync_wakeup = wakeup
                maintenance_tasks.append(asyncio.create_task(run_loop(app.state.db_pool,settings,shopify=shopify,wakeup=wakeup)))
            elif enabled:
                logger.error('Catalogue maintenance requires an authorised actor')
        if settings.ebay_market_refresh_enabled:
            if not settings.trawl_api_key or not settings.ebay_market_refresh_actor_user_id:
                logger.error("Live eBay market refresh enabled without required provider/actor configuration")
            else:
                market_task = asyncio.create_task(run_live_market_refresh(app.state.db_pool, settings))
        shopify_config_complete = all(
            (
                settings.shopify_shop_domain,
                settings.shopify_client_id,
                settings.shopify_client_secret,
                settings.shopify_location_gid,
                settings.shopify_publication_gid,
                settings.shopify_catalogue_bootstrap_actor_user_id,
            )
        )
        logger.warning(
            "Shopify catalogue bootstrap startup: enabled=%s config_complete=%s",
            settings.shopify_catalogue_bootstrap_enabled,
            shopify_config_complete,
        )
        if settings.shopify_catalogue_bootstrap_enabled:
            bootstrap_task = asyncio.create_task(
                run_shopify_catalogue_bootstrap(app.state.db_pool, settings)
            )

            def _bootstrap_done(task: asyncio.Task) -> None:
                if task.cancelled():
                    logger.warning("Shopify catalogue bootstrap task was cancelled")
                    return
                try:
                    result = task.result()
                except Exception:
                    logger.exception("Shopify catalogue bootstrap task failed")
                else:
                    logger.warning(
                        "Shopify catalogue bootstrap task finished: %s",
                        result,
                    )

            bootstrap_task.add_done_callback(_bootstrap_done)
            app.state.shopify_catalogue_bootstrap_task = bootstrap_task

        if settings.shopify_linked_draft_reconciliation_enabled:
            linked_draft_task = asyncio.create_task(
                run_linked_draft_reconciliation(app.state.db_pool, settings)
            )

            def _linked_draft_done(task: asyncio.Task) -> None:
                if task.cancelled():
                    logger.warning("Shopify linked-draft reconciliation was cancelled")
                    return
                try:
                    result = task.result()
                except Exception:
                    logger.exception("Shopify linked-draft reconciliation failed")
                else:
                    logger.warning(
                        "Shopify linked-draft reconciliation finished: %s",
                        result,
                    )

            linked_draft_task.add_done_callback(_linked_draft_done)
            app.state.shopify_linked_draft_reconciliation_task = linked_draft_task
        try:
            yield
        finally:
            for task in (bootstrap_task, linked_draft_task, market_task,*maintenance_tasks):
                if task is not None and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                elif task is not None:
                    try:
                        task.result()
                    except Exception:
                        pass
            await close_shared_vision_http_client()
            await close_artwork_tasks()
            await close_reference_http_client()
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
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob: https://assets.tcgdex.net https://onepiece-cardgame.com https://www.onepiece-cardgame.com https://*.onepiece-cardgame.com https://www.dbs-cardgame.com https://narutocardgame.gg https://cardtrader.com https://www.cardtrader.com https://upload.wikimedia.org https://images.prismic.io https://cdn.shopify.com https://*.shopifycdn.com https://*.shopifycdn.net; "
            f"connect-src 'self' {settings.supabase_url}; "
            "font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.get("/app", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(_dashboard_html())

    @app.get("/join", include_in_schema=False)
    async def founder_join() -> HTMLResponse:
        return HTMLResponse((STATIC_DIR / "join.html").read_text(encoding="utf-8"))

    @app.get("/owner", include_in_schema=False)
    async def owner_portal() -> HTMLResponse:
        return HTMLResponse((STATIC_DIR / "owner.html").read_text(encoding="utf-8"))

    @app.get("/owner/join", include_in_schema=False)
    async def owner_join() -> HTMLResponse:
        return HTMLResponse((STATIC_DIR / "owner-join.html").read_text(encoding="utf-8"))

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
    app.include_router(founder_accounts_router)
    app.include_router(seller_channel_sync_router)
    app.include_router(owner_inventory_router)
    app.include_router(action_required_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(automation_control_router)
    app.include_router(automation_commands_router)
    app.include_router(automation_recovery_router)
    app.include_router(finance_router)
    app.include_router(founder_onboarding_router)
    app.include_router(grading_certificates_router)
    app.include_router(free_canonical_media_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(collectible_identity_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(ebay_privacy_router)
    app.include_router(ebay_sales_router)
    app.include_router(ebay_oauth_router)
    app.include_router(refunds_router)
    app.include_router(pricing_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(payout_preferences_router)
    app.include_router(owner_login_router)
    app.include_router(owner_portal_api_router)
    app.include_router(owner_portal_finance_router)
    app.include_router(owner_onboarding_router)
    app.include_router(imported_benchmark_pricing_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(ebay_sold_pricing_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(pricing_preview_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(market_ingestion_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(market_mappings_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(marketplace_listings_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(market_discovery_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(market_provider_probe_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(market_smoke_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(imports_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(import_enrichment_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(import_review_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(inventory_intake_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(inventory_intelligence_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(inventory_market_values_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(inventory_state_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(inventory_sale_intent_router)
    app.include_router(identity_review_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(recognition_router)
    app.include_router(reference_library_router)
    app.include_router(catalogue_browser_router)
    app.include_router(condition_review_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(competitive_intelligence_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(competitive_intelligence_automation_router)
    app.include_router(shopify_router)
    app.include_router(shopify_pipeline_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(shopify_pooling_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(shopify_published_pooling_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(shopify_readiness_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(purchase_lots_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(storage_locations_router, dependencies=[Depends(require_platform_admin_request)])
    app.include_router(stripe_connect_router)
    app.include_router(tcggraph_media_router, dependencies=[Depends(require_platform_admin_request)])
    return app
