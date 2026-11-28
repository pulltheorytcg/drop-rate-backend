"""Asking-derived reference Market Values retain exact identity and source basis."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.reference_asking_display import (
    ASKING_DISPLAY_SQL, ASKING_MARKET_VALUE_SOURCE, ASKING_MARKET_VALUE_BASIS,
    add_asking_estimates, asking_estimate_view, asking_market_value_fields,
)

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
IDENTITY = {"name": "Energy Marker", "set_id": "PR", "card_number": "E-141",
            "set_name": "Promos", "finish": "Normal", "rarity": "Promo"}
MATCHING_EVIDENCE = {"provider_variant": None, "variant_title_terms": None,
                     "set_title_terms": None, "set_name": None}


def record(**changes):
    return {"key": "r:one", "method_version": "EBAY_UK_RAW_ASK_V1", "currency": "GBP",
            "estimate_minor": 700, "estimate_high_minor": 900, "listing_count": 4, "seller_count": 3,
            "observed_at": NOW - timedelta(hours=1), "expires_at": NOW + timedelta(days=2),
            "reference_identity": dict(IDENTITY), "current_identity": dict(IDENTITY),
            "current_matching_reference_evidence": dict(MATCHING_EVIDENCE),
            "current_reference_group_count": 1,
            "evidence": {"source": "EBAY_OFFICIAL_BROWSE", "shipping_basis": "ITEM_PLUS_SHIPPING",
                         "shipping_context": "CONFIGURED_SHOP_POSTCODE_BENCHMARK",
                         "matching_reference_evidence": dict(MATCHING_EVIDENCE),
                         "reference_group_count": 1,
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
    {"current_matching_reference_evidence": {**MATCHING_EVIDENCE, "provider_variant": "Parallel"}},
    {"current_reference_group_count": 2},
    {"current_matching_reference_evidence": None},
    {"evidence": {**record()["evidence"], "reference_group_count": True}},
    {"evidence": {**record()["evidence"], "reference_group_count": 0}},
    {"evidence": {**record()["evidence"], "matching_reference_evidence": {}}},
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
    assert result[0]["market_value_minor"] == 700
    assert result[0]["market_value_high_minor"] == 900
    assert result[0]["market_value_source"] == ASKING_MARKET_VALUE_SOURCE
    assert result[0]["market_value_basis"] == ASKING_MARKET_VALUE_BASIS
    assert result[0]["market_value_confidence"] == "LOW"
    assert result[0]["basis_condition"] == "Near Mint"
    assert result[0]["market_value_evidence"] == {
        "provider": "EBAY_OFFICIAL_BROWSE",
        "method_version": "EBAY_UK_RAW_ASK_V1",
        "currency": "GBP", "listing_count": 4, "independent_seller_count": 3,
        "shipping_basis": "ITEM_PLUS_SHIPPING",
        "basis_type": ASKING_MARKET_VALUE_BASIS, "completed_sales_used": 0,
        "cardmarket_check": {"status": "NO_CARDMARKET_PRICE"},
    }
    assert "asking_price_estimate" not in result[0]
    assert result[1:] == original[1:]
    assert rows == original  # Read-only projection; never mutate source rows.
    # Every raw reference card on the page is asked about in one bounded read;
    # sealed and canonical rows never are.
    assert [x["key"] for x in connection.calls[0][1]] == ["r:one", "r:priced", "r:guide"]
    assert len(connection.calls) == 1
    assert "current_identity" in ASKING_DISPLAY_SQL
    assert "'finish',r.finish,'rarity',r.rarity" in ASKING_DISPLAY_SQL


@pytest.mark.asyncio
async def test_a_priced_card_without_asking_evidence_keeps_its_value():
    connection = Connection([])
    row = product(market_value_minor=1200, asking_price_estimate={"estimate_minor": 700})
    result = await add_asking_estimates(connection, [row], now=NOW)
    assert len(connection.calls) == 1
    assert result[0]["market_value_minor"] == 1200
    assert "market_value_source" not in result[0] or result[0]["market_value_source"] != ASKING_MARKET_VALUE_SOURCE
    assert "asking_price_estimate" not in result[0]


def guide_row(guide_minor, **changes):
    return product(**{"market_value_minor": guide_minor, "market_value_high_minor": guide_minor,
                      "market_value_source": "TCGDEX_CARDMARKET",
                      "pricing_updated_at": NOW - timedelta(days=1), **changes})


@pytest.mark.asyncio
@pytest.mark.parametrize("guide_minor,asking_minor", [
    (4000, 4000), (4000, 4400), (4000, 7900), (4000, 2100), (56, 207), (100, 399), (500, 250)])
async def test_asking_average_that_agrees_with_cardmarket_is_the_value(guide_minor, asking_minor):
    # Owner rule (28 Nov 2026): asking average first, checked against Cardmarket.
    connection = Connection([record(estimate_minor=asking_minor, estimate_high_minor=asking_minor + 100)])
    result = await add_asking_estimates(connection, [guide_row(guide_minor)], now=NOW)
    assert result[0]["market_value_minor"] == asking_minor
    assert result[0]["market_value_source"] == ASKING_MARKET_VALUE_SOURCE
    assert result[0]["market_value_evidence"]["cardmarket_check"] == {
        "status": "AGREES", "asking_minor": asking_minor, "cardmarket_minor": guide_minor,
        "cardmarket_source": "TCGDEX_CARDMARKET"}
    assert "asking_price_estimate" not in result[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("guide_minor,asking_minor", [(4000, 20000), (4000, 8001), (4000, 1900), (100, 401)])
async def test_asking_average_that_disagrees_with_cardmarket_is_held(guide_minor, asking_minor):
    row = guide_row(guide_minor)
    connection = Connection([record(estimate_minor=asking_minor, estimate_high_minor=asking_minor + 100)])
    result = await add_asking_estimates(connection, [row], now=NOW)
    # The Cardmarket guide stays the value; the asking average is flagged context.
    assert {key: result[0][key] for key in row} == row
    held = result[0]["asking_price_estimate"]
    assert held["estimate_minor"] == asking_minor
    assert held["cardmarket_check"] == {
        "status": "DISAGREES", "asking_minor": asking_minor, "cardmarket_minor": guide_minor,
        "cardmarket_source": "TCGDEX_CARDMARKET"}


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"market_value_source": "TCGDEX_TCGPLAYER"},  # US prices are never the comparison
    {"market_value_source": "STORED_SNAPSHOT"},
    {"market_value_source": "UNRECOGNISED"},
    {"pricing_updated_at": NOW - timedelta(days=8)},  # an expired guide checks nothing
    {"market_value_minor": None, "market_value_source": None},
    {"shared_price": {"status": "AVAILABLE", "market_value_minor": 980}, "market_value_source": "STORED_SNAPSHOT"},
])
async def test_asking_average_comes_first_when_there_is_no_current_cardmarket_price(changes):
    connection = Connection([record(estimate_minor=20000, estimate_high_minor=20100)])
    result = await add_asking_estimates(connection, [guide_row(4000, **changes)], now=NOW)
    assert result[0]["market_value_minor"] == 20000
    assert result[0]["market_value_source"] == ASKING_MARKET_VALUE_SOURCE
    assert result[0]["market_value_evidence"]["cardmarket_check"] == {"status": "NO_CARDMARKET_PRICE"}


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [
    "TCGDEX_CARDMARKET", "TCGDEX_CARDMARKET_VARIANT", "CARDMARKET_BULK", "CARDMARKET_BULK_SINGLES",
    "CARDMARKET_CATALOGUE", "POKEWALLET_CARDMARKET_CATALOGUE", "POKEWALLET_DBS_CARDMARKET_CATALOGUE",
    "POKEWALLET_POKEMON_CARDMARKET_CATALOGUE"])
async def test_every_cardmarket_source_is_used_for_the_check(source):
    connection = Connection([record(estimate_minor=20000, estimate_high_minor=20100)])
    result = await add_asking_estimates(connection, [guide_row(4000, market_value_source=source)], now=NOW)
    assert result[0]["asking_price_estimate"]["cardmarket_check"]["cardmarket_source"] == source
    assert result[0]["market_value_source"] == source


@pytest.mark.asyncio
async def test_expired_cache_does_not_restore_previous_asking_object():
    connection = Connection([record(expires_at=NOW)])
    result = await add_asking_estimates(connection, [product(asking_price_estimate={"estimate_minor": 700})], now=NOW)
    assert "asking_price_estimate" not in result[0]


def test_asking_model_rejects_weak_or_corrupt_evidence():
    assert asking_market_value_fields(None) is None
    assert asking_market_value_fields({"status": "WRONG"}) is None
    normal = asking_estimate_view(record(), now=NOW)
    assert asking_market_value_fields({**normal, "seller_count": 2}) is None
    assert asking_market_value_fields({**normal, "estimate_minor": 0}) is None
    assert asking_market_value_fields({**normal, "estimate_high_minor": 600}) is None


@pytest.mark.asyncio
async def test_asking_market_value_is_never_applied_to_physical_or_sealed_products():
    connection = Connection([record()])
    rows = [
        product(source_kind="INVENTORY", inventory_code="INV-PKM-123456"),
        product(source_kind="SEALED_REFERENCE", product_type="SEALED"),
        product(source_kind="REFERENCE", product_type="CARD", grading_company="PSA", grade="10"),
    ]
    # The canonical-identity row can't be a physical slab target.
    # A graded physical inventory is rejected by source_kind regardless.
    rows[2]["source_kind"] = "INVENTORY"
    result = await add_asking_estimates(connection, rows, now=NOW)
    assert result == rows
    assert not connection.calls


@pytest.mark.asyncio
async def test_expired_asking_market_value_cannot_survive_rehydration():
    connection = Connection([record(expires_at=NOW)])
    old = product(market_value_minor=700, market_value_high_minor=900,
                  market_value_source=ASKING_MARKET_VALUE_SOURCE,
                  market_value_basis=ASKING_MARKET_VALUE_BASIS,
                  pricing_updated_at=NOW-timedelta(days=1),
                  basis_condition="Near Mint")
    out = await add_asking_estimates(connection, [old], now=NOW)
    assert out[0]["market_value_minor"] is None if "market_value_minor" in out[0] else True
    assert "market_value_source" not in out[0]
    assert "pricing_updated_at" not in out[0]


@pytest.mark.asyncio
async def test_five_independent_sellers_raise_confidence_but_not_sales_claim():
    connection = Connection([record(listing_count=7,seller_count=5)])
    result = await add_asking_estimates(connection, [product()], now=NOW)
    value = result[0]
    assert value["market_value_confidence"] == "MEDIUM"
    assert value["market_value_evidence"]["completed_sales_used"] == 0
    assert "store_price_minor" not in value
    assert "recommended_retail_minor" not in value



@pytest.mark.asyncio
@pytest.mark.parametrize(("legacy_minor", "asking_minor", "provider", "reference_id"), [
    (12, 249, "TCGdex", "sv03.5-004"),
    (56, 207, "Bandai Official", "OP17-103"),
])
async def test_current_verified_asking_supersedes_expired_legacy_guide(
        legacy_minor, asking_minor, provider, reference_id):
    """Regression: stale guide kept market_value_minor non-null and blocked cache.

    This affects production Charmander 151 and Katakuri OP17-103. The database
    guide value is not rewritten; this is solely the catalogue response view.
    """
    row = product(
        provider=provider, provider_id=reference_id,
        market_value_minor=legacy_minor, market_value_high_minor=legacy_minor,
        market_value_source="TCGDEX_TCGPLAYER",
        pricing_updated_at=NOW - timedelta(days=16),
        basis_condition="Raw · Cardmarket mixed-language guide",
    )
    previous = copy.deepcopy(row)
    connection = Connection([record(estimate_minor=asking_minor,
                                    estimate_high_minor=asking_minor + 100)])
    result = await add_asking_estimates(connection, [row], now=NOW)
    assert row == previous
    assert len(connection.calls) == 1
    assert len(connection.calls[0][1]) == 1
    assert result[0]["market_value_minor"] == asking_minor
    assert result[0]["market_value_high_minor"] == asking_minor + 100
    assert result[0]["market_value_source"] == ASKING_MARKET_VALUE_SOURCE
    assert result[0]["market_value_basis"] == ASKING_MARKET_VALUE_BASIS
    assert result[0]["market_value_evidence"]["completed_sales_used"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"source_kind": "INVENTORY"},
    {"source_kind": "CATALOGUE"},
    {"product_type": "SEALED"},
    {"product_type": "COMIC"},
    {"grading_company": "PSA", "grade": "10"},
    {"seal_status": "SEALED"},
])
async def test_asking_average_never_touches_stock_sealed_graded_or_non_card_rows(overrides):
    row = product(**{
        "market_value_minor": 56,
        "market_value_source": "TCGDEX_TCGPLAYER",
        "pricing_updated_at": NOW - timedelta(days=16),
        **overrides,
    })
    connection = Connection([record(estimate_minor=207)])
    result = await add_asking_estimates(connection, [row], now=NOW)
    assert result == [row]
    assert connection.calls == []


@pytest.mark.asyncio
async def test_expired_guide_without_valid_asking_does_not_invent_price():
    row = product(
        market_value_minor=56, market_value_source="TCGDEX_TCGPLAYER",
        pricing_updated_at=NOW - timedelta(days=16),
    )
    connection = Connection([record(current_identity={**IDENTITY, "card_number": "OTHER"})])
    result = await add_asking_estimates(connection, [row], now=NOW)
    assert result == [row]
    assert len(connection.calls) == 1
