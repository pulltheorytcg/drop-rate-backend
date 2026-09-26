from __future__ import annotations

import asyncio
import hashlib
import html
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ebay_sell_client import (
    REQUIRED_SELLER_SCOPES,
    EbaySellApiError,
    EbaySellClient,
    exchange_authorization_code,
)
from .ebay_seller_connection import (
    encrypt_refresh_token,
    load_effective_seller_config,
    seller_client,
)
from .ownership import current_owner as _owner
from .settings import Settings, get_settings


router = APIRouter(prefix="/api/v1/ebay/oauth", tags=["ebay-oauth"])
AUTHORIZE_URL = "https://auth.ebay.com/oauth2/authorize"
STATE_TTL_MINUTES = 10
SELLING_POLICY_MANAGEMENT = "SELLING_POLICY_MANAGEMENT"


class SellerConfigSelection(BaseModel):
    payment_policy_id: str = Field(min_length=1, max_length=128)
    fulfillment_policy_id: str = Field(min_length=1, max_length=128)
    return_policy_id: str = Field(min_length=1, max_length=128)
    merchant_location_key: str = Field(min_length=1, max_length=50)


def _oauth_missing(settings: Settings) -> list[str]:
    required = {
        "TCG_EBAY_CLIENT_ID": settings.ebay_client_id,
        "TCG_EBAY_CLIENT_SECRET": settings.ebay_client_secret,
        "TCG_EBAY_RUNAME": settings.ebay_runame,
        "TCG_EBAY_OAUTH_CALLBACK_ENDPOINT": settings.ebay_oauth_callback_endpoint,
        "TCG_EBAY_OAUTH_ENCRYPTION_KEY": settings.ebay_oauth_encryption_key,
    }
    return [name for name, value in required.items() if not value]


def _safe_html(title: str, message: str, *, ok: bool) -> HTMLResponse:
    colour = "#15966b" if ok else "#a83a3a"
    status = 200 if ok else 400
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#071b3f;color:#eef7ff;margin:0;display:grid;min-height:100vh;place-items:center}}
main{{max-width:620px;margin:24px;padding:28px;border:1px solid #23446f;border-radius:20px;background:#0d274f;box-shadow:0 20px 60px #0005}}
h1{{margin:0 0 12px;font-size:1.65rem}}p{{line-height:1.55;color:#c7d8ec}}.state{{color:{colour};font-weight:800}}
</style></head><body><main><p class="state">{'CONNECTED' if ok else 'ACTION REQUIRED'}</p>
<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>
<p>You can close this tab and return to Drop Rate Founder HQ.</p></main></body></html>"""
    return HTMLResponse(body, status_code=status)


def _normalise_location_status(row: dict[str, Any]) -> str:
    return str(
        row.get("merchantLocationStatus")
        or row.get("locationStatus")
        or "ENABLED"
    ).upper()


def _policy_id(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _location_key(row: dict[str, Any]) -> str:
    return str(row.get("merchantLocationKey") or "").strip()


def _program_type(row: dict[str, Any]) -> str:
    return str(row.get("programType") or row.get("programTypeEnum") or "").strip()


async def _ensure_selling_policy_management(client: EbaySellClient) -> bool:
    """Ensure Inventory API business policies are enabled for this seller."""

    programs = await client.get_opted_in_programs()
    if any(_program_type(row) == SELLING_POLICY_MANAGEMENT for row in programs):
        return False
    await client.opt_in_to_program(SELLING_POLICY_MANAGEMENT)
    programs = await client.get_opted_in_programs()
    if not any(_program_type(row) == SELLING_POLICY_MANAGEMENT for row in programs):
        raise EbaySellApiError(
            "eBay did not confirm Selling Policy Management opt-in"
        )
    return True


async def _capture_option_call(
    label: str,
    call: Any,
) -> tuple[str, list[dict[str, Any]], str | None]:
    try:
        rows = await call
    except (EbaySellApiError, RuntimeError, ValueError) as exc:
        status = getattr(exc, "status_code", None)
        code = f"{label.upper()}_HTTP_{status}" if status else f"{label.upper()}_ERROR"
        return label, [], code
    return label, rows, None


async def _discover_seller_options(client: EbaySellClient) -> dict[str, Any]:
    errors: dict[str, str] = {}
    opted_in = False
    try:
        opted_in = await _ensure_selling_policy_management(client)
    except (EbaySellApiError, RuntimeError, ValueError) as exc:
        status = getattr(exc, "status_code", None)
        errors["selling_policy_management"] = (
            f"SELLING_POLICY_MANAGEMENT_HTTP_{status}"
            if status else "SELLING_POLICY_MANAGEMENT_ERROR"
        )

    results = await asyncio.gather(
        _capture_option_call("payment", client.get_payment_policies()),
        _capture_option_call("fulfillment", client.get_fulfillment_policies()),
        _capture_option_call("return", client.get_return_policies()),
        _capture_option_call("locations", client.get_inventory_locations()),
    )
    discovered: dict[str, list[dict[str, Any]]] = {
        "payment": [],
        "fulfillment": [],
        "return": [],
        "locations": [],
    }
    for label, rows, error_code in results:
        discovered[label] = rows
        if error_code:
            errors[label] = error_code

    payments = [
        row for row in discovered["payment"]
        if row.get("marketplaceId") in {None, client.marketplace_id}
        and row.get("immediatePay") is True
        and _policy_id(row, "paymentPolicyId")
    ]
    fulfillment = [
        row for row in discovered["fulfillment"]
        if row.get("marketplaceId") in {None, client.marketplace_id}
        and _policy_id(row, "fulfillmentPolicyId")
    ]
    returns = [
        row for row in discovered["return"]
        if row.get("marketplaceId") in {None, client.marketplace_id}
        and _policy_id(row, "returnPolicyId")
    ]
    locations = [
        row for row in discovered["locations"]
        if _location_key(row) and _normalise_location_status(row) == "ENABLED"
    ]
    return {
        "payment": payments,
        "fulfillment": fulfillment,
        "return": returns,
        "locations": locations,
        "errors": errors,
        "selling_policy_management_opted_in_now": opted_in,
    }


def _single_option(values: list[dict[str, Any]], key: str) -> str | None:
    if len(values) != 1:
        return None
    value = str(values[0].get(key) or "").strip()
    return value or None


def _sanitise_policy(row: dict[str, Any], id_key: str) -> dict[str, Any]:
    return {
        "id": str(row.get(id_key) or ""),
        "name": str(row.get("name") or row.get(id_key) or ""),
        "marketplace_id": row.get("marketplaceId"),
        "immediate_pay": row.get("immediatePay") if id_key == "paymentPolicyId" else None,
    }


def _sanitise_location(row: dict[str, Any]) -> dict[str, Any]:
    location = row.get("location")
    address = location.get("address") if isinstance(location, dict) else None
    return {
        "key": _location_key(row),
        "name": str(row.get("name") or _location_key(row)),
        "status": _normalise_location_status(row),
        "postal_code": address.get("postalCode") if isinstance(address, dict) else None,
        "country": address.get("country") if isinstance(address, dict) else None,
    }


async def _persist_seller_connection(
    pool: Any,
    *,
    attempt: Any,
    settings: Settings,
    encrypted_refresh_token: str,
    scopes: list[str],
    status: str,
    payment_policy_id: str | None = None,
    fulfillment_policy_id: str | None = None,
    return_policy_id: str | None = None,
    merchant_location_key: str | None = None,
    last_error_code: str | None = None,
) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            "select set_config('tcg.user_id',$1,true)",
            str(attempt["user_id"]),
        )
        await connection.execute(
            "select set_config('tcg.request_id',$1,true)",
            f"ebay-oauth:{attempt['id']}",
        )
        await connection.execute(
            """
            insert into tcg.ebay_seller_connections(
                owner_id,created_by_user_id,marketplace_id,
                refresh_token_ciphertext,granted_scopes,status,
                payment_policy_id,fulfillment_policy_id,return_policy_id,
                merchant_location_key,last_verified_at,last_error_code
            ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,clock_timestamp(),$11)
            on conflict (owner_id) do update
            set refresh_token_ciphertext=excluded.refresh_token_ciphertext,
                granted_scopes=excluded.granted_scopes,
                status=excluded.status,
                payment_policy_id=excluded.payment_policy_id,
                fulfillment_policy_id=excluded.fulfillment_policy_id,
                return_policy_id=excluded.return_policy_id,
                merchant_location_key=excluded.merchant_location_key,
                last_verified_at=clock_timestamp(),
                last_error_code=excluded.last_error_code,
                connected_at=clock_timestamp(),
                version=tcg.ebay_seller_connections.version+1,
                updated_at=clock_timestamp()
            """,
            attempt["owner_id"],
            attempt["user_id"],
            settings.ebay_marketplace_id,
            encrypted_refresh_token,
            scopes,
            status,
            payment_policy_id,
            fulfillment_policy_id,
            return_policy_id,
            merchant_location_key,
            last_error_code,
        )


@router.get("/status")
async def ebay_oauth_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    settings = get_settings()
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        row = await connection.fetchrow(
            """
            select id,status,granted_scopes,payment_policy_id,fulfillment_policy_id,
                   return_policy_id,merchant_location_key,notification_destination_id,
                   notification_subscription_id,connected_at,last_verified_at,
                   last_error_code,version
            from tcg.ebay_seller_connections
            where owner_id=$1
            """,
            owner["id"],
        )
    missing = _oauth_missing(settings)
    return {
        "oauth_configured": not missing,
        "missing": missing,
        "runame_configured": bool(settings.ebay_runame),
        "callback_endpoint": settings.ebay_oauth_callback_endpoint,
        "connected": row is not None and row["status"] != "DISCONNECTED",
        "connection": dict(row) if row else None,
        "publish_enabled": settings.ebay_publish_enabled,
    }


@router.post("/start")
async def start_ebay_oauth(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, str]:
    settings = get_settings()
    missing = _oauth_missing(settings)
    if missing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "eBay seller OAuth is not ready to start",
                "missing": missing,
                "callback_endpoint": settings.ebay_oauth_callback_endpoint,
            },
        )

    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)

    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        await connection.execute(
            "delete from tcg.ebay_oauth_attempts where expires_at < clock_timestamp()"
        )
        await connection.execute(
            """
            insert into tcg.ebay_oauth_attempts(
                owner_id,user_id,state_sha256,expires_at
            ) values ($1,$2,$3,$4)
            """,
            owner["id"], user.user_id, state_hash, expires_at,
        )

    query = urlencode({
        "client_id": settings.ebay_client_id,
        "redirect_uri": settings.ebay_runame,
        "response_type": "code",
        "scope": " ".join(REQUIRED_SELLER_SCOPES),
        "state": state,
        "prompt": "login",
        "locale": "en-GB",
    })
    return {"authorization_url": f"{AUTHORIZE_URL}?{query}"}


@router.get("/callback", response_class=HTMLResponse)
async def ebay_oauth_callback(
    request: Request,
    state: str = Query(min_length=20, max_length=256),
    code: str | None = Query(default=None, max_length=2048),
    error: str | None = Query(default=None, max_length=256),
    error_description: str | None = Query(default=None, max_length=1000),
) -> HTMLResponse:
    settings = get_settings()
    missing = _oauth_missing(settings)
    if missing:
        return _safe_html(
            "eBay connection could not finish",
            "Drop Rate's eBay OAuth callback is not fully configured.",
            ok=False,
        )

    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    async with request.app.state.db_pool.acquire() as connection:
        async with connection.transaction():
            attempt = await connection.fetchrow(
                """
                select id,owner_id,user_id
                from tcg.ebay_oauth_attempts
                where state_sha256=$1
                  and consumed_at is null
                  and expires_at > clock_timestamp()
                for update
                """,
                state_hash,
            )
            if attempt is None:
                return _safe_html(
                    "This eBay connection link is no longer valid",
                    "Start the eBay connection again from Founder HQ.",
                    ok=False,
                )
            await connection.execute(
                """
                update tcg.ebay_oauth_attempts
                set consumed_at=clock_timestamp()
                where id=$1
                """,
                attempt["id"],
            )

    if error or not code:
        description = error_description or error or "The seller did not grant access."
        return _safe_html(
            "eBay access was not granted",
            description[:500],
            ok=False,
        )

    try:
        token_data = await exchange_authorization_code(
            client_id=settings.ebay_client_id or "",
            client_secret=settings.ebay_client_secret or "",
            code=code,
            redirect_uri=settings.ebay_runame or "",
        )
        refresh_token = str(token_data["refresh_token"])
        seller = EbaySellClient(
            client_id=settings.ebay_client_id or "",
            client_secret=settings.ebay_client_secret or "",
            refresh_token=refresh_token,
            marketplace_id=settings.ebay_marketplace_id,
        )
        await seller.user_access_token()
        scopes = sorted(seller.granted_scopes)
        required = set(REQUIRED_SELLER_SCOPES)
        if not required.issubset(set(scopes)):
            raise EbaySellApiError(
                "The eBay seller consent did not include every required scope"
            )
        encrypted = encrypt_refresh_token(settings, refresh_token)
    except (EbaySellApiError, RuntimeError, ValueError) as exc:
        return _safe_html(
            "eBay connection could not be verified",
            str(getattr(exc, "detail", str(exc)))[:500],
            ok=False,
        )

    # Consent succeeded. Persist the encrypted long-lived grant before any
    # optional seller-account discovery so a downstream policy/location error
    # never throws away a valid seller connection.
    await _persist_seller_connection(
        request.app.state.db_pool,
        attempt=attempt,
        settings=settings,
        encrypted_refresh_token=encrypted,
        scopes=scopes,
        status="CONNECTED",
    )

    options = await _discover_seller_options(seller)
    payment_id = _single_option(options["payment"], "paymentPolicyId")
    fulfillment_id = _single_option(options["fulfillment"], "fulfillmentPolicyId")
    return_id = _single_option(options["return"], "returnPolicyId")
    location_key = _single_option(options["locations"], "merchantLocationKey")
    discovery_errors = dict(options.get("errors") or {})
    ready_config = (
        not discovery_errors
        and all((payment_id, fulfillment_id, return_id, location_key))
    )
    if ready_config:
        status = "CONNECTED"
        last_error = None
    elif discovery_errors:
        status = "ACTION_REQUIRED"
        last_error = "SELLER_CONFIGURATION_DISCOVERY_INCOMPLETE"
    else:
        status = "ACTION_REQUIRED"
        last_error = "SELLER_CONFIGURATION_SELECTION_REQUIRED"

    await _persist_seller_connection(
        request.app.state.db_pool,
        attempt=attempt,
        settings=settings,
        encrypted_refresh_token=encrypted,
        scopes=scopes,
        status=status,
        payment_policy_id=payment_id,
        fulfillment_policy_id=fulfillment_id,
        return_policy_id=return_id,
        merchant_location_key=location_key,
        last_error_code=last_error,
    )

    if ready_config:
        message = (
            "Your seller account is connected. Drop Rate also found one compatible "
            "payment, fulfilment and return policy plus one enabled inventory location."
        )
    elif discovery_errors:
        message = (
            "Your seller account is securely connected. eBay accepted the seller grant, "
            "but one or more seller-policy or inventory-location checks still need "
            "attention in Founder HQ before publishing."
        )
    else:
        message = (
            "Your seller account is securely connected. Drop Rate found multiple or "
            "missing seller policies/locations, so choose the correct ones in Founder HQ "
            "before publishing."
        )
    return _safe_html("eBay seller account connected", message, ok=True)


@router.get("/options")
async def ebay_seller_options(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    settings = get_settings()
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
    try:
        client, effective = await seller_client(
            request.app.state.db_pool, settings, owner_id=owner["id"]
        )
        options = await _discover_seller_options(client)
    except (EbaySellApiError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail=str(getattr(exc, "detail", str(exc))),
        ) from exc
    return {
        "selected": {
            "payment_policy_id": effective.payment_policy_id,
            "fulfillment_policy_id": effective.fulfillment_policy_id,
            "return_policy_id": effective.return_policy_id,
            "merchant_location_key": effective.merchant_location_key,
        },
        "payment": [
            _sanitise_policy(row, "paymentPolicyId") for row in options["payment"]
        ],
        "fulfillment": [
            _sanitise_policy(row, "fulfillmentPolicyId")
            for row in options["fulfillment"]
        ],
        "return": [
            _sanitise_policy(row, "returnPolicyId") for row in options["return"]
        ],
        "locations": [_sanitise_location(row) for row in options["locations"]],
        "errors": dict(options.get("errors") or {}),
        "selling_policy_management_opted_in_now": bool(
            options.get("selling_policy_management_opted_in_now")
        ),
    }


@router.post("/configuration")
async def save_ebay_seller_configuration(
    payload: SellerConfigSelection,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    settings = get_settings()
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
    try:
        client, _ = await seller_client(
            request.app.state.db_pool, settings, owner_id=owner["id"]
        )
        options = await _discover_seller_options(client)
    except (EbaySellApiError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail=str(getattr(exc, "detail", str(exc))),
        ) from exc

    discovery_errors = dict(options.get("errors") or {})
    if discovery_errors:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "eBay seller configuration is still incomplete",
                "errors": discovery_errors,
            },
        )

    valid_payment = {
        _policy_id(row, "paymentPolicyId") for row in options["payment"]
    }
    valid_fulfillment = {
        _policy_id(row, "fulfillmentPolicyId") for row in options["fulfillment"]
    }
    valid_return = {
        _policy_id(row, "returnPolicyId") for row in options["return"]
    }
    valid_locations = {_location_key(row) for row in options["locations"]}

    invalid: list[str] = []
    if payload.payment_policy_id not in valid_payment:
        invalid.append("payment policy")
    if payload.fulfillment_policy_id not in valid_fulfillment:
        invalid.append("fulfilment policy")
    if payload.return_policy_id not in valid_return:
        invalid.append("return policy")
    if payload.merchant_location_key not in valid_locations:
        invalid.append("inventory location")
    if invalid:
        raise HTTPException(
            status_code=409,
            detail=f"Selected eBay {' / '.join(invalid)} is not valid for EBAY_GB",
        )

    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        row = await connection.fetchrow(
            """
            update tcg.ebay_seller_connections
            set payment_policy_id=$2,fulfillment_policy_id=$3,return_policy_id=$4,
                merchant_location_key=$5,status='CONNECTED',last_error_code=null,
                last_verified_at=clock_timestamp(),version=version+1,
                updated_at=clock_timestamp()
            where owner_id=$1 and status <> 'DISCONNECTED'
            returning id,status,payment_policy_id,fulfillment_policy_id,
                      return_policy_id,merchant_location_key,version
            """,
            owner["id"], payload.payment_policy_id, payload.fulfillment_policy_id,
            payload.return_policy_id, payload.merchant_location_key,
        )
        if row is None:
            raise HTTPException(status_code=409, detail="Connect the eBay seller account first")
    return dict(row)
