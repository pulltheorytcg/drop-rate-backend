from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .settings import get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError


router = APIRouter(prefix="/api/v1/shopify", tags=["shopify"])

MAX_WEBHOOK_BODY_BYTES = 2_000_000
INITIAL_WEBHOOK_TOPICS = frozenset(
    {
        "orders/paid",
        "orders/cancelled",
        "refunds/create",
        "app/uninstalled",
    }
)


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
    if not settings.shopify_shop_domain or not settings.shopify_access_token:
        raise HTTPException(
            status_code=409,
            detail="Shopify Admin API connection is not configured",
        )
    return ShopifyAdminClient(
        shop_domain=settings.shopify_shop_domain,
        access_token=settings.shopify_access_token,
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
        and settings.shopify_access_token
        and settings.shopify_client_secret
    )
    return jsonable_encoder(
        {
            "configured": configured,
            "shop_domain": settings.shopify_shop_domain,
            "api_version": settings.shopify_api_version,
            "admin_api_configured": bool(
                settings.shopify_shop_domain and settings.shopify_access_token
            ),
            "webhook_secret_configured": bool(settings.shopify_client_secret),
            "publish_enabled": settings.shopify_publish_enabled,
            "webhook_path": "/api/v1/shopify/webhooks",
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


@router.post("/webhooks")
async def shopify_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(
        default=None,
        alias="X-Shopify-Hmac-Sha256",
    ),
    x_shopify_webhook_id: str | None = Header(
        default=None,
        alias="X-Shopify-Webhook-Id",
    ),
    x_shopify_topic: str | None = Header(default=None, alias="X-Shopify-Topic"),
    x_shopify_shop_domain: str | None = Header(
        default=None,
        alias="X-Shopify-Shop-Domain",
    ),
    x_shopify_api_version: str | None = Header(
        default=None,
        alias="X-Shopify-Api-Version",
    ),
    x_shopify_triggered_at: str | None = Header(
        default=None,
        alias="X-Shopify-Triggered-At",
    ),
    x_shopify_event_id: str | None = Header(
        default=None,
        alias="X-Shopify-Event-Id",
    ),
) -> JSONResponse:
    settings = get_settings()
    if not settings.shopify_client_secret or not settings.shopify_shop_domain:
        raise HTTPException(
            status_code=503,
            detail="Shopify webhook verification is not configured",
        )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_WEBHOOK_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Shopify webhook body is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")

    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Shopify webhook body is too large")

    if not verify_shopify_hmac(
        raw_body,
        x_shopify_hmac_sha256,
        settings.shopify_client_secret,
    ):
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

    status = "RECEIVED" if topic in INITIAL_WEBHOOK_TOPICS else "IGNORED"
    payload_sha256 = hashlib.sha256(raw_body).hexdigest()

    async with request.app.state.db_pool.acquire() as connection:
        async with connection.transaction():
            inserted = await connection.fetchrow(
                """
                insert into tcg.shopify_webhook_events(
                    webhook_id, event_id, topic, shop_domain, api_version,
                    triggered_at, resource_id, payload_sha256, status,
                    processed_at
                ) values(
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,
                    case when $9='IGNORED' then clock_timestamp() else null end
                )
                on conflict(webhook_id) do nothing
                returning id,status,received_at
                """,
                webhook_id,
                (x_shopify_event_id or "").strip() or None,
                topic,
                shop_domain,
                (x_shopify_api_version or "").strip() or None,
                triggered_at,
                _resource_id(payload),
                payload_sha256,
                status,
            )
            if inserted is None:
                existing = await connection.fetchrow(
                    """
                    select id,status,received_at
                    from tcg.shopify_webhook_events
                    where webhook_id=$1
                    """,
                    webhook_id,
                )
                return JSONResponse(
                    status_code=200,
                    content=jsonable_encoder(
                        {
                            "received": True,
                            "duplicate": True,
                            "status": existing["status"] if existing else "RECEIVED",
                        }
                    ),
                )

    return JSONResponse(
        status_code=200,
        content=jsonable_encoder(
            {
                "received": True,
                "duplicate": False,
                "status": status,
            }
        ),
    )
