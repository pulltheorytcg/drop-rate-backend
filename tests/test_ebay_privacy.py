from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import ebay_privacy


ROOT = Path(__file__).parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"


def configured_settings():
    return SimpleNamespace(
        ebay_deletion_verification_token="A" * 40,
        ebay_deletion_endpoint=(
            "https://drop-rate-api-live-production.up.railway.app"
            "/api/v1/ebay/marketplace-account-deletion"
        ),
    )


@pytest.mark.asyncio
async def test_ebay_challenge_response_uses_required_hash_order(monkeypatch) -> None:
    monkeypatch.setattr(ebay_privacy, "get_settings", configured_settings)

    result = await ebay_privacy.verify_marketplace_account_deletion_endpoint(
        challenge_code="challenge-123"
    )

    settings = configured_settings()
    expected = hashlib.sha256(
        (
            "challenge-123"
            + settings.ebay_deletion_verification_token
            + settings.ebay_deletion_endpoint
        ).encode("utf-8")
    ).hexdigest()
    assert result == {"challengeResponse": expected}


@pytest.mark.asyncio
async def test_account_deletion_post_acknowledges_without_persistence(monkeypatch) -> None:
    monkeypatch.setattr(ebay_privacy, "get_settings", configured_settings)

    payload = b'{"metadata":{"topic":"MARKETPLACE_ACCOUNT_DELETION"},"notification":{"notificationId":"test"}}'
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/ebay/marketplace-account-deletion",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 1234),
            "scheme": "https",
        },
        receive,
    )

    response = await ebay_privacy.acknowledge_marketplace_account_deletion(request)

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_account_deletion_post_rejects_unrelated_topic(monkeypatch) -> None:
    monkeypatch.setattr(ebay_privacy, "get_settings", configured_settings)

    payload = b'{"metadata":{"topic":"SOMETHING_ELSE"}}'
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/ebay/marketplace-account-deletion",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 1234),
            "scheme": "https",
        },
        receive,
    )

    with pytest.raises(HTTPException) as exc_info:
        await ebay_privacy.acknowledge_marketplace_account_deletion(request)

    assert exc_info.value.status_code == 400


def test_callback_module_never_persists_or_logs_notification_payload() -> None:
    source = (ROOT / "backend" / "app" / "ebay_privacy.py").read_text().lower()
    assert "insert into" not in source
    assert "update tcg." not in source
    assert "delete from" not in source
    assert "logger." not in source


def test_callback_router_is_wired_into_app() -> None:
    main = MAIN.read_text()
    assert "from .ebay_privacy import router as ebay_privacy_router" in main
    assert "app.include_router(ebay_privacy_router)" in main
