from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .settings import get_settings


router = APIRouter(prefix="/api/v1/ebay", tags=["ebay-compliance"])

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,80}$")
_MAX_NOTIFICATION_BYTES = 64 * 1024


def _callback_settings() -> tuple[str, str]:
    settings = get_settings()
    token = settings.ebay_deletion_verification_token
    endpoint = settings.ebay_deletion_endpoint

    if not token or not endpoint:
        raise HTTPException(status_code=503, detail="eBay deletion callback is not configured")
    if not _TOKEN_RE.fullmatch(token):
        raise HTTPException(status_code=503, detail="eBay deletion verification token is invalid")
    if not endpoint.startswith("https://"):
        raise HTTPException(status_code=503, detail="eBay deletion callback endpoint must use HTTPS")

    return token, endpoint


@router.get("/marketplace-account-deletion")
async def verify_marketplace_account_deletion_endpoint(
    challenge_code: str = Query(min_length=1, max_length=512),
) -> dict[str, str]:
    """Answer eBay's ownership challenge for the configured callback endpoint."""

    token, endpoint = _callback_settings()
    digest = hashlib.sha256(
        f"{challenge_code}{token}{endpoint}".encode("utf-8")
    ).hexdigest()
    return {"challengeResponse": digest}


@router.post("/marketplace-account-deletion", status_code=204)
async def acknowledge_marketplace_account_deletion(request: Request) -> Response:
    """Acknowledge account-deletion notifications without persisting user data.

    Drop Rate currently does not retain eBay buyer/seller account identifiers in
    market observations. The callback therefore has no user record to delete.
    The payload is validated only enough to fail closed on unrelated requests and
    is never written to the database or logs.
    """

    _callback_settings()
    body = await request.body()
    if len(body) > _MAX_NOTIFICATION_BYTES:
        raise HTTPException(status_code=413, detail="Notification payload is too large")

    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON notification") from exc

    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    topic = metadata.get("topic") if isinstance(metadata, dict) else None
    if topic != "MARKETPLACE_ACCOUNT_DELETION":
        raise HTTPException(status_code=400, detail="Unsupported eBay notification topic")

    return Response(status_code=204)
