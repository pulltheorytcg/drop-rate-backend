"""Public launch-interest form stays separate from owner authentication."""

from __future__ import annotations

from pathlib import Path

import asyncpg
import httpx
import pytest

from app.seller_hub_launch import SellerHubLaunchSignup


ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "backend" / "app" / "static"
MIGRATION = ROOT / "database" / "migrations" / "20261031190234_seller_hub_launch_waitlist.sql"


class FakeConnection:
    def __init__(self, *, inserted: bool = True, failure: Exception | None = None):
        self.inserted = inserted
        self.failure = failure
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def fetchval(self, query, *args):
        self.calls.append((query, args))
        if self.failure:
            raise self.failure
        return self.inserted


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return self.connection


@pytest.fixture
def launch_app(monkeypatch):
    monkeypatch.setenv("TCG_DATABASE_URL", "postgres://example:example@localhost/example")
    monkeypatch.setenv("TCG_AUTH_ISSUER", "https://project.supabase.co/auth/v1")
    monkeypatch.setenv("TCG_AUTH_AUDIENCE", "authenticated")
    monkeypatch.setenv("TCG_SUPABASE_PUBLISHABLE_KEY", "test-public-value")
    from app.settings import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    connection = FakeConnection()
    app.state.db_pool = FakePool(connection)
    yield app, connection
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_public_root_is_waitlist_but_old_railway_dashboard_is_preserved(launch_app):
    app, _ = launch_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.droprate.co.uk") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "Sell With Drop Rate | Seller Hub Coming Soon" in response.text
        assert "registration" in response.text.lower()
        assert "/owner/join" in response.text
        assert "seller-hub-launch.css" in response.text

        invited = await client.get("/owner/join?invite=synthetic-invite")
        assert invited.status_code == 200
        assert "owner-join.js" in invited.text

        early_account = await client.get("/owner/join")
        assert "Create Seller Hub account" in early_account.text

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://drop-rate-api-live-production.up.railway.app") as client:
        dashboard = await client.get("/")
        assert dashboard.status_code == 200
        assert "seller-hub-launch.css" not in dashboard.text
        explicit = await client.get("/seller-hub")
        assert "Seller Hub Coming Soon" in explicit.text


@pytest.mark.asyncio
async def test_waitlist_signup_normalises_email_and_uses_private_sql_function(launch_app):
    app, connection = launch_app
    body = {
        "email": "  Collector+Cards@EXAMPLE.com  ",
        "name": "  Jamie  ",
        "interest": "COMICS_MANGA",
        "consent": True,
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.droprate.co.uk") as client:
        response = await client.post("/api/v1/public/seller-hub/waitlist", json=body)

    assert response.status_code == 200
    assert response.json() == {"status": "registered"}
    assert len(connection.calls) == 1
    query, args = connection.calls[0]
    assert "tcg_private.register_seller_hub_interest" in query
    assert args == ("collector+cards@example.com", "Jamie", "COMICS_MANGA", True)
    assert "collector+cards@example.com" not in query


@pytest.mark.asyncio
async def test_duplicate_email_has_indistinguishable_success_response(launch_app):
    app, connection = launch_app
    connection.inserted = False
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.droprate.co.uk") as client:
        result = await client.post("/api/v1/public/seller-hub/waitlist", json={"email": "same@example.com", "consent": True})
    assert result.json() == {"status": "registered"}


@pytest.mark.asyncio
async def test_invalid_opt_in_email_and_interest_rejected_without_database_write(launch_app):
    app, connection = launch_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.droprate.co.uk") as client:
        for overrides in (
            {"consent": False},
            {"email": "not-an-email"},
            {"interest": "PLATFORM_ADMIN"},
            {"name": "x" * 121},
        ):
            payload = {"email": "hello@example.com", "consent": True} | overrides
            response = await client.post("/api/v1/public/seller-hub/waitlist", json=payload)
            assert response.status_code == 422
    assert connection.calls == []


@pytest.mark.asyncio
async def test_honeypot_fails_closed_without_a_database_insert(launch_app):
    app, connection = launch_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.droprate.co.uk") as client:
        response = await client.post("/api/v1/public/seller-hub/waitlist", json={"email": "bot@example.com", "consent": True, "website": "https://spam.example"})
    assert response.json() == {"status": "registered"}
    assert connection.calls == []


@pytest.mark.asyncio
async def test_database_failure_is_retryable_and_does_not_claim_success(launch_app):
    app, connection = launch_app
    connection.failure = asyncpg.PostgresConnectionError("connection unavailable")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.droprate.co.uk") as client:
        response = await client.post("/api/v1/public/seller-hub/waitlist", json={"email": "valid@example.com", "consent": True})
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
    assert "valid@example.com" not in response.text


def test_private_sql_grants_rls_and_idempotent_opt_in():
    sql = MIGRATION.read_text().lower()
    assert "force row level security" in sql
    assert "revoke all on tcg.seller_hub_launch_waitlist" in sql
    assert "from public, anon, authenticated, service_role, tcg_api" in sql
    assert "tcg_private.register_seller_hub_interest" in sql
    assert "grant execute on function tcg_private.register_seller_hub_interest" in sql
    assert "on conflict (email) do update" in sql
    assert "where seller_hub_launch_waitlist.status = 'unsubscribed'" in sql
    assert "p_consent is distinct from true" in sql
    assert "consented_at" in sql and "consent_version" in sql


def test_frontend_uses_local_assets_and_explicit_prelaunch_disclosures():
    html = (ASSETS / "seller-hub-launch.html").read_text()
    js = (ASSETS / "seller-hub-launch.js").read_text()
    css = (ASSETS / "seller-hub-launch.css").read_text()
    assert html.count('<article class="feature-card') == 6
    assert 'id="waitlist-consent"' in html and 'type="checkbox" required' in html
    assert 'method="post" action="/api/v1/public/seller-hub/waitlist"' in html
    assert "full Seller Hub is still in development" in html
    assert "doesn't create a seller account" in html
    assert '/assets/brand-assets/seller-hub-approved.webp' in html
    assert 'fetch(\'/api/v1/public/seller-hub/waitlist\'' in js
    assert "response.ok" in js
    assert "credentials: 'omit'" in js
    assert "@media(max-width:760px)" in css
    assert "prefers-reduced-motion" in css


def test_email_signup_normalisation_and_consent_required():
    signup = SellerHubLaunchSignup(email=" USER@Example.COM ", consent=True)
    assert signup.email == "user@example.com"
    assert signup.interest == "CARDS"
    with pytest.raises(Exception):
        SellerHubLaunchSignup(email="user@example.com", consent=False)
