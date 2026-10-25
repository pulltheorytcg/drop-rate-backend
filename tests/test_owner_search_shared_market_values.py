"""Owner-scoped manual correction must use the same shared GBP reference for everyone.

No production prices, inventory or cross-owner data are written by these tests.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import owner_portal_api


ROOT = Path(__file__).resolve().parents[1]


def test_owner_manual_search_requires_exact_reference_evidence_and_explicit_source():
    code = (ROOT / "backend/app/owner_portal_api.py").read_text()
    section = code[code.index('@router.get("/catalogue-search")'):code.index('@router.get("/inventory")')]
    assert "tcg.catalogue_reference_value_v2(" in section
    assert "tcg.recognition_catalogue_reference_value(" not in section
    assert "tcg.reference_market_prices ref_market" in section
    assert "tcg.reference_catalogue_prices ref_catalogue" in section
    assert "ref_market.quotes->0->>'reference_language'=c.language" in section
    assert "ref_market.quotes->0->'reference_identity'=jsonb_build_object(" in section
    assert "ref_catalogue.quotes->0->'reference_identity'=jsonb_build_object(" in section
    assert "m.match_status='VERIFIED'" in section
    assert "ref_market.pricing_updated_at between now()-interval '7 days' and now()" in section
    assert "ref_catalogue.pricing_updated_at between now()-interval '7 days' and now()" in section
    assert "where id=$1 and owner_id=$2" in section
    assert "item[\"recommended_retail_minor\"] = None" in section
    assert "from tcg.inventory_items" not in section
    ui = (ROOT / "backend/app/static/owner-recognition.js").read_text()
    # A card has a single customer-facing GBP label, irrespective of source.
    # The API still retains its exact evidence and source classification.
    assert ui.count('`Value: ${formatMoney(row.market_value_minor)}`') == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("value,expected_status", [(9, "REFERENCE_ESTIMATE"), (None, "NO_VERIFIED_VALUATION")])
async def test_two_owners_get_same_reference_or_missing_state(monkeypatch, value, expected_status):
    """Only owner-authenticated runs are queried; value comes from global provider rows."""
    accessed = []

    class FakeConnection:
        async def fetchrow(self, query, *args):
            assert "where id=$1 and owner_id=$2" in query
            accessed.append(args[1])
            return {"id": args[0], "status": "NEEDS_REVIEW",
                    "system_code": "ONE_PIECE_CARD_GAME",
                    "ai_observation": {"language": "English"}}

        async def fetch(self, query, *args):
            if "with matching_cards as materialized" not in query:
                return []
            assert "tcg.reference_market_prices" in query
            assert "tcg.reference_catalogue_prices" in query
            return [{
                "provider": "Punk Records", "system_code": "ONE_PIECE_CARD_GAME",
                "language": "English", "provider_id": "OP09-106", "name": "Nico Olvia",
                "set_name": "EMPERORS IN THE NEW WORLD", "card_number": "OP09-106",
                "variant": "OP09-106", "rarity": "Common", "finish": "Normal",
                "image_url": None, "mapped_catalogue_id": None,
                "reference_market_value_minor": value,
                "reference_pricing_updated_at": datetime(2026, 10, 12, tzinfo=timezone.utc) if value else None,
                "reference_value_source": "CARDMARKET_BULK_SINGLES" if value else None,
            }]

    @asynccontextmanager
    async def fake_user_connection(pool, user_id, request_id):
        yield FakeConnection()

    monkeypatch.setattr(owner_portal_api, "user_connection", fake_user_connection)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                              state=SimpleNamespace(request_id="fixture"))
    results = []
    for _ in range(2):
        owner_id = uuid4()
        output = await owner_portal_api.owner_catalogue_search(
            request=request, user=SimpleNamespace(user_id=uuid4()),
            access={"owner_id": owner_id},
            q="OP09-106", limit=12, include_reference=True, run_id=uuid4())
        assert len(output["items"]) == 1
        row = output["items"][0]
        assert row["source_kind"] == "REFERENCE"
        assert row["requires_materialization"] is True
        assert row["market_value_minor"] == value
        assert row["pricing_status"] == expected_status
        assert row["recommended_retail_minor"] is None
        assert row["market_value_source"] == ("CARDMARKET_BULK_SINGLES" if value else None)
        results.append((row["market_value_minor"], row["pricing_status"], row["market_value_source"]))
    assert results[0] == results[1]
    assert len(set(accessed)) == 2
