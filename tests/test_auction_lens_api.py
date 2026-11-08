"""Authenticated, opt-in Auction Lens pilot route: no real DB, no video storage."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth import AuthenticatedUser, require_user
from app import auction_lens_api as api


P_ID, M_ID = uuid4(), uuid4()
OBS = {
    "game": "Pokemon", "language": "English", "name": "Rapidash",
    "set_name": "Temporal Forces", "card_number": "048/162",
    "finish": "Normal", "object_type": "RAW_CARD",
}
PAYLOAD = {
    "generation": 8, "source": "OWN_VIDEO",
    "image_data_url": "data:image/jpeg;base64," + "A" * 180,
    "observed": OBS,
}
ROW = {
    "catalogue_id": P_ID, "media_asset_id": M_ID, "product_type": "CARD",
    "game": "Pokemon", "language": "English", "name": "Rapidash",
    "set_name": "Temporal Forces", "card_number": "048/162",
    "variant": "Normal", "approval_status": "APPROVED",
    "source_status": "ACTIVE", "rights_status": "VERIFIED",
}
HINT = {
    "catalogue_id": P_ID, "media_asset_id": M_ID, "similarity": 0.975,
    "trust_level": "VERIFIED",
}


class ReadOnlyConnection:
    def __init__(self, rows=None):
        self.rows = list(rows if rows is not None else [ROW])
        self.query_count = 0

    async def fetch(self, query, *args):
        self.query_count += 1
        assert "insert " not in query.casefold()
        assert "update " not in query.casefold()
        assert "delete " not in query.casefold()
        return self.rows

    async def execute(self, *_args, **_kwargs):
        raise AssertionError("Auction frame route must never write")


@pytest.fixture()
def pilot(monkeypatch):
    connection = ReadOnlyConnection()
    actor_id = uuid4()
    seen = {"readonly": [], "hints": 0, "actor_id": actor_id}
    # One exact signed-in test account; no implicit account-wide beta access.
    monkeypatch.setenv("TCG_AUCTION_LENS_BETA_USER_IDS", str(actor_id))
    app = FastAPI()
    app.state.db_pool = object()

    @app.middleware("http")
    async def id_middleware(request: Request, call_next):
        request.state.request_id = "pilot-request"
        return await call_next(request)

    app.include_router(api.router)
    app.dependency_overrides[require_user] = lambda: AuthenticatedUser(
        user_id=actor_id, session_id=None
    )

    @asynccontextmanager
    async def fake_user_connection(_pool, _actor, _req, *, readonly_snapshot=False):
        seen["readonly"].append(readonly_snapshot)
        yield connection

    async def fake_owner(_con):
        return {"id": uuid4()}

    async def fake_hints(_con, _hashes, **options):
        seen["hints"] += 1
        assert options["system_code"] == "POKEMON_TCG"
        return [dict(HINT)]

    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(recognition_max_image_bytes=900_000))
    monkeypatch.setattr(api, "user_connection", fake_user_connection)
    monkeypatch.setattr(api, "current_owner", fake_owner)
    monkeypatch.setattr(api, "decode_image_data_url",
                        lambda *args, **kwargs: SimpleNamespace(hashes=(1, 2)))
    monkeypatch.setattr(api, "discover_reference_candidate_hints", fake_hints)
    monkeypatch.setattr(api, "_enabled", lambda name:
                        name == "TCG_AUCTION_LENS_AUTHORISED_PILOT_ENABLED")
    return TestClient(app), connection, seen


def test_pilot_is_disabled_by_default_and_fails_closed(pilot, monkeypatch):
    client, con, seen = pilot
    monkeypatch.setattr(api, "_enabled", lambda _: False)
    result = client.post("/api/v1/auction-lens/pilot/resolve", json=PAYLOAD)
    assert result.status_code == 404
    assert con.query_count == 0 and seen["hints"] == 0


def test_authenticated_owned_video_returns_exact_identity_no_unlicensed_market_value(pilot):
    client, con, seen = pilot
    result = client.post("/api/v1/auction-lens/pilot/resolve", json={
        **PAYLOAD, "confirmed_raw_condition": "Near Mint",
    })
    assert result.status_code == 200
    assert result.json()["generation"] == 8
    assert result.json()["decision"] == "EXACT"
    assert result.json()["identityKey"].startswith("card:")
    assert "value" not in result.json()
    assert con.query_count == 1 and seen["hints"] == 1
    assert seen["readonly"] == [True]


def test_low_visual_evidence_cannot_expose_price(pilot, monkeypatch):
    client, con, _seen = pilot

    async def low_hints(*_args, **_kwargs):
        return [{**HINT, "similarity": 0.59}]

    monkeypatch.setattr(api, "discover_reference_candidate_hints", low_hints)
    result = client.post("/api/v1/auction-lens/pilot/resolve", json=PAYLOAD)
    assert result.status_code == 200
    assert result.json() == {"generation": 8, "decision": "CHECK_VERSION"}


@pytest.mark.parametrize("source", ["WHATNOT_LIVE", "EBAY_LIVE", "SCRAPED_STREAM", ""])
def test_unapproved_source_name_cannot_be_selected(pilot, source):
    client, _con, _seen = pilot
    assert client.post("/api/v1/auction-lens/pilot/resolve",
                       json={**PAYLOAD, "source": source}).status_code == 422


def test_explicit_licence_gate_is_separate_from_pilot_gate(pilot, monkeypatch):
    client, _con, _seen = pilot
    called = []

    async def permitted_market(_con, *, catalogue_id, now):
        called.append(catalogue_id)
        return {"marketValueMinor": 1277, "currency": "GBP",
                "source": "Eligible UK sold", "valuationEligible": True,
                "expiresAtMs": int((now + timedelta(days=1)).timestamp() * 1000)}

    monkeypatch.setattr(api, "_eligible_uk_value", permitted_market)
    monkeypatch.setattr(api, "_enabled", lambda _: True)
    without_confirmed_condition = client.post(
        "/api/v1/auction-lens/pilot/resolve", json=PAYLOAD
    ).json()
    assert "value" not in without_confirmed_condition
    assert called == []
    confirmed = client.post(
        "/api/v1/auction-lens/pilot/resolve",
        json={**PAYLOAD, "confirmed_raw_condition": "Near Mint"}
    ).json()
    assert confirmed["value"]["marketValueMinor"] == 1277
    assert called == [P_ID]


def test_market_value_selection_rejects_guides_or_expired_evidence(monkeypatch):
    now = datetime(2026, 11, 7, 13, tzinfo=timezone.utc)
    con = ReadOnlyConnection(rows=[])
    monkeypatch.setattr(api, "resolve_reference_value", lambda *_a, **_kw: {
        "status": "REFERENCE_ESTIMATE", "method": api.SOLD,
        "market_value_minor": 1277, "checked_at": now,
    })
    import asyncio
    assert asyncio.run(api._eligible_uk_value(con, catalogue_id=P_ID, now=now)) is None
    monkeypatch.setattr(api, "resolve_reference_value", lambda *_a, **_kw: {
        "status": "AVAILABLE", "method": api.SOLD,
        "market_value_minor": 1277, "checked_at": now - timedelta(days=8),
    })
    assert asyncio.run(api._eligible_uk_value(con, catalogue_id=P_ID, now=now)) is None


def test_slow_index_never_hangs_auction_or_returns_stale_identity(pilot, monkeypatch):
    client, _connection, _seen = pilot
    monkeypatch.setattr(api, "_LOOKUP_TIMEOUT_SECONDS", 0.002)

    async def delayed_hints(*_args, **_kwargs):
        await asyncio.sleep(0.025)
        return [dict(HINT)]

    monkeypatch.setattr(api, "discover_reference_candidate_hints", delayed_hints)
    response = client.post("/api/v1/auction-lens/pilot/resolve", json=PAYLOAD)
    assert response.status_code == 200
    assert response.json() == {"generation": 8, "decision": "CHECK_VERSION"}

    # A timed-out request must release the shared concurrency slot.
    monkeypatch.setattr(api, "_LOOKUP_TIMEOUT_SECONDS", 2.5)

    async def ready_hints(*_args, **_kwargs):
        return [dict(HINT)]

    monkeypatch.setattr(api, "discover_reference_candidate_hints", ready_hints)
    next_result = client.post("/api/v1/auction-lens/pilot/resolve", json=PAYLOAD)
    assert next_result.status_code == 200
    assert next_result.json()["decision"] == "EXACT"


def test_sold_market_value_expires_at_earlier_comparable_or_refresh_window(monkeypatch):
    now = datetime(2026, 11, 7, 16, tzinfo=timezone.utc)
    evidence_at = now - timedelta(hours=1)
    oldest_sale = now - timedelta(days=89)
    snapshot_id = uuid4()
    con = ReadOnlyConnection(rows=[{
        "snapshot_id": snapshot_id,
        "oldest_sale_at": oldest_sale,
    }])
    monkeypatch.setattr(api, "resolve_reference_value", lambda *_a, **_kw: {
        "status": "AVAILABLE", "method": api.SOLD,
        "market_value_minor": 3200, "checked_at": evidence_at,
        "snapshot_id": snapshot_id,
    })
    value = asyncio.run(api._eligible_uk_value(con, catalogue_id=P_ID, now=now))
    assert value["marketValueMinor"] == 3200
    assert value["currency"] == "GBP"
    assert value["basis"] == "English · Near Mint · raw"
    assert value["evidenceAtMs"] == int(evidence_at.timestamp() * 1000)
    assert value["expiresAtMs"] == int((oldest_sale + timedelta(days=90)).timestamp() * 1000)


def test_pilot_quote_uses_server_market_evidence_only(pilot, monkeypatch):
    client, _connection, _seen = pilot
    now = datetime.now(timezone.utc)
    seen = []

    async def approved_market(_con, *, catalogue_id, now):
        seen.append(catalogue_id)
        return {
            "marketValueMinor": 10000, "currency": "GBP",
            "source": "Verified UK sold Market Value",
            "evidenceAtMs": int((now - timedelta(hours=1)).timestamp() * 1000),
            "expiresAtMs": int((now + timedelta(hours=1)).timestamp() * 1000),
            "valuationEligible": True,
        }

    monkeypatch.setattr(api, "_eligible_uk_value", approved_market)
    monkeypatch.setattr(api, "_enabled", lambda _: True)
    quote = {
        "lot_ref": "consented-own-video-lot-1", "status": "ACTIVE",
        "currency": "GBP", "bid_minor": 5000,
        "shipping_minor": 600, "buyer_fees_minor": 900,
        "import_tax_minor": 0, "additional_costs_minor": 0,
        "bid_observed_at": now.isoformat(),
    }
    result = client.post("/api/v1/auction-lens/pilot/resolve", json={
        **PAYLOAD, "confirmed_raw_condition": "Near Mint", "quote": quote,
    })
    assert result.status_code == 200
    body = result.json()
    assert body["comparison"]["status"] == "UNDER_MARKET"
    assert body["comparison"]["allInMinor"] == 6500
    assert body["comparison"]["bidExpiresAtMs"] > int(now.timestamp() * 1000)
    assert body["comparison"]["differenceMinor"] == 3500
    assert body["value"]["marketValueMinor"] == 10000
    assert seen == [P_ID]

    # A buyer can supply observations, but cannot supply a replacement
    # market value, source or expired price in the quote.
    injected = client.post("/api/v1/auction-lens/pilot/resolve", json={
        **PAYLOAD, "quote": {**quote, "marketValueMinor": 999999},
    })
    assert injected.status_code == 422


def test_pilot_quote_never_leaks_bargain_when_value_or_charges_unknown(pilot, monkeypatch):
    client, _con, _seen = pilot
    now = datetime.now(timezone.utc)
    quote = {
        "lot_ref": "consented-own-video-lot-1", "bid_minor": 5000,
        "shipping_minor": 0, "buyer_fees_minor": 0,
        "import_tax_minor": 0, "additional_costs_minor": 0,
        "bid_observed_at": now.isoformat(),
    }
    # Pilot enabled but no display licence and no confirmed raw condition.
    body = client.post("/api/v1/auction-lens/pilot/resolve", json={
        **PAYLOAD, "quote": quote,
    }).json()
    assert body["comparison"] == {"status": "NO_CURRENT_MARKET_VALUE"}
    assert "value" not in body

    async def approved_market(_con, *, catalogue_id, now):
        return {
            "marketValueMinor": 10000, "currency": "GBP",
            "source": "Verified UK sold Market Value",
            "evidenceAtMs": int((now - timedelta(hours=1)).timestamp() * 1000),
            "expiresAtMs": int((now + timedelta(hours=1)).timestamp() * 1000),
            "valuationEligible": True,
        }
    monkeypatch.setattr(api, "_eligible_uk_value", approved_market)
    monkeypatch.setattr(api, "_enabled", lambda _: True)
    body = client.post("/api/v1/auction-lens/pilot/resolve", json={
        **PAYLOAD, "confirmed_raw_condition": "Near Mint",
        "quote": {**quote, "shipping_minor": None},
    }).json()
    assert body["comparison"] == {"status": "CHARGES_UNKNOWN"}
    assert body["value"]["marketValueMinor"] == 10000


@pytest.mark.parametrize("invalid_quote", [
    {"currency": "USD"},
    {"bid_minor": -1},
    {"bid_minor": True},
    {"shipping_minor": -1},
    {"bid_observed_at": "2026-11-08T15:00:00"},
])
def test_pilot_quote_rejects_invalid_currency_amounts_or_naive_time(pilot, invalid_quote):
    client, _con, _seen = pilot
    quote = {
        "lot_ref": "own-video-lot", "bid_minor": 5000,
        "bid_observed_at": datetime.now(timezone.utc).isoformat(),
    }
    result = client.post("/api/v1/auction-lens/pilot/resolve", json={
        **PAYLOAD, "quote": {**quote, **invalid_quote},
    })
    assert result.status_code == 422


def test_beta_allowlist_is_closed_by_default_and_does_not_decode_unapproved_frames(
    pilot, monkeypatch,
):
    client, connection, seen = pilot

    def forbidden_decode(*_args, **_kwargs):
        raise AssertionError("Must not decode an excluded user's image")

    monkeypatch.setattr(api, "decode_image_data_url", forbidden_decode)
    # Pilot flag alone is not permission to access a private scanner.
    monkeypatch.delenv("TCG_AUCTION_LENS_BETA_USER_IDS")
    response = client.post("/api/v1/auction-lens/pilot/resolve", json=PAYLOAD)
    assert response.status_code == 404
    assert connection.query_count == 0 and seen["hints"] == 0
    assert client.get("/api/v1/auction-lens/pilot/access").status_code == 404

    # One other real UUID, but not the currently signed-in account.
    monkeypatch.setenv("TCG_AUCTION_LENS_BETA_USER_IDS", str(uuid4()))
    assert client.post("/api/v1/auction-lens/pilot/resolve", json=PAYLOAD).status_code == 404
    assert connection.query_count == 0


@pytest.mark.parametrize("allowlist", [
    "",
    "not-a-uuid",
    "00000000-0000-0000-0000-000000000001,broken",
    "00000000-0000-0000-0000-000000000001,",
    "00000000-0000-0000-0000-000000000001,,00000000-0000-0000-0000-000000000002",
    "00000000-0000-0000-0000-000000000001,00000000-0000-0000-0000-000000000001",
    ",".join(str(uuid4()) for _ in range(26)),
])
def test_malformed_or_overlarge_allowlist_fails_closed(pilot, monkeypatch, allowlist):
    client, connection, _seen = pilot
    monkeypatch.setenv("TCG_AUCTION_LENS_BETA_USER_IDS", allowlist)
    assert client.get("/api/v1/auction-lens/pilot/access").status_code == 404
    assert client.post("/api/v1/auction-lens/pilot/resolve", json=PAYLOAD).status_code == 404
    assert connection.query_count == 0


def test_entitlement_endpoint_only_returns_boolean_no_peer_ids(pilot):
    client, connection, seen = pilot
    response = client.get("/api/v1/auction-lens/pilot/access")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "footage_scope": "OWN_OR_EXPLICITLY_AUTHORISED_VIDEO",
        "uk_sold_market_display_enabled": False,
    }
    assert seen["readonly"] == [True]
    # No other tester's identity or count of approved accounts leaks.
    assert "actor_id" not in response.text
    assert str(seen["actor_id"]) not in response.text
    assert connection.query_count == 0


def test_disabling_pilot_kills_entitlement_and_resolution_for_all_users(pilot, monkeypatch):
    client, connection, seen = pilot
    monkeypatch.setattr(api, "_enabled", lambda _: False)
    assert client.get("/api/v1/auction-lens/pilot/access").status_code == 404
    assert client.post("/api/v1/auction-lens/pilot/resolve", json=PAYLOAD).status_code == 404
    assert connection.query_count == 0 and seen["readonly"] == []


def test_beta_cannot_be_bypassed_by_user_id_in_request_body_or_headers(pilot, monkeypatch):
    client, connection, seen = pilot
    other = uuid4()
    monkeypatch.setenv("TCG_AUCTION_LENS_BETA_USER_IDS", str(other))
    result = client.post("/api/v1/auction-lens/pilot/resolve", json={
        **PAYLOAD, "user_id": str(other), "email": "tester@example.invalid"
    }, headers={"X-Owner-Id": str(other), "X-Auction-Beta": "true"})
    assert result.status_code == 404
    assert connection.query_count == 0 and seen["hints"] == 0


def test_allowlist_accepts_two_selected_users_but_not_every_owner(pilot, monkeypatch):
    client, _con, seen = pilot
    owner_id = seen["actor_id"]
    monkeypatch.setenv("TCG_AUCTION_LENS_BETA_USER_IDS", f"{owner_id},{uuid4()}")
    assert client.get("/api/v1/auction-lens/pilot/access").status_code == 200
    assert api._beta_allowed(uuid4()) is False
