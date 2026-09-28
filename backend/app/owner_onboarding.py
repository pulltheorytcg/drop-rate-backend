from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator

from .access_control import require_platform_admin
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .resend_email import (
    ResendApiError,
    ResendEmailClient,
    ResendWebhookVerificationError,
    build_seller_invite_email,
    verify_resend_webhook,
)
from .settings import Settings, get_settings


router = APIRouter(tags=["owner-onboarding"])
ONBOARDING_ACK_VERSION = 1


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    if not local or not domain:
        return "invited email"
    if len(local) == 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[:2] + ("*" * min(6, len(local) - 2))
    return f"{masked_local}@{domain}"


def _public_origin(request: Request, settings: Settings) -> str:
    if settings.public_app_url:
        return settings.public_app_url.rstrip("/")
    origin = str(request.base_url).rstrip("/")
    if origin.startswith("https://"):
        return origin
    if settings.environment.casefold() in {"production", "prod"}:
        raise HTTPException(
            status_code=500,
            detail="Public HTTPS app URL is required for seller invitation emails",
        )
    return origin


def _invite_url(origin: str, raw_token: str) -> str:
    return f"{origin}/owner/join?invite={quote(raw_token, safe='')}"


def _email_ready(settings: Settings) -> bool:
    return bool(settings.resend_api_key and settings.seller_invite_from_email)


class OwnerInviteCreate(BaseModel):
    invited_name: str = Field(min_length=1, max_length=120)
    invited_email: str = Field(min_length=3, max_length=320)
    commission_bps: int = Field(default=1000, ge=0, le=10000)
    expires_in_days: int = Field(default=7, ge=1, le=30)

    @field_validator("invited_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("invited_email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        clean = value.strip().lower()
        if "@" not in clean or clean.startswith("@") or clean.endswith("@"):
            raise ValueError("Enter a valid email address")
        return clean


class OwnerInviteRedeem(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    display_name: str = Field(min_length=1, max_length=120)
    acknowledged: bool
    acknowledgement_version: Literal[1] = ONBOARDING_ACK_VERSION

    @field_validator("token", "display_name")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.strip()


async def _record_email_result(
    *,
    request: Request,
    user: AuthenticatedUser,
    invite_id: UUID,
    status: str,
    provider_message_id: str | None,
    error_code: str | None,
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await require_platform_admin(connection)
        row = await connection.fetchrow(
            "select * from tcg.record_owner_invite_email_result($1,$2,$3,$4,$5)",
            invite_id,
            status,
            "RESEND",
            provider_message_id,
            error_code,
        )
    return dict(row) if row is not None else {}


async def _send_invite_email(
    *,
    request: Request,
    user: AuthenticatedUser,
    invite: dict,
    raw_token: str,
    attempt_number: int,
) -> dict:
    settings = get_settings()
    if not _email_ready(settings):
        return {
            "status": "NOT_CONFIGURED",
            "provider": "RESEND",
            "message": "Transactional email is not configured; use the secure invite link.",
        }

    origin = _public_origin(request, settings)
    invite_url = _invite_url(origin, raw_token)
    email = build_seller_invite_email(
        invited_name=str(invite["invited_name"]),
        invite_url=invite_url,
        commission_bps=int(invite["commission_bps"]),
        expires_at=invite["expires_at"],
        logo_url=f"{origin}/assets/brand-assets/drop-rate-logo.png",
    )
    client = ResendEmailClient(api_key=str(settings.resend_api_key))

    try:
        message_id = await client.send(
            sender=str(settings.seller_invite_from_email),
            recipient=str(invite["invited_email"]),
            email=email,
            idempotency_key=f"owner-invite/{invite['id']}/attempt/{attempt_number}",
            reply_to=settings.seller_invite_reply_to,
        )
    except ResendApiError as exc:
        error_code = (
            f"RESEND_HTTP_{exc.status_code}"
            if exc.status_code is not None
            else "RESEND_REQUEST_FAILED"
        )
        recorded = await _record_email_result(
            request=request,
            user=user,
            invite_id=UUID(str(invite["id"])),
            status="FAILED",
            provider_message_id=None,
            error_code=error_code,
        )
        return {
            "status": "FAILED",
            "provider": "RESEND",
            "retryable": exc.retryable,
            "error_code": error_code,
            "attempt_count": recorded.get("email_attempt_count", attempt_number),
        }

    recorded = await _record_email_result(
        request=request,
        user=user,
        invite_id=UUID(str(invite["id"])),
        status="SENT",
        provider_message_id=message_id,
        error_code=None,
    )
    return {
        "status": "SENT",
        "provider": "RESEND",
        "provider_message_id": message_id,
        "attempt_count": recorded.get("email_attempt_count", attempt_number),
        "sent_at": recorded.get("email_sent_at"),
    }


@router.post("/api/v1/owner-invites")
async def create_owner_invite(
    payload: OwnerInviteCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await require_platform_admin(connection)
        row = await connection.fetchrow(
            "select * from tcg.create_owner_invite($1,$2,$3,$4,$5)",
            _token_hash(raw_token),
            payload.invited_name,
            payload.invited_email,
            payload.commission_bps,
            expires_at,
        )

    if row is None:
        raise HTTPException(status_code=500, detail="Owner invite could not be created")

    settings = get_settings()
    origin = _public_origin(request, settings)
    invite = dict(row)
    delivery = await _send_invite_email(
        request=request,
        user=user,
        invite=invite,
        raw_token=raw_token,
        attempt_number=1,
    )
    invite_url = _invite_url(origin, raw_token)
    return jsonable_encoder(
        {
            **invite,
            "invite_url": invite_url,
            "email_delivery": delivery,
        }
    )


@router.get("/api/v1/owner-invites")
async def list_owner_invites(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=25, ge=1, le=100),
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await require_platform_admin(connection)
        rows = await connection.fetch(
            "select * from tcg.list_owner_invites($1)",
            limit,
        )
    return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/api/v1/owner-invites/{invite_id}/resend")
async def resend_owner_invite(
    invite_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    raw_token = secrets.token_urlsafe(32)

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await require_platform_admin(connection)
        row = await connection.fetchrow(
            "select * from tcg.prepare_owner_invite_resend($1,$2)",
            invite_id,
            _token_hash(raw_token),
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Owner invite not found")

    invite = dict(row)
    settings = get_settings()
    origin = _public_origin(request, settings)
    attempt_number = int(invite.get("email_attempt_count") or 0) + 1
    delivery = await _send_invite_email(
        request=request,
        user=user,
        invite=invite,
        raw_token=raw_token,
        attempt_number=attempt_number,
    )
    return jsonable_encoder(
        {
            "id": invite_id,
            "invite_url": _invite_url(origin, raw_token),
            "email_delivery": delivery,
        }
    )


@router.get("/api/v1/public/owner-invites/{token}")
async def preview_owner_invite(token: str, request: Request) -> dict:
    clean = token.strip()
    if len(clean) < 20 or len(clean) > 500:
        raise HTTPException(status_code=404, detail="Owner invite not found")

    async with request.app.state.db_pool.acquire() as connection:
        row = await connection.fetchrow(
            "select * from tcg.preview_owner_invite($1)",
            _token_hash(clean),
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Owner invite not found")
    if not row["available"]:
        raise HTTPException(status_code=410, detail="Owner invite is no longer available")

    return jsonable_encoder(
        {
            "invited_name": row["invited_name"],
            "invited_email_masked": _mask_email(str(row["invited_email"])),
            "commission_bps": row["commission_bps"],
            "expires_at": row["expires_at"],
            "acknowledgement_version": ONBOARDING_ACK_VERSION,
        }
    )


@router.post("/api/v1/owner-invites/redeem")
async def redeem_owner_invite(
    payload: OwnerInviteRedeem,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    if not user.email:
        raise HTTPException(
            status_code=403,
            detail="A verified account email is required to redeem this invitation",
        )
    if not payload.acknowledged:
        raise HTTPException(
            status_code=422,
            detail="Seller onboarding acknowledgement is required",
        )

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        row = await connection.fetchrow(
            "select * from tcg.redeem_owner_invite($1,$2,$3,$4)",
            _token_hash(payload.token),
            payload.display_name,
            user.email,
            payload.acknowledgement_version,
        )

    if row is None:
        raise HTTPException(status_code=409, detail="Owner invite could not be redeemed")
    return jsonable_encoder(
        {
            "owner": dict(row),
            "onboarding": {
                "status": "COMPLETE",
                "acknowledgement_version": payload.acknowledgement_version,
                "next": "/owner?welcome=1",
            },
        }
    )


@router.post("/api/v1/webhooks/resend")
async def resend_email_webhook(request: Request) -> dict:
    settings = get_settings()
    if not settings.resend_webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="Resend webhook verification is not configured",
        )

    raw_body = await request.body()
    svix_id = request.headers.get("svix-id", "")
    svix_timestamp = request.headers.get("svix-timestamp", "")
    svix_signature = request.headers.get("svix-signature", "")

    try:
        verify_resend_webhook(
            raw_body=raw_body,
            webhook_secret=settings.resend_webhook_secret,
            svix_id=svix_id,
            svix_timestamp=svix_timestamp,
            svix_signature=svix_signature,
        )
    except ResendWebhookVerificationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid Resend webhook signature",
        ) from exc

    try:
        event = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Resend webhook payload") from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Invalid Resend webhook payload")

    event_type = str(event.get("type") or "").strip().lower()
    supported = {
        "email.sent",
        "email.delivered",
        "email.delivery_delayed",
        "email.bounced",
        "email.failed",
        "email.suppressed",
        "email.complained",
    }
    if event_type not in supported:
        return {"processed": False, "ignored": True, "event_type": event_type}

    data = event.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Resend webhook data is missing")
    provider_message_id = str(
        data.get("email_id") or data.get("id") or ""
    ).strip()
    if not provider_message_id:
        raise HTTPException(status_code=400, detail="Resend email ID is missing")

    created_at = str(event.get("created_at") or "").strip()
    try:
        occurred_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Resend event timestamp") from exc
    if occurred_at.tzinfo is None:
        raise HTTPException(status_code=400, detail="Invalid Resend event timestamp")

    async with request.app.state.db_pool.acquire() as connection:
        result = await connection.fetchrow(
            "select * from tcg.record_owner_invite_email_webhook($1,$2,$3,$4,$5,$6)",
            "RESEND",
            svix_id,
            provider_message_id,
            event_type,
            hashlib.sha256(raw_body).hexdigest(),
            occurred_at,
        )

    if result is None:
        raise HTTPException(status_code=500, detail="Resend webhook could not be recorded")
    return jsonable_encoder(dict(result))


@router.delete("/api/v1/owner-invites/{invite_id}")
async def revoke_owner_invite(
    invite_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await require_platform_admin(connection)
        revoked = await connection.fetchval(
            "select tcg.revoke_owner_invite($1)",
            invite_id,
        )

    if not revoked:
        raise HTTPException(status_code=404, detail="Open owner invite not found")
    return {"revoked": True}
