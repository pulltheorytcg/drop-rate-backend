from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner
from .settings import Settings, get_settings
from .stripe_connect_client import StripeApiError, StripeConnectClient


router = APIRouter(prefix="/api/v1/stripe")
WEBHOOK_TOLERANCE_SECONDS = 300


class PayoutReview(BaseModel):
    version: int = Field(ge=1)
    reason: str = Field(default="", max_length=1000)


def _client(settings: Settings) -> StripeConnectClient:
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=409, detail="Stripe Connect is not configured")
    return StripeConnectClient(secret_key=settings.stripe_secret_key)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _account_snapshot(account: dict[str, Any]) -> dict[str, Any]:
    requirements = account.get("requirements")
    if not isinstance(requirements, dict):
        requirements = {}
    capabilities = account.get("capabilities")
    if not isinstance(capabilities, dict):
        capabilities = {}

    transfers = str(capabilities.get("transfers") or "unrequested").upper()
    if transfers not in {"UNREQUESTED", "PENDING", "ACTIVE", "INACTIVE"}:
        transfers = "INACTIVE"

    currently_due = _string_list(requirements.get("currently_due"))
    eventually_due = _string_list(requirements.get("eventually_due"))
    past_due = _string_list(requirements.get("past_due"))
    disabled_reason = str(requirements.get("disabled_reason") or "").strip() or None
    details_submitted = bool(account.get("details_submitted"))
    payouts_enabled = bool(account.get("payouts_enabled"))

    if bool(account.get("deleted")):
        status = "DISCONNECTED"
    elif not details_submitted:
        status = "ONBOARDING"
    elif (
        payouts_enabled
        and transfers == "ACTIVE"
        and not currently_due
        and not past_due
        and not disabled_reason
    ):
        status = "READY"
    else:
        status = "RESTRICTED"

    return {
        "stripe_account_id": str(account.get("id") or "").strip(),
        "livemode": bool(account.get("livemode")),
        "country": str(account.get("country") or "").strip().upper() or None,
        "status": status,
        "details_submitted": details_submitted,
        "charges_enabled": bool(account.get("charges_enabled")),
        "payouts_enabled": payouts_enabled,
        "transfers_capability_status": transfers,
        "requirements_currently_due": currently_due,
        "requirements_eventually_due": eventually_due,
        "requirements_past_due": past_due,
        "disabled_reason": disabled_reason,
    }


async def _save_account_snapshot(
    connection: asyncpg.Connection,
    *,
    owner_id: UUID,
    account: dict[str, Any],
) -> dict[str, Any]:
    snapshot = _account_snapshot(account)
    row = await connection.fetchrow(
        """
        update tcg.stripe_connected_accounts
        set livemode=$3,
            country=$4,
            status=$5,
            details_submitted=$6,
            charges_enabled=$7,
            payouts_enabled=$8,
            transfers_capability_status=$9,
            requirements_currently_due=$10,
            requirements_eventually_due=$11,
            requirements_past_due=$12,
            disabled_reason=$13,
            last_error_code=null,
            last_synced_at=clock_timestamp(),
            version=version+1,
            updated_at=clock_timestamp()
        where owner_id=$1 and stripe_account_id=$2
        returning *
        """,
        owner_id,
        snapshot["stripe_account_id"],
        snapshot["livemode"],
        snapshot["country"],
        snapshot["status"],
        snapshot["details_submitted"],
        snapshot["charges_enabled"],
        snapshot["payouts_enabled"],
        snapshot["transfers_capability_status"],
        snapshot["requirements_currently_due"],
        snapshot["requirements_eventually_due"],
        snapshot["requirements_past_due"],
        snapshot["disabled_reason"],
    )
    if row is None:
        raise HTTPException(status_code=409, detail="Stripe account mapping changed")
    return dict(row)


def _readiness_blockers(row: dict[str, Any] | asyncpg.Record | None) -> list[str]:
    if row is None:
        return ["STRIPE_ACCOUNT_MISSING"]
    blockers: list[str] = []
    if str(row["status"]) != "READY":
        blockers.append("STRIPE_ACCOUNT_NOT_READY")
    if str(row["transfers_capability_status"]) != "ACTIVE":
        blockers.append("TRANSFERS_NOT_ACTIVE")
    if not bool(row["payouts_enabled"]):
        blockers.append("PAYOUTS_DISABLED")
    if row["requirements_currently_due"]:
        blockers.append("VERIFICATION_CURRENTLY_DUE")
    if row["requirements_past_due"]:
        blockers.append("VERIFICATION_PAST_DUE")
    return blockers


async def _require_founder_operator(
    request: Request,
    user: AuthenticatedUser,
) -> asyncpg.Record:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
    if owner["owner_type"] != "FOUNDER" or owner["role"] != "FOUNDER":
        raise HTTPException(status_code=403, detail="Founder approval is required")
    return owner


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    *,
    now: int | None = None,
) -> None:
    timestamp: int | None = None
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, separator, value = part.strip().partition("=")
        if not separator:
            continue
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                timestamp = None
        elif key == "v1" and value:
            signatures.append(value)

    if timestamp is None or not signatures:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature header")
    current = int(time.time()) if now is None else int(now)
    if abs(current - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
        raise HTTPException(status_code=400, detail="Stripe webhook signature is stale")

    signed_payload = str(timestamp).encode("ascii") + b"." + payload
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")


@router.get("/connect/status")
async def stripe_connect_status(
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
            select id,owner_id,stripe_account_id,livemode,account_type,country,status,
                   details_submitted,charges_enabled,payouts_enabled,
                   transfers_capability_status,requirements_currently_due,
                   requirements_eventually_due,requirements_past_due,
                   disabled_reason,last_error_code,last_synced_at,version
            from tcg.stripe_connected_accounts
            where owner_id=$1
            """,
            owner["id"],
        )
    blockers = _readiness_blockers(row)
    return jsonable_encoder({
        "configured": bool(settings.stripe_secret_key),
        "webhook_configured": bool(settings.stripe_webhook_secret),
        "connect_live_enabled": settings.stripe_connect_live_enabled,
        "payout_execution_enabled": settings.stripe_payout_execution_enabled,
        "connected": row is not None,
        "ready_for_payouts": row is not None and not blockers,
        "blockers": blockers,
        "account": dict(row) if row else None,
    })


@router.post("/connect/account", status_code=201)
async def create_or_sync_stripe_account(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    settings = get_settings()
    client = _client(settings)
    if client.key_livemode and not settings.stripe_connect_live_enabled:
        raise HTTPException(
            status_code=409,
            detail="Live Stripe connected-account creation is locked",
        )

    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        existing = await connection.fetchrow(
            "select * from tcg.stripe_connected_accounts where owner_id=$1",
            owner["id"],
        )

    if existing:
        try:
            account = await client.retrieve_account(str(existing["stripe_account_id"]))
        except StripeApiError as exc:
            raise HTTPException(
                status_code=502 if exc.retryable else 409,
                detail=exc.detail,
            ) from exc
        async with user_connection(
            request.app.state.db_pool, user.user_id, request.state.request_id
        ) as connection:
            await _owner(connection)
            saved = await _save_account_snapshot(
                connection,
                owner_id=owner["id"],
                account=account,
            )
        return jsonable_encoder({"account": saved, "created": False})

    try:
        account = await client.create_express_account(
            country=settings.stripe_connect_country,
            owner_id=str(owner["id"]),
        )
    except StripeApiError as exc:
        raise HTTPException(
            status_code=502 if exc.retryable else 409,
            detail=exc.detail,
        ) from exc

    snapshot = _account_snapshot(account)
    if not snapshot["stripe_account_id"].startswith("acct_"):
        raise HTTPException(status_code=502, detail="Stripe account response is invalid")

    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        await _owner(connection)
        try:
            row = await connection.fetchrow(
                """
                insert into tcg.stripe_connected_accounts(
                    owner_id,created_by_user_id,stripe_account_id,livemode,
                    country,status,details_submitted,charges_enabled,payouts_enabled,
                    transfers_capability_status,requirements_currently_due,
                    requirements_eventually_due,requirements_past_due,
                    disabled_reason,last_synced_at
                ) values (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,clock_timestamp()
                )
                returning *
                """,
                owner["id"],
                user.user_id,
                snapshot["stripe_account_id"],
                snapshot["livemode"],
                snapshot["country"],
                snapshot["status"],
                snapshot["details_submitted"],
                snapshot["charges_enabled"],
                snapshot["payouts_enabled"],
                snapshot["transfers_capability_status"],
                snapshot["requirements_currently_due"],
                snapshot["requirements_eventually_due"],
                snapshot["requirements_past_due"],
                snapshot["disabled_reason"],
            )
        except asyncpg.UniqueViolationError:
            row = await connection.fetchrow(
                "select * from tcg.stripe_connected_accounts where owner_id=$1",
                owner["id"],
            )
    return jsonable_encoder({"account": dict(row), "created": True})


@router.post("/connect/onboarding-link")
async def stripe_onboarding_link(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.stripe_connect_refresh_url or not settings.stripe_connect_return_url:
        raise HTTPException(
            status_code=409,
            detail="Stripe Connect return and refresh URLs are not configured",
        )
    client = _client(settings)
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        row = await connection.fetchrow(
            "select * from tcg.stripe_connected_accounts where owner_id=$1",
            owner["id"],
        )
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="Create the Stripe payout account first",
            )

    try:
        account = await client.retrieve_account(str(row["stripe_account_id"]))
        link = await client.create_account_link(
            account_id=str(row["stripe_account_id"]),
            refresh_url=settings.stripe_connect_refresh_url,
            return_url=settings.stripe_connect_return_url,
        )
    except StripeApiError as exc:
        raise HTTPException(
            status_code=502 if exc.retryable else 409,
            detail=exc.detail,
        ) from exc

    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        await _owner(connection)
        saved = await _save_account_snapshot(
            connection,
            owner_id=owner["id"],
            account=account,
        )
    url = str(link.get("url") or "").strip()
    if not url.startswith("https://"):
        raise HTTPException(status_code=502, detail="Stripe onboarding URL is invalid")
    return jsonable_encoder({
        "url": url,
        "expires_at": link.get("expires_at"),
        "account": saved,
    })


@router.post("/connect/sync")
async def sync_stripe_account(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    settings = get_settings()
    client = _client(settings)
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        row = await connection.fetchrow(
            "select * from tcg.stripe_connected_accounts where owner_id=$1",
            owner["id"],
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Stripe payout account not found")
    try:
        account = await client.retrieve_account(str(row["stripe_account_id"]))
    except StripeApiError as exc:
        raise HTTPException(
            status_code=502 if exc.retryable else 409,
            detail=exc.detail,
        ) from exc
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        await _owner(connection)
        saved = await _save_account_snapshot(
            connection,
            owner_id=owner["id"],
            account=account,
        )
    return jsonable_encoder({"account": saved, "blockers": _readiness_blockers(saved)})


async def _unreconciled_sales_count(
    connection: asyncpg.Connection,
    owner_id: UUID,
) -> int:
    value = await connection.fetchval(
        """
        select count(*)::int
        from tcg.order_items oi
        join tcg.orders o on o.id=oi.order_id
        where oi.owner_id=$1
          and o.source in ('SHOPIFY','EBAY')
          and not exists (
            select 1
            from tcg.order_item_reconciliations r
            where r.order_item_id=oi.id
              and r.fees_reconciled_at is not null
              and r.shipping_cost_reconciled_at is not null
          )
        """,
        owner_id,
    )
    return int(value or 0)


async def _owner_payout_balance(
    connection: asyncpg.Connection,
    owner_id: UUID,
) -> tuple[int, int]:
    ledger_available = await connection.fetchval(
        """
        select coalesce(sum(amount_minor),0)::bigint
        from tcg.financial_ledger_entries
        where owner_id=$1 and funds_status='AVAILABLE'
        """,
        owner_id,
    )
    reserved = await connection.fetchval(
        """
        select coalesce(sum(amount_minor),0)::bigint
        from tcg.payout_requests
        where owner_id=$1 and status in ('REQUESTED','APPROVED')
        """,
        owner_id,
    )
    return int(ledger_available or 0), int(reserved or 0)


@router.get("/payouts/queue")
async def stripe_payout_queue(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    await _require_founder_operator(request, user)
    async with request.app.state.db_pool.acquire() as connection:
        rows = await connection.fetch(
            """
            select
              pr.id,pr.owner_id,pr.payout_code,pr.amount_minor,pr.currency,
              pr.status,pr.requested_at,pr.approved_at,pr.resolved_at,pr.version,
              o.display_name,o.owner_type,o.active as owner_active,
              sca.id as connected_account_db_id,
              sca.stripe_account_id,sca.livemode,
              sca.status as stripe_status,sca.payouts_enabled,
              sca.transfers_capability_status,
              sca.requirements_currently_due,sca.requirements_past_due,
              spe.state as execution_state,spe.last_error_code as execution_error
            from tcg.payout_requests pr
            join tcg.owners o on o.id=pr.owner_id
            left join tcg.stripe_connected_accounts sca on sca.owner_id=pr.owner_id
            left join tcg.stripe_payout_executions spe on spe.payout_request_id=pr.id
            where pr.status in ('REQUESTED','APPROVED')
            order by pr.requested_at,pr.id
            """
        )
        items: list[dict[str, Any]] = []
        for source in rows:
            row = dict(source)
            account_row = None
            if row["connected_account_db_id"] is not None:
                account_row = {
                    "status": row["stripe_status"],
                    "payouts_enabled": row["payouts_enabled"],
                    "transfers_capability_status": row["transfers_capability_status"],
                    "requirements_currently_due": row["requirements_currently_due"],
                    "requirements_past_due": row["requirements_past_due"],
                }
            blockers = _readiness_blockers(account_row)
            ledger_available, reserved = await _owner_payout_balance(
                connection, row["owner_id"]
            )
            unreconciled = await _unreconciled_sales_count(
                connection, row["owner_id"]
            )
            if not row["owner_active"]:
                blockers.append("OWNER_INACTIVE")
            if unreconciled:
                blockers.append("UNRECONCILED_EXTERNAL_SALES")
            if ledger_available < reserved:
                blockers.append("OWNER_BALANCE_SHORTFALL")
            row["ledger_available_minor"] = ledger_available
            row["reserved_payout_minor"] = reserved
            row["unreconciled_external_sales"] = unreconciled
            row["blockers"] = sorted(set(blockers))
            row["eligible_for_approval"] = (
                row["status"] == "REQUESTED" and not row["blockers"]
            )
            items.append(row)
    return jsonable_encoder({"items": items})


@router.post("/payouts/{payout_id}/approve")
async def approve_stripe_payout(
    payout_id: UUID,
    payload: PayoutReview,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    operator = await _require_founder_operator(request, user)
    async with request.app.state.db_pool.acquire() as connection:
        async with connection.transaction():
            payout = await connection.fetchrow(
                "select * from tcg.payout_requests where id=$1 for update",
                payout_id,
            )
            if payout is None:
                raise HTTPException(status_code=404, detail="Payout request not found")
            if payout["status"] == "APPROVED":
                execution = await connection.fetchrow(
                    "select * from tcg.stripe_payout_executions where payout_request_id=$1",
                    payout_id,
                )
                return jsonable_encoder(
                    {"payout": dict(payout), "execution": dict(execution) if execution else None,
                     "idempotent": True}
                )
            if payout["version"] != payload.version:
                raise HTTPException(
                    status_code=409,
                    detail={"message": "Payout request changed; refresh and try again",
                            "current_version": payout["version"]},
                )
            if payout["status"] != "REQUESTED":
                raise HTTPException(
                    status_code=409,
                    detail=f"Payout is {payout['status']} and cannot be approved",
                )

            account = await connection.fetchrow(
                "select * from tcg.stripe_connected_accounts where owner_id=$1 for update",
                payout["owner_id"],
            )
            blockers = _readiness_blockers(account)
            unreconciled = await _unreconciled_sales_count(
                connection, payout["owner_id"]
            )
            if unreconciled:
                blockers.append("UNRECONCILED_EXTERNAL_SALES")
            ledger_available, reserved = await _owner_payout_balance(
                connection, payout["owner_id"]
            )
            if ledger_available < reserved:
                blockers.append("OWNER_BALANCE_SHORTFALL")
            if blockers:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Payout is not eligible for approval",
                        "blockers": sorted(set(blockers)),
                    },
                )

            execution = await connection.fetchrow(
                """
                insert into tcg.stripe_payout_executions(
                    payout_request_id,owner_id,connected_account_id,
                    idempotency_key,amount_minor,currency,state,transfer_group
                ) values ($1,$2,$3,$4,$5,$6,'PREPARED',$7)
                on conflict (payout_request_id) do nothing
                returning *
                """,
                payout["id"],
                payout["owner_id"],
                account["id"],
                f"drop-rate:payout:{payout['id']}",
                payout["amount_minor"],
                payout["currency"],
                payout["payout_code"],
            )
            if execution is None:
                execution = await connection.fetchrow(
                    "select * from tcg.stripe_payout_executions where payout_request_id=$1",
                    payout_id,
                )

            updated = await connection.fetchrow(
                """
                update tcg.payout_requests
                set status='APPROVED',
                    approved_at=clock_timestamp(),
                    approved_by_user_id=$2,
                    rejected_reason=null,
                    version=version+1,
                    updated_at=clock_timestamp()
                where id=$1
                returning *
                """,
                payout_id,
                user.user_id,
            )
            await connection.execute(
                """
                insert into tcg.audit_events(
                    actor,request_id,action,entity_type,entity_id,old_values,new_values
                ) values ($1,$2,'STRIPE_PAYOUT_APPROVED','PAYOUT_REQUEST',$3,$4::jsonb,$5::jsonb)
                """,
                str(user.user_id),
                str(request.state.request_id),
                payout_id,
                json.dumps({"status": payout["status"], "version": payout["version"]}),
                json.dumps({
                    "status": updated["status"],
                    "version": updated["version"],
                    "approved_by_owner_id": str(operator["id"]),
                    "execution_state": execution["state"],
                }),
            )
    return jsonable_encoder({"payout": dict(updated), "execution": dict(execution), "idempotent": False})


@router.post("/payouts/{payout_id}/reject")
async def reject_stripe_payout(
    payout_id: UUID,
    payload: PayoutReview,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    operator = await _require_founder_operator(request, user)
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A rejection reason is required")
    async with request.app.state.db_pool.acquire() as connection:
        async with connection.transaction():
            payout = await connection.fetchrow(
                "select * from tcg.payout_requests where id=$1 for update",
                payout_id,
            )
            if payout is None:
                raise HTTPException(status_code=404, detail="Payout request not found")
            if payout["version"] != payload.version or payout["status"] != "REQUESTED":
                raise HTTPException(
                    status_code=409,
                    detail="Only the current REQUESTED payout version can be rejected",
                )
            updated = await connection.fetchrow(
                """
                update tcg.payout_requests
                set status='REJECTED',rejected_reason=$2,resolved_at=clock_timestamp(),
                    version=version+1,updated_at=clock_timestamp()
                where id=$1
                returning *
                """,
                payout_id,
                reason,
            )
            await connection.execute(
                """
                insert into tcg.audit_events(
                    actor,request_id,action,entity_type,entity_id,old_values,new_values
                ) values ($1,$2,'STRIPE_PAYOUT_REJECTED','PAYOUT_REQUEST',$3,$4::jsonb,$5::jsonb)
                """,
                str(user.user_id),
                str(request.state.request_id),
                payout_id,
                json.dumps({"status": payout["status"], "version": payout["version"]}),
                json.dumps({
                    "status": updated["status"],
                    "version": updated["version"],
                    "reason": reason,
                    "rejected_by_owner_id": str(operator["id"]),
                }),
            )
    return jsonable_encoder({"payout": dict(updated)})


@router.post("/webhooks")
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook is not configured")
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature")

    raw = await request.body()
    verify_stripe_signature(raw, stripe_signature, settings.stripe_webhook_secret)
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe event JSON") from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Invalid Stripe event")
    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    if not event_id.startswith("evt_") or not event_type:
        raise HTTPException(status_code=400, detail="Invalid Stripe event envelope")
    connected_account_id = str(event.get("account") or "").strip() or None
    livemode = bool(event.get("livemode"))
    payload_hash = hashlib.sha256(raw).hexdigest()

    async with request.app.state.db_pool.acquire() as connection:
        async with connection.transaction():
            inserted = await connection.fetchrow(
                """
                insert into tcg.stripe_webhook_events(
                    stripe_event_id,event_type,connected_account_id,livemode,payload_sha256,
                    attempt_count,last_attempt_at
                ) values ($1,$2,$3,$4,$5,1,clock_timestamp())
                on conflict (stripe_event_id) do nothing
                returning id
                """,
                event_id,
                event_type,
                connected_account_id,
                livemode,
                payload_hash,
            )
            if inserted is None:
                existing = await connection.fetchrow(
                    """
                    select processing_status,payload_sha256,last_attempt_at
                    from tcg.stripe_webhook_events
                    where stripe_event_id=$1
                    for update
                    """,
                    event_id,
                )
                if existing is None:
                    raise HTTPException(status_code=409, detail="Stripe event state changed")
                if existing["payload_sha256"] != payload_hash:
                    raise HTTPException(
                        status_code=400,
                        detail="Stripe event ID was replayed with a different payload",
                    )
                if existing["processing_status"] in ("PROCESSED", "IGNORED"):
                    return {"received": True, "duplicate": True}
                recent_attempt = await connection.fetchval(
                    """
                    select $1::timestamptz is not null
                       and $1::timestamptz > clock_timestamp() - interval '10 minutes'
                    """,
                    existing["last_attempt_at"],
                )
                if existing["processing_status"] == "RECEIVED" and recent_attempt:
                    return {"received": True, "duplicate": True}
                await connection.execute(
                    """
                    update tcg.stripe_webhook_events
                    set processing_status='RECEIVED',
                        attempt_count=attempt_count+1,
                        last_attempt_at=clock_timestamp(),
                        last_error_code=null,
                        version=version+1
                    where stripe_event_id=$1
                    """,
                    event_id,
                )

    data = event.get("data")
    obj = data.get("object") if isinstance(data, dict) else None
    if not isinstance(obj, dict):
        obj = {}

    processing_status = "IGNORED"
    try:
        async with request.app.state.db_pool.acquire() as connection:
            async with connection.transaction():
                if event_type == "account.updated":
                    account_id = str(obj.get("id") or "").strip()
                    mapped = await connection.fetchrow(
                        "select owner_id from tcg.stripe_connected_accounts where stripe_account_id=$1",
                        account_id,
                    )
                    if mapped:
                        await _save_account_snapshot(
                            connection,
                            owner_id=mapped["owner_id"],
                            account=obj,
                        )
                        processing_status = "PROCESSED"
                elif event_type.startswith("payout."):
                    payout_id = str(obj.get("id") or "").strip()
                    execution = await connection.fetchrow(
                        """
                        select * from tcg.stripe_payout_executions
                        where stripe_payout_id=$1
                        for update
                        """,
                        payout_id,
                    )
                    if execution:
                        if event_type == "payout.paid":
                            state = "PAID"
                        elif event_type in {"payout.failed", "payout.canceled", "payout.cancelled"}:
                            state = "FAILED"
                        else:
                            state = "PAYOUT_PENDING"
                        await connection.execute(
                            """
                            update tcg.stripe_payout_executions
                            set state=$2,last_error_code=$3,
                                resolved_at=case when $2 in ('PAID','FAILED')
                                  then clock_timestamp() else resolved_at end,
                                version=version+1,updated_at=clock_timestamp()
                            where id=$1
                            """,
                            execution["id"],
                            state,
                            str(obj.get("failure_code") or "").strip() or None,
                        )
                        processing_status = "PROCESSED"
                elif event_type in {"transfer.created", "transfer.updated", "transfer.reversed"}:
                    transfer_id = str(obj.get("id") or "").strip()
                    execution = await connection.fetchrow(
                        "select id from tcg.stripe_payout_executions where stripe_transfer_id=$1",
                        transfer_id,
                    )
                    if execution:
                        await connection.execute(
                            """
                            update tcg.stripe_payout_executions
                            set state=case when $2='transfer.reversed' then 'REVERSED'
                                           else 'TRANSFERRED' end,
                                resolved_at=case when $2='transfer.reversed'
                                  then clock_timestamp() else resolved_at end,
                                version=version+1,updated_at=clock_timestamp()
                            where id=$1
                            """,
                            execution["id"],
                            event_type,
                        )
                        processing_status = "PROCESSED"

                await connection.execute(
                    """
                    update tcg.stripe_webhook_events
                    set processing_status=$2,processed_at=clock_timestamp(),
                        last_error_code=null,version=version+1
                    where stripe_event_id=$1
                    """,
                    event_id,
                    processing_status,
                )
    except Exception:
        async with request.app.state.db_pool.acquire() as connection:
            await connection.execute(
                """
                update tcg.stripe_webhook_events
                set processing_status='FAILED',last_error_code='PROCESSING_FAILED',
                    version=version+1
                where stripe_event_id=$1
                """,
                event_id,
            )
        raise
    return {"received": True, "duplicate": False, "status": processing_status}
