"""Regression: an unmapped recognition candidate can reuse a shared reference quote."""
from uuid import uuid4

import pytest

from app.recognition import _candidate_review_payload, _run_payload
from app.catalogue_coverage import coverage_summary


def test_market_status_distinguishes_guide_from_exact_sale():
    base = dict(catalogue_id=None, source_kind="PROVIDER", reference_selection=None)
    for source in ("TCGDEX_CARDMARKET", "TCGDEX_CARDMARKET_VARIANT", "CARDMARKET_BULK_SINGLES", "CARDMARKET_CATALOGUE", "CARDMARKET_ESTIMATE"):
        result = _candidate_review_payload({**base, "market_value_minor": 132, "market_value_source": source})
        assert result["pricing_status"] == "REFERENCE_ESTIMATE"
        assert result["market_value_minor"] == 132
        assert result["catalogue_id"] is None
    assert _candidate_review_payload({**base, "market_value_minor": 132, "market_value_source": "STORED_SNAPSHOT"})["pricing_status"] == "AVAILABLE"
    assert _candidate_review_payload({**base, "market_value_minor": None, "market_value_source": "TCGDEX_CARDMARKET"})["pricing_status"] == "NO_VERIFIED_VALUATION"


@pytest.mark.asyncio
async def test_global_reference_value_reused_without_owned_inventory():
    run_id = uuid4()
    class FakeConnection:
        def __init__(self):
            self.sql = ""
        async def fetchrow(self, query, *args):
            return {"id": run_id, "status": "NEEDS_REVIEW", "owner_id": uuid4()}
        async def fetch(self, query, *args):
            if "from tcg.recognition_candidates rc" in query:
                self.sql = query
                return [dict(catalogue_id=None, source_kind="PROVIDER", market_value_minor=450,
                    market_value_source="CARDMARKET_BULK_SINGLES", reference_selection=None)]
            return []

    db = FakeConnection()
    response = await _run_payload(db, run_id)
    assert response["candidates"][0]["pricing_status"] == "REFERENCE_ESTIMATE"
    assert response["candidates"][0]["market_value_minor"] == 450
    assert "tcg.reference_market_prices" in db.sql
    assert "tcg.reference_catalogue_prices" in db.sql
    assert "tcg.catalogue_reference_value_v2(" in db.sql
    assert "ref_market.quotes->0->'reference_identity'" in db.sql
    assert "ref_catalogue.quotes->0->'reference_identity'" in db.sql
    assert "now()-interval '7 days'" in db.sql
    assert "not rc.hard_rejected" in db.sql
    assert "TCGDEX_TCGPLAYER" not in db.sql
    assert "from tcg.inventory_items" not in db.sql


def test_shared_coverage_is_independent_of_owner_and_never_counts_usd_as_gbp():
    evidence = [
        {"kind": "CARD", "system_code": "ONE_PIECE_CARD_GAME", "language": "English", "status": "REFERENCE_AVAILABLE", "products": 30},
        {"kind": "CARD", "system_code": "ONE_PIECE_CARD_GAME", "language": "English", "status": "PROVIDER_MAPPING_REQUIRED", "products": 70},
        {"kind": "CARD", "system_code": "POKEMON_TCG", "language": "English", "status": "US_CONTEXT_ONLY", "products": 4},
        {"kind": "SEALED", "system_code": "ONE_PIECE_CARD_GAME", "language": "Unknown", "status": "MIXED_LANGUAGE_GUIDE", "products": 8},
    ]
    summary = coverage_summary(evidence)
    assert summary == coverage_summary(list(reversed(evidence)))
    assert summary["by_kind"]["CARD"] == dict(total=104, priced=30, missing=74)
    assert summary["by_kind"]["SEALED"] == dict(total=8, priced=8, missing=0)
    assert summary["valuation_currency"] == "GBP"
