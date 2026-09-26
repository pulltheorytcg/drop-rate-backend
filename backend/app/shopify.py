from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ebay_sales import sync_ebay_after_shopify_result
from .ebay_sell_client import EbaySellApiError
from .ownership import current_owner as _owner
from .settings import get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError
from .shopify_pipeline import ShopifyProcessingError, process_shopify_webhook


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/shopify", tags=["shopify"])

MAX_WEBHOOK_BODY_BYTES = 2_000_000
INITIAL_WEBHOOK_TOPICS = frozenset(
    {
        "orders/create",
        "orders/paid",
        "orders/cancelled",
        "refunds/create",
        "app/uninstalled",
    }
)
SHOPIFY_WEBHOOK_TOPIC_ENUMS = {
    "orders/create": "ORDERS_CREATE",
    "orders/paid": "ORDERS_PAID",
    "orders/cancelled": "ORDERS_CANCELLED",
    "refunds/create": "REFUNDS_CREATE",
    "app/uninstalled": "APP_UNINSTALLED",
}



def plan_webhook_registration(
    existing: list[dict[str, Any]],
    endpoint: str,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]], list[dict[str, Any]]]:
    present: list[dict[str, Any]] = []
    missing: list[tuple[str, str]] = []
    conflicts: list[dict[str, Any]] = []

    for rest_topic, enum_topic in SHOPIFY_WEBHOOK_TOPIC_ENUMS.items():
        topic_subscriptions = [
            subscription
            for subscription in existing
            if subscription.get("topic") == enum_topic
        ]
        exact = [
            subscription
            for subscription in topic_subscriptions
            if str(subscription.get("uri") or "").rstrip("/") == endpoint
        ]

        if len(topic_subscriptions) == 0:
            missing.append((rest_topic, enum_topic))
            continue
        if len(topic_subscriptions) == 1 and len(exact) == 1:
            present.append(
                {
                    "topic": rest_topic,
                    "shopify_topic": enum_topic,
                    "subscription_id": exact[0].get("id"),
                    "uri": endpoint,
                    "state": "EXISTING",
                }
            )
            continue

        conflicts.append(
            {
                "topic": rest_topic,
                "shopify_topic": enum_topic,
                "existing": [
                    {
                        "subscription_id": subscription.get("id"),
                        "uri": subscription.get("uri"),
                    }
                    for subscription in topic_subscriptions
                ],
            }
        )

    return present, missing, conflicts


def verify_shopify_hmac(raw_body: bytes, header_value: str | None, secret: str) -> bool:
    if not raw_body or not header_value or not secret:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, header_value.strip())


def _parse_triggered_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Shopify webhook triggered-at header",
        ) from exc
    if parsed.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail="Shopify webhook triggered-at must include a timezone",
        )
    return parsed


def _resource_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("id", "order_id", "admin_graphql_api_id"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()[:255]
    return None


def _shopify_client() -> ShopifyAdminClient:
    settings = get_settings()
    if (
        not settings.shopify_shop_domain
        or not settings.shopify_client_id
        or not settings.shopify_client_secret
    ):
        raise HTTPException(
            status_code=409,
            detail="Shopify Admin API connection is not configured",
        )
    return ShopifyAdminClient(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        api_version=settings.shopify_api_version,
    )


@router.get("/status")
async def shopify_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        delivery = await connection.fetchrow(
            """
            select
                count(*)::int as total_deliveries,
                count(*) filter(where status='RECEIVED')::int as received,
                count(*) filter(where status='PROCESSED')::int as processed,
                count(*) filter(where status='IGNORED')::int as ignored,
                count(*) filter(where status='FAILED')::int as failed,
                max(received_at) as last_received_at
            from tcg.shopify_webhook_events
            """
        )
    configured = bool(
        settings.shopify_shop_domain
        and settings.shopify_client_id
        and settings.shopify_client_secret
    )
    return jsonable_encoder(
        {
            "configured": configured,
            "shop_domain": settings.shopify_shop_domain,
            "api_version": settings.shopify_api_version,
            "admin_api_configured": bool(
                settings.shopify_shop_domain
                and settings.shopify_client_id
                and settings.shopify_client_secret
            ),
            "webhook_secret_configured": bool(settings.shopify_client_secret),
            "webhook_endpoint_configured": bool(settings.shopify_webhook_endpoint),
            "webhook_registration_ready": bool(
                configured and settings.shopify_webhook_endpoint
            ),
            "publish_enabled": settings.shopify_publish_enabled,
            "webhook_path": "/api/v1/shopify/webhooks",
            "webhook_endpoint": settings.shopify_webhook_endpoint,
            "webhook_topics": sorted(INITIAL_WEBHOOK_TOPICS),
            "deliveries": dict(delivery),
        }
    )


@router.post("/probe")
async def probe_shopify(
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    client = _shopify_client()
    try:
        shop = await client.probe_shop()
    except ShopifyApiError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": exc.detail,
                "retryable": exc.retryable,
                "provider_status": exc.status_code,
            },
        ) from exc

    settings = get_settings()
    returned_domain = str(shop.get("myshopify_domain") or "").casefold()
    if returned_domain and returned_domain != settings.shopify_shop_domain:
        raise HTTPException(
            status_code=409,
            detail="Shopify Admin API returned a different shop domain",
        )
    return jsonable_encoder(
        {
            "status": "SUCCEEDED",
            "shop": shop,
            "api_version": client.api_version,
            "publish_enabled": settings.shopify_publish_enabled,
        }
    )


@router.post("/webhooks/register")
async def register_shopify_webhooks(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    endpoint = settings.shopify_webhook_endpoint
    if not endpoint:
        raise HTTPException(
            status_code=409,
            detail="Shopify webhook endpoint is not configured",
        )

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        if owner["role"] != "FOUNDER":
            raise HTTPException(
                status_code=403,
                detail="Only a founder can change Shopify webhook registration",
            )

    client = _shopify_client()
    try:
        shop = await client.probe_shop()
        returned_domain = str(shop.get("myshopify_domain") or "").casefold()
        if returned_domain != settings.shopify_shop_domain:
            raise HTTPException(
                status_code=409,
                detail="Shopify Admin API returned a different shop domain",
            )

        existing = await client.list_webhook_subscriptions()
        present, missing, conflicts = plan_webhook_registration(existing, endpoint)

        if conflicts:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Shopify has conflicting webhook subscriptions. "
                        "No new subscriptions were created."
                    ),
                    "conflicts": conflicts,
                },
            )

        created: list[dict[str, Any]] = []
        for rest_topic, enum_topic in missing:
            subscription = await client.create_webhook_subscription(
                topic=enum_topic,
                uri=endpoint,
            )
            created.append(
                {
                    "topic": rest_topic,
                    "shopify_topic": enum_topic,
                    "subscription_id": subscription.get("id"),
                    "uri": subscription.get("uri"),
                    "state": "CREATED",
                }
            )

        verified = await client.list_webhook_subscriptions()
        verification: list[dict[str, Any]] = []
        for rest_topic, enum_topic in SHOPIFY_WEBHOOK_TOPIC_ENUMS.items():
            exact = [
                subscription
                for subscription in verified
                if subscription.get("topic") == enum_topic
                and str(subscription.get("uri") or "").rstrip("/") == endpoint
            ]
            if len(exact) != 1:
                raise ShopifyApiError(
                    "Shopify webhook registration could not be verified"
                )
            verification.append(
                {
                    "topic": rest_topic,
                    "shopify_topic": enum_topic,
                    "subscription_id": exact[0].get("id"),
                    "uri": endpoint,
                    "state": "VERIFIED",
                }
            )

    except HTTPException:
        raise
    except ShopifyApiError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": exc.detail,
                "retryable": exc.retryable,
                "provider_status": exc.status_code,
                "created_before_failure": created if "created" in locals() else [],
            },
        ) from exc

    return jsonable_encoder(
        {
            "status": "SUCCEEDED",
            "shop": shop,
            "api_version": client.api_version,
            "publish_enabled": settings.shopify_publish_enabled,
            "endpoint": endpoint,
            "existing_count": len(present),
            "created_count": len(created),
            "subscriptions": verification,
        }
    )


@router.post("/webhooks")
async def shopify_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(default=None, alias="X-Shopify-Hmac-Sha256"),
    x_shopify_webhook_id: str | None = Header(default=None, alias="X-Shopify-Webhook-Id"),
    x_shopify_topic: str | None = Header(default=None, alias="X-Shopify-Topic"),
    x_shopify_shop_domain: str | None = Header(default=None, alias="X-Shopify-Shop-Domain"),
    x_shopify_api_version: str | None = Header(default=None, alias="X-Shopify-Api-Version"),
    x_shopify_triggered_at: str | None = Header(default=None, alias="X-Shopify-Triggered-At"),
    x_shopify_event_id: str | None = Header(default=None, alias="X-Shopify-Event-Id"),
) -> JSONResponse:
    settings = get_settings()
    if not settings.shopify_client_secret or not settings.shopify_shop_domain:
        raise HTTPException(status_code=503, detail="Shopify webhook verification is not configured")

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_WEBHOOK_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Shopify webhook body is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc

    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Shopify webhook body is too large")
    if not verify_shopify_hmac(raw_body, x_shopify_hmac_sha256, settings.shopify_client_secret):
        raise HTTPException(status_code=401, detail="Invalid Shopify webhook signature")

    shop_domain = (x_shopify_shop_domain or "").strip().casefold()
    if shop_domain != settings.shopify_shop_domain:
        raise HTTPException(status_code=401, detail="Shopify webhook shop domain mismatch")

    webhook_id = (x_shopify_webhook_id or "").strip()
    topic = (x_shopify_topic or "").strip().casefold()
    if not webhook_id or len(webhook_id) > 255:
        raise HTTPException(status_code=400, detail="Missing or invalid Shopify webhook ID")
    if not topic or len(topic) > 120:
        raise HTTPException(status_code=400, detail="Missing or invalid Shopify webhook topic")
    if x_shopify_event_id and len(x_shopify_event_id.strip()) > 255:
        raise HTTPException(status_code=400, detail="Invalid Shopify event ID")

    triggered_at = _parse_triggered_at(x_shopify_triggered_at)
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Shopify webhook body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Shopify webhook body must be a JSON object")

    initial_status = "RECEIVED" if topic in INITIAL_WEBHOOK_TOPICS else "IGNORED"
    payload_sha256 = hashlib.sha256(raw_body).hexdigest()

    async with request.app.state.db_pool.acquire() as connection:
        inserted = await connection.fetchrow(
            """
            insert into tcg.shopify_webhook_events(
                webhook_id,event_id,topic,shop_domain,api_version,triggered_at,
                resource_id,payload_sha256,status,processed_at
            ) values(
                $1,$2,$3,$4,$5,$6,$7,$8,$9,
                case when $9='IGNORED' then clock_timestamp() else null end
            )
            on conflict(webhook_id) do nothing
            returning id,status,payload_sha256
            """,
            webhook_id,
            (x_shopify_event_id or "").strip() or None,
            topic,
            shop_domain,
            (x_shopify_api_version or "").strip() or None,
            triggered_at,
            _resource_id(payload),
            payload_sha256,
            initial_status,
        )

        duplicate = inserted is None
        event = inserted
        if duplicate:
            event = await connection.fetchrow(
                """
                select id,status,payload_sha256
                from tcg.shopify_webhook_events
                where webhook_id=$1
                """,
                webhook_id,
            )
            if event is None:
                raise HTTPException(status_code=500, detail="Webhook deduplication state is missing")
            if event["payload_sha256"] != payload_sha256:
                raise HTTPException(status_code=409, detail="Webhook ID was reused with a different payload")
            if event["status"] in {"PROCESSED", "IGNORED"}:
                return JSONResponse(
                    status_code=200,
                    content=jsonable_encoder({
                        "received": True,
                        "duplicate": True,
                        "status": event["status"],
                    }),
                )

        if initial_status == "IGNORED":
            return JSONResponse(
                status_code=200,
                content=jsonable_encoder({
                    "received": True,
                    "duplicate": duplicate,
                    "status": "IGNORED",
                }),
            )

        try:
            async with connection.transaction():
                result = await process_shopify_webhook(
                    connection,
                    topic=topic,
                    payload=payload,
                    webhook_id=webhook_id,
                )
                next_status = result.get("status", "PROCESSED")
        except ShopifyProcessingError as exc:
            await connection.execute(
                """
                update tcg.shopify_webhook_events
                set status='FAILED',processed_at=clock_timestamp(),error_code=$2
                where id=$1
                """,
                event["id"], exc.code,
            )
            return JSONResponse(
                status_code=500,
                content={"received": True, "processed": False, "error_code": exc.code},
            )
        except ShopifyApiError:
            await connection.execute(
                """
                update tcg.shopify_webhook_events
                set status='FAILED',processed_at=clock_timestamp(),error_code='SHOPIFY_API_ERROR'
                where id=$1
                """,
                event["id"],
            )
            return JSONResponse(
                status_code=502,
                content={"received": True, "processed": False, "error_code": "SHOPIFY_API_ERROR"},
            )
        except Exception as exc:
            logger.exception(
                "Unexpected Shopify webhook processing failure",
                extra={
                    "shopify_webhook_id": webhook_id,
                    "shopify_topic": topic,
                    "shopify_resource_id": _resource_id(payload),
                    "exception_type": type(exc).__name__,
                },
            )
            await connection.execute(
                """
                update tcg.shopify_webhook_events
                set status='FAILED',processed_at=clock_timestamp(),error_code='UNEXPECTED_PROCESSING_ERROR'
                where id=$1
                """,
                event["id"],
            )
            return JSONResponse(
                status_code=500,
                content={"received": True, "processed": False, "error_code": "UNEXPECTED_PROCESSING_ERROR"},
            )

    # Cross-channel provider I/O deliberately runs after the database
    # transaction commits. A failed eBay withdrawal leaves this webhook FAILED,
    # so Shopify retries can complete the exact same idempotent cleanup path.
    try:
        await sync_ebay_after_shopify_result(request.app.state.db_pool, result)
    except EbaySellApiError as exc:
        logger.warning(
            "Shopify state committed but eBay cross-channel sync failed",
            extra={
                "shopify_webhook_id": webhook_id,
                "shopify_topic": topic,
                "retryable": exc.retryable,
                "provider_status": exc.status_code,
            },
        )
        async with request.app.state.db_pool.acquire() as connection:
            await connection.execute(
                """
                update tcg.shopify_webhook_events
                set status='FAILED',processed_at=clock_timestamp(),
                    error_code='CROSS_CHANNEL_EBAY_ERROR'
                where id=$1
                """,
                event["id"],
            )
        return JSONResponse(
            status_code=502,
            content={
                "received": True,
                "processed": False,
                "error_code": "CROSS_CHANNEL_EBAY_ERROR",
            },
        )

    async with request.app.state.db_pool.acquire() as connection:
        await connection.execute(
            """
            update tcg.shopify_webhook_events
            set status=$2,processed_at=clock_timestamp(),error_code=null
            where id=$1
            """,
            event["id"], next_status,
        )

    return JSONResponse(
        status_code=200,
        content=jsonable_encoder({
            "received": True,
            "duplicate": duplicate,
            "status": result.get("status", "PROCESSED"),
            "action": result.get("action"),
        }),
    )

