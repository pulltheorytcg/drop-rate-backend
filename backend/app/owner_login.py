from __future__ import annotations

import hashlib
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from .settings import get_settings


router = APIRouter(tags=["owner-login"])

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,29}$")
_INVALID_LOGIN_DETAIL = "Invalid email, username or password"


class OwnerLoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=4096)

    @field_validator("identifier")
    @classmethod
    def clean_identifier(cls, value: str) -> str:
        clean = value.strip().casefold()
        if not clean:
            raise ValueError("Email or username is required")
        return clean


def _sha256_key(namespace: str, value: str) -> str:
    return hashlib.sha256(f"{namespace}|{value}".encode("utf-8")).hexdigest()


def _client_network_identity(request: Request) -> str:
    # Railway terminates the public connection before Uvicorn. Prefer the
    # forwarding headers supplied by the proxy, but never persist the raw IP.
    for header in ("cf-connecting-ip", "x-forwarded-for", "x-real-ip"):
        raw = (request.headers.get(header) or "").strip()
        if not raw:
            continue
        value = raw.split(",", 1)[0].strip()
        if value:
            return value
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def _login_rate_status(
    request: Request,
    *,
    network_hash: str,
    identifier_hash: str,
) -> tuple[bool, int]:
    async with request.app.state.db_pool.acquire() as connection:
        row = await connection.fetchrow(
            "select * from tcg.owner_login_rate_limit_status($1,$2)",
            network_hash,
            identifier_hash,
        )
    if row is None:
        raise HTTPException(status_code=503, detail="Sign in is temporarily unavailable")
    return bool(row["allowed"]), int(row["retry_after_seconds"] or 0)


async def _record_login_failure(
    request: Request,
    *,
    network_hash: str,
    identifier_hash: str,
) -> None:
    async with request.app.state.db_pool.acquire() as connection:
        await connection.execute(
            "select tcg.record_owner_login_failure($1,$2)",
            network_hash,
            identifier_hash,
        )


async def _resolve_username_email(request: Request, username: str) -> str | None:
    if _USERNAME_RE.fullmatch(username) is None:
        return None
    async with request.app.state.db_pool.acquire() as connection:
        value = await connection.fetchval(
            "select tcg.resolve_owner_login_email($1)",
            username,
        )
    return str(value).strip().casefold() if value else None


async def _supabase_password_session(email: str, password: str) -> tuple[int, dict[str, Any]]:
    settings = get_settings()
    url = f"{settings.supabase_url}/auth/v1/token"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            response = await client.post(
                url,
                params={"grant_type": "password"},
                headers={
                    "apikey": settings.supabase_publishable_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={"email": email, "password": password},
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign in is temporarily unavailable",
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}
    return response.status_code, payload


@router.post("/api/v1/public/owner-session")
async def create_owner_session(
    payload: OwnerLoginRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    identifier = payload.identifier
    network_hash = _sha256_key(
        "drop-rate-owner-login-network-v1",
        _client_network_identity(request),
    )
    identifier_hash = _sha256_key(
        "drop-rate-owner-login-identifier-v1",
        identifier,
    )

    allowed, retry_after = await _login_rate_status(
        request,
        network_hash=network_hash,
        identifier_hash=identifier_hash,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Try again shortly.",
            headers={"Retry-After": str(max(1, retry_after))},
        )

    if "@" in identifier:
        email = identifier
    else:
        email = await _resolve_username_email(request, identifier)

    # Always exercise the same Supabase password path for an unknown username.
    # This keeps the public response generic and avoids returning a resolved
    # email address to an unauthenticated browser.
    auth_email = email or f"unknown-{identifier_hash[:24]}@example.invalid"
    upstream_status, session = await _supabase_password_session(
        auth_email,
        payload.password,
    )

    if upstream_status == 429:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Try again shortly.",
        )

    if upstream_status >= 500:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign in is temporarily unavailable",
        )

    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")
    if upstream_status != 200 or not access_token or not refresh_token:
        await _record_login_failure(
            request,
            network_hash=network_hash,
            identifier_hash=identifier_hash,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_LOGIN_DETAIL,
        )

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return session
