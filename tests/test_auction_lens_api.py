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
    seen = {"readonly": [], "hints": 0}
    app = FastAPI()
    app.state.db_pool = object()

    @app.middleware("http")
    async def id_middleware(request: Request, call_next):
        request.state.request_id = "pilot-request"
        return await call_next(request)

    app.include_router(api.router)
    app.dependency_overrides[require_user] = lambda: AuthenticatedUser(
        user_id=uuid4(), session_id=None
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
