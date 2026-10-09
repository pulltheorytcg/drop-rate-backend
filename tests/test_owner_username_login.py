from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Response
from starlette.requests import Request

from app import owner_login
from app.owner_login import OwnerLoginRequest, create_owner_session


def _request(headers: dict[str, str] | None = None) -> Request:
    app = FastAPI()
    scope = {
        "type": "http",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/public/owner-session",
        "raw_path": b"/api/v1/public/owner-session",
        "query_string": b"",
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {}).items()
        ],
        "client": ("100.64.0.10", 54321),
        "server": ("drop-rate.example", 443),
        "app": app,
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_username_login_resolves_server_side_and_returns_session(monkeypatch) -> None:
    calls: dict[str, object] = {}

    async def fake_rate(*args, **kwargs):
        return True, 0

    async def fake_resolve(_request, username):
        calls["username"] = username
        return "seller@example.com"

    async def fake_auth(email, password):
        calls["email"] = email
        calls["password"] = password
        return 200, {
            "access_token": "access",
            "refresh_token": "refresh",
            "token_type": "bearer",
            "user": {"id": "00000000-0000-0000-0000-000000000001", "email": email},
        }

    async def unexpected_failure(*args, **kwargs):
        raise AssertionError("successful login must not record a failure")

    monkeypatch.setattr(owner_login, "_login_rate_status", fake_rate)
    monkeypatch.setattr(owner_login, "_resolve_username_email", fake_resolve)
    monkeypatch.setattr(owner_login, "_supabase_password_session", fake_auth)
    monkeypatch.setattr(owner_login, "_record_login_failure", unexpected_failure)

    payload = OwnerLoginRequest(identifier="  Sunny_Cards  ", password="correct horse battery staple")
    response = Response()
    result = await create_owner_session(payload, _request(), response)

    assert calls["username"] == "sunny_cards"
    assert calls["email"] == "seller@example.com"
    assert calls["password"] == "correct horse battery staple"
    assert result["access_token"] == "access"
    assert result["refresh_token"] == "refresh"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


@pytest.mark.asyncio
async def test_email_login_skips_username_resolution(monkeypatch) -> None:
    calls: dict[str, object] = {}

    async def fake_rate(*args, **kwargs):
        return True, 0

    async def should_not_resolve(*args, **kwargs):
        raise AssertionError("email login must not resolve a username")

    async def fake_auth(email, password):
        calls["email"] = email
        return 200, {"access_token": "a", "refresh_token": "r"}

    monkeypatch.setattr(owner_login, "_login_rate_status", fake_rate)
    monkeypatch.setattr(owner_login, "_resolve_username_email", should_not_resolve)
    monkeypatch.setattr(owner_login, "_supabase_password_session", fake_auth)

    payload = OwnerLoginRequest(identifier=" SELLER@EXAMPLE.COM ", password="password")
    result = await create_owner_session(payload, _request(), Response())

    assert calls["email"] == "seller@example.com"
    assert result["access_token"] == "a"


@pytest.mark.asyncio
async def test_unknown_username_uses_synthetic_email_and_generic_error(monkeypatch) -> None:
    calls: dict[str, object] = {}

    async def fake_rate(*args, **kwargs):
        return True, 0

    async def fake_resolve(_request, username):
        calls["username"] = username
        return None

    async def fake_auth(email, password):
        calls["auth_email"] = email
        return 400, {"error": "invalid_grant", "error_description": "Invalid login credentials"}

    async def fake_record(*args, **kwargs):
        calls["failure_recorded"] = True

    monkeypatch.setattr(owner_login, "_login_rate_status", fake_rate)
    monkeypatch.setattr(owner_login, "_resolve_username_email", fake_resolve)
    monkeypatch.setattr(owner_login, "_supabase_password_session", fake_auth)
    monkeypatch.setattr(owner_login, "_record_login_failure", fake_record)

    with pytest.raises(HTTPException) as exc:
        await create_owner_session(
            OwnerLoginRequest(identifier="does_not_exist", password="wrong"),
            _request(),
            Response(),
        )

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid email, username or password"
    assert str(calls["auth_email"]).startswith("unknown-")
    assert str(calls["auth_email"]).endswith("@example.invalid")
    assert "does_not_exist" not in str(calls["auth_email"])
    assert calls["failure_recorded"] is True


@pytest.mark.asyncio
async def test_rate_limit_blocks_before_resolution_or_supabase(monkeypatch) -> None:
    async def fake_rate(*args, **kwargs):
        return False, 123

    async def should_not_run(*args, **kwargs):
        raise AssertionError("rate-limited login must stop before resolution/auth")

    monkeypatch.setattr(owner_login, "_login_rate_status", fake_rate)
    monkeypatch.setattr(owner_login, "_resolve_username_email", should_not_run)
    monkeypatch.setattr(owner_login, "_supabase_password_session", should_not_run)

    with pytest.raises(HTTPException) as exc:
        await create_owner_session(
            OwnerLoginRequest(identifier="seller_name", password="wrong"),
            _request({"x-forwarded-for": "203.0.113.99"}),
            Response(),
        )

    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "123"}
    assert "Too many sign-in attempts" in str(exc.value.detail)


def test_login_identifier_and_network_are_hashed_before_database_throttling() -> None:
    request = _request({"x-forwarded-for": "203.0.113.7, 100.64.0.1"})
    network = owner_login._client_network_identity(request)
    network_hash = owner_login._sha256_key("drop-rate-owner-login-network-v1", network)
    identifier_hash = owner_login._sha256_key(
        "drop-rate-owner-login-identifier-v1",
        "seller@example.com",
    )

    assert network == "203.0.113.7"
    assert len(network_hash) == 64
    assert len(identifier_hash) == 64
    assert "203.0.113.7" not in network_hash
    assert "seller@example.com" not in identifier_hash


def test_username_login_migration_keeps_email_resolution_server_only() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sql = (
        root
        / "database"
        / "migrations"
        / "20261001001000_owner_username_login.sql"
    ).read_text()

    lower = sql.lower()
    assert "create or replace function tcg.resolve_owner_login_email" in lower
    assert "join auth.users" in lower
    assert "security definer" in lower
    assert "grant execute on function tcg.resolve_owner_login_email(text) to tcg_api" in lower
    assert "revoke all on function tcg.resolve_owner_login_email(text) from public, anon, authenticated" in lower

    assert "create table if not exists tcg.owner_login_failures" in lower
    assert "enable row level security" in lower
    assert "identifier_failures < 8" in lower
    assert "network_failures < 30" in lower
    assert "interval '15 minutes'" in lower


def test_seller_hub_login_shell_uses_email_or_username_contract() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "backend" / "app" / "static" / "owner.html").read_text()
    js = (root / "backend" / "app" / "static" / "owner-portal.js").read_text()

    assert "Email or username" in html
    assert 'type="text" autocomplete="username"' in html
    assert 'fetch("/api/v1/public/owner-session"' in js
    assert 'identifier: byId("owner-email-input").value.trim()' in js
    assert 'authRequest("/token?grant_type=password"' not in js[js.index('byId("owner-login-form")'):js.index('byId("owner-google")')]
    assert '<script src="/assets/owner-portal.js?v=owner-v15" defer></script>' in html
