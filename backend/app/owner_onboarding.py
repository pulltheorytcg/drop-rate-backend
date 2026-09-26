from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator

from .access_control import require_platform_admin
from .auth import AuthenticatedUser, require_user
from .db import user_connection


router = APIRouter(tags=["owner-onboarding"])


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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

    @field_validator("token", "display_name")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.strip()


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

    origin = str(request.base_url).rstrip("/")
    invite_url = f"{origin}/owner/join?invite={quote(raw_token, safe='')}"
    return jsonable_encoder({**dict(row), "invite_url": invite_url})


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
            "commission_bps": row["commission_bps"],
            "expires_at": row["expires_at"],
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

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        row = await connection.fetchrow(
            "select * from tcg.redeem_owner_invite($1,$2,$3)",
            _token_hash(payload.token),
            payload.display_name,
            user.email,
        )

    if row is None:
        raise HTTPException(status_code=409, detail="Owner invite could not be redeemed")
    return jsonable_encoder({"owner": dict(row)})


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
