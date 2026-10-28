"""Asking estimates remain a separate, exact-identity, short-lived display tier."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.reference_asking_display import (
    ASKING_DISPLAY_SQL, add_asking_estimates, asking_estimate_view,
)

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
IDENTITY = {"name": "Energy Marker", "set_id": "PR", "card_number": "E-141",
            "set_name": "Promos", "finish": "Normal", "rarity": "Promo"}


def record(**changes):
    return {"key": "r:one", "method_version": "EBAY_UK_RAW_ASK_V1", "currency": "GBP",
            "estimate_minor": 700, "estimate_high_minor": 900, "listing_count": 4, "seller_count": 3,
            "observed_at": NOW - timedelta(hours=1), "expires_at": NOW + timedelta(days=2),
            "reference_identity": dict(IDENTITY), "current_identity": dict(IDENTITY),
            "evidence": {"source": "EBAY_OFFICIAL_BROWSE", "shipping_basis": "ITEM_PLUS_SHIPPING",
                         "shipping_context": "CONFIGURED_SHOP_POSTCODE_BENCHMARK",
                         "condition": "Near Mint", "finish": "Normal"},
            **changes}


def product(**changes):
    return {"key": "r:one", "provider": "Bandai", "system_code": "DRAGON_BALL_SUPER_FUSION_WORLD",
            "language": "English", "provider_id": "E-141", "source_kind": "REFERENCE",
            "product_type": "CARD", "market_value_minor": None, "market_value_high_minor": None,
            "market_quotes": [], "market_refresh_needed": False, **changes}


def test_public_view_exposes_asking_provenance_without_market_value():
    value = asking_estimate_view(record(evidence=json.dumps(record()["evidence"])), now=NOW)
    assert value["status"] == "ASKING_PRICE_ESTIMATE"
    assert value["estimate_minor"] == 700
    assert value["listing_count"] == 4 and value["seller_count"] == 3
    assert (value["condition"], value["finish"]) == ("Near Mint", "Normal")
    assert value["physical_valuation_eligible"] is False
    assert value["shipping_context"] == "CONFIGURED_SHOP_POSTCODE_BENCHMARK"
    assert value["recommended_retail_minor"] is None
    assert "market_value_minor" not in value and "evidence" not in value


def test_shipping_context_is_required_and_private_destination_never_exposed():
    for context in (None, "", "BUYER_POSTCODE"):
        evidence = {**record()["evidence"], "shipping_context": context}
        assert asking_estimate_view(record(evidence=evidence), now=NOW) is None
    evidence = {**record()["evidence"], "shipping_postcode": "private", "shipping_postcode_hash": "private-hash"}
    view = asking_estimate_view(record(evidence=evidence), now=NOW)
    assert "private" not in json.dumps(view, default=str)
    assert "a.evidence->>'shipping_context'='CONFIGURED_SHOP_POSTCODE_BENCHMARK'" in ASKING_DISPLAY_SQL


@pytest.mark.parametrize("changes", [
    {"currency": "USD"}, {"method_version": "FUTURE_METHOD"},
    {"estimate_minor": 0}, {"estimate_minor": True}, {"estimate_high_minor": 699},
    {"listing_count": 2}, {"seller_count": 2}, {"seller_count": 5},
    {"observed_at": NOW + timedelta(seconds=1)},
    {"observed_at": NOW - timedelta(days=3, seconds=1)},
    {"expires_at": NOW}, {"expires_at": NOW + timedelta(days=4)},
    {"observed_at": NOW.replace(tzinfo=None)}, {"observed_at": "bad"},
    {"evidence": {}}, {"evidence": "not json"},
    {"evidence": {**record()["evidence"], "shipping_basis": "ITEM_ONLY"}},
    {"evidence": {**record()["evidence"], "finish": "Unknown"}},
    {"current_identity": {**IDENTITY, "finish": "Foil"}},
    {"current_identity": {**IDENTITY, "rarity": "Secret Rare"}},
    {"reference_identity": None},
])
def test_unusable_or_changed_printing_cache_is_hidden(changes):
    assert asking_estimate_view(record(**changes), now=NOW) is None


class Connection:
    def __init__(self, records):
        self.records, self.calls = records, []

    async def fetch(self, query, keys, now):
        self.calls.append((query, json.loads(keys), now))
        return self.records


@pytest.mark.asyncio
async def test_fallback_is_page_bounded_and_preserves_all_legacy_values():
    rows = [product(shared_price={"status": "STALE", "market_value_minor": None, "last_known_minor": 500}),
            product(key="r:priced", market_value_minor=1200),
            product(key="r:guide", shared_price={"status": "CATALOGUE_GUIDE", "market_value_minor": 1100}),
            product(key="s:one", source_kind="SEALED_REFERENCE", product_type="SEALED"),
            product(key="c:one", source_kind="CATALOGUE")]
    original = copy.deepcopy(rows)
    connection = Connection([record()])
    result = await add_asking_estimates(connection, rows, now=NOW)
    assert rows == original
    assert result[0]["asking_price_estimate"]["estimate_minor"] == 700
    assert [{k: v for k, v in row.items() if k != "asking_price_estimate"} for row in result] == original
    assert [x["key"] for x in connection.calls[0][1]] == ["r:one"]
    assert "current_identity" in ASKING_DISPLAY_SQL
    assert "'finish',r.finish,'rarity',r.rarity" in ASKING_DISPLAY_SQL


@pytest.mark.asyncio
async def test_no_request_when_all_products_have_stronger_reference_values():
    connection = Connection([])
    row = product(market_value_minor=1200, asking_price_estimate={"estimate_minor": 700})
    result = await add_asking_estimates(connection, [row], now=NOW)
    assert connection.calls == []
    assert "asking_price_estimate" not in result[0]


@pytest.mark.asyncio
async def test_expired_cache_does_not_restore_previous_asking_object():
    connection = Connection([record(expires_at=NOW)])
    result = await add_asking_estimates(connection, [product(asking_price_estimate={"estimate_minor": 700})], now=NOW)
    assert "asking_price_estimate" not in result[0]
