from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib

import pytest

from backend.app.uk_eu_market_estimate import (
    IDENTITY_FIELDS, METHOD, REFERENCE_KEYS, estimate_uk_eu_market,
)


NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def inputs(prices=(1000, 1100, 1200), *, guide_value=1000, shipping=200):
    reference = {
        "provider": "TCGdex", "system_code": "POKEMON_TCG", "language": "English",
        "provider_id": "base1-4", "name": "Charizard", "set_id": "base1",
        "card_number": "4/102", "set_name": "Base Set", "finish": "Holofoil", "rarity": "Rare",
    }
    identity = {key: reference[key] for key in IDENTITY_FIELDS}
    comparables = [{
        "item_id": str(1000 + index), "seller_hash": hashlib.sha256(f"seller-{index}".encode()).hexdigest(),
        "price_gbp_minor": price, "shipping_gbp_minor": shipping,
        "delivered_gbp_minor": price + shipping, "observed_at": NOW.isoformat(),
        "condition": "Near Mint", "finish": "Holo",
        "match_proof": {"game": "POKEMON_TCG", "language": "english", "card_number": "4/102"},
        "listing_evidence": {"acquisition": "GET_ITEM", "condition_id": "4000"},
    } for index, price in enumerate(prices)]
    report = {
        "status": "READY", "source": "EBAY_OFFICIAL_BROWSE", "method_version": "EBAY_UK_RAW_ASK_V1",
        "basis": "ASKING_PRICE_ESTIMATE", "currency": "GBP", "condition_basis": "RAW_NEAR_MINT_OR_MINT",
        "identity": deepcopy(identity), "selected_finish": "Holo", "observed_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=3)).isoformat(), "comparables": comparables,
        "estimate_minor": 999999, "sample_count": 999, "seller_count": 999,
    }
    guide = {
        "source": "CARDMARKET", "source_product_id": "12345", "source_field": "trend",
        "currency": "GBP", "shipping_basis": "ITEM_ONLY", "price_gbp_minor": guide_value,
        "observed_at": NOW.isoformat(), "reference_identity": deepcopy(identity),
        "reference_key": {key: reference[key] for key in REFERENCE_KEYS}, "finish": "Holofoil",
        "condition_specific": False, "language_specific": False,
        "provenance": {"source": "TCGDEX_CARDMARKET", "product_id": "12345",
                       "original_currency": "EUR", "original_minor": 1250,
                       "fx_rate_to_gbp": "0.8", "fx_source": "ECB_EURO_REFERENCE_RATES"},
    }
    return reference, report, guide


def calculate(values, *, now=NOW):
    return estimate_uk_eu_market(*values, now=now)


def test_combines_actual_item_evidence_with_guide_not_delivered_summary_or_declared_counts():
    values = inputs()
    result = calculate(values)
    assert result["status"] == "READY"
    assert result["estimate_minor"] == 1050  # UK item median 1100 + EU guide 1000.
    assert result["source_count"] == 2
    assert result["observation_count"] == 4
    assert result["sold_observation_count"] == 0
    assert result["confidence"] == .5
    assert result["observation_type"] == "DERIVED_NOT_SOLD"
    assert result["physical_valuation_eligible"] is False
    assert result["auto_publish_eligible"] is False
    assert result["condition_specific"] is False
    assert result["language_specific"] is False
    assert result["recommended_retail_minor"] is None
    assert result["evidence"]["sources"][0]["observation_type"] == "ACTIVE"
    assert result["evidence"]["sources"][1]["observation_type"] == "PRICE_GUIDE"


def test_changing_shipping_cannot_inflate_item_only_blend():
    assert calculate(inputs(shipping=0))["estimate_minor"] == calculate(inputs(shipping=5000))["estimate_minor"]


def test_item_outlier_removal_runs_again_independently_of_delivered_report():
    result = calculate(inputs((1000, 1100, 1200, 100000), guide_value=1100))
    assert result["status"] == "READY"
    assert result["estimate_minor"] == 1100
    assert result["observation_count"] == 4
    assert result["evidence"]["excluded_browse_count"] == 1


def test_duplicate_sellers_cannot_satisfy_minimum_or_inflate_confidence():
    values = inputs()
    values[1]["comparables"][2]["seller_hash"] = values[1]["comparables"][0]["seller_hash"]
    assert calculate(values)["status"] == "INSUFFICIENT_INDEPENDENT_LISTINGS"


def test_repeated_same_listing_never_counts_twice():
    values = inputs()
    values[1]["comparables"] += [deepcopy(values[1]["comparables"][0])] * 40
    result = calculate(values)
    assert result["status"] == "READY"
    assert result["observation_count"] == 4
    assert result["confidence"] == .5


def test_conflicting_provider_id_quarantines_both_records():
    values = inputs()
    conflicting = deepcopy(values[1]["comparables"][0])
    conflicting["price_gbp_minor"] = 1050
    conflicting["delivered_gbp_minor"] = 1250
    values[1]["comparables"].append(conflicting)
    result = calculate(values)
    assert result["status"] == "INSUFFICIENT_INDEPENDENT_LISTINGS"


@pytest.mark.parametrize("price", [True, 0, -1, 1.0, float("nan"), float("inf"), 1_000_000_000_001])
def test_invalid_guide_price_is_rejected(price):
    values = inputs()
    values[2]["price_gbp_minor"] = price
    assert calculate(values)["status"] == "INVALID_CARDMARKET_GUIDE"


@pytest.mark.parametrize("price", [True, 0, -1, 1.0, float("nan"), float("inf"), 1_000_000_000_001])
def test_invalid_browse_price_cannot_sneak_into_three_seller_minimum(price):
    values = inputs()
    values[1]["comparables"][0]["price_gbp_minor"] = price
    assert calculate(values)["status"] == "INSUFFICIENT_INDEPENDENT_LISTINGS"


@pytest.mark.parametrize("field,value", [
    ("source", "DROP_RATE_COMPUTED_MARKET_V1"), ("currency", "EUR"),
    ("shipping_basis", "ITEM_PLUS_SHIPPING"), ("condition_specific", True),
    ("language_specific", True), ("source_product_id", ""), ("source_field", None),
    ("provenance", []),
])
def test_invalid_guide_contract_fails_closed(field, value):
    values = inputs()
    values[2][field] = value
    assert calculate(values)["status"] == "INVALID_CARDMARKET_GUIDE"


@pytest.mark.parametrize("target,field,value", [
    ("reference_identity", "name", "Blastoise"),
    ("reference_identity", "set_id", "base2"),
    ("reference_identity", "card_number", "4/130"),
    ("reference_identity", "rarity", "Common"),
    ("reference_key", "language", "Japanese"),
    ("reference_key", "provider_id", "base1-2"),
])
def test_guide_identity_cannot_transfer_between_prints(target, field, value):
    values = inputs()
    values[2][target][field] = value
    assert calculate(values)["status"] == "REFERENCE_IDENTITY_MISMATCH"


def test_changed_reference_invalidates_both_cached_sources():
    values = inputs()
    values[0]["finish"] = "Reverse Holofoil"
    assert calculate(values)["status"] == "REFERENCE_IDENTITY_MISMATCH"


def test_alternate_finish_cannot_be_blended():
    values = inputs()
    values[2]["finish"] = "Reverse Holofoil"
    assert calculate(values)["status"] == "FINISH_MISMATCH"


@pytest.mark.parametrize("field,value", [
    ("status", "INSUFFICIENT_COMPARABLES"), ("source", "EBAY_SCRAPED"),
    ("basis", "SOLD"), ("currency", "USD"), ("condition_basis", "GRADED_PSA_10"),
])
def test_unsupported_browse_report_is_rejected(field, value):
    values = inputs()
    values[1][field] = value
    assert calculate(values)["status"] == "INVALID_BROWSE_REPORT"


@pytest.mark.parametrize("field,value", [("game", "ONE_PIECE_CARD_GAME"), ("language", "japanese"), ("card_number", "5/102")])
def test_one_wrong_physical_match_does_not_count_as_evidence(field, value):
    values = inputs()
    values[1]["comparables"][0]["match_proof"][field] = value
    assert calculate(values)["status"] == "INSUFFICIENT_INDEPENDENT_LISTINGS"


@pytest.mark.parametrize("source,offset", [(1, timedelta(seconds=1)), (2, timedelta(seconds=1)), (2, -timedelta(days=7)), (2, -timedelta(days=8))])
def test_future_or_stale_sources_cannot_be_revived_by_calculation(source, offset):
    values = inputs()
    values[source]["observed_at"] = (NOW + offset).isoformat()
    assert calculate(values)["status"] == "STALE_OR_INVALID_EVIDENCE_TIME"


def test_browse_expiry_remains_original_acquisition_plus_three_days():
    values = inputs()
    assert calculate(values, now=NOW + timedelta(days=3))["status"] == "STALE_OR_INVALID_EVIDENCE_TIME"
    values[1]["expires_at"] = (NOW + timedelta(days=9)).isoformat()
    assert calculate(values)["status"] == "STALE_OR_INVALID_EVIDENCE_TIME"


def test_no_naive_or_non_datetime_clock():
    for invalid in (NOW.replace(tzinfo=None), None, "tomorrow", "0001-01-01T00:00:00+14:00"):
        assert calculate(inputs(), now=invalid)["status"] == "INVALID_INPUT"


def test_stale_comparable_cannot_borrow_fresh_report_timestamp():
    values = inputs()
    values[1]["comparables"][0]["observed_at"] = (NOW - timedelta(days=2)).isoformat()
    assert calculate(values)["status"] == "INSUFFICIENT_INDEPENDENT_LISTINGS"


def test_source_disagreement_does_not_publish_reassuring_midpoint():
    result = calculate(inputs(guide_value=3000))
    assert result["status"] == "SOURCE_DISAGREEMENT"
    assert result["estimate_minor"] is None
    assert result["market_value_minor"] is None
    assert result["source_count"] == 0


def test_older_source_has_less_influence_without_inventing_observation_time():
    values = inputs((1000, 1000, 1000), guide_value=1500)
    values[2]["observed_at"] = (NOW - timedelta(days=6)).isoformat()
    result = calculate(values)
    assert result["status"] == "READY"
    assert 1167 < result["estimate_minor"] < 1250
    assert result["observed_at"] == values[2]["observed_at"]
    assert result["expires_at"] == (NOW + timedelta(days=1)).isoformat()
    assert result["evidence"]["sources"][0]["weight"] > result["evidence"]["sources"][1]["weight"]


def test_many_listings_never_become_many_sources_or_completed_sales():
    result = calculate(inputs((1000,) * 100))
    assert result["status"] == "READY"
    assert result["source_count"] == 2
    assert result["sold_observation_count"] == 0
    assert result["confidence"] <= .60


def test_subpound_market_value_is_not_raised_to_retail_floor():
    result = calculate(inputs((10, 11, 12), guide_value=10, shipping=0))
    assert result["status"] == "READY"
    assert result["estimate_minor"] == 11


def test_provenance_is_copied_and_inputs_unchanged():
    values = inputs()
    before = deepcopy(values)
    result = calculate(values)
    assert values == before
    assert result["source"] == METHOD
    assert result["computed_at"] == NOW.isoformat()
    assert result["evidence"]["computed_at"] == NOW.isoformat()
    assert result["evidence"]["cardmarket_provenance"] == values[2]["provenance"]
    result["evidence"]["ebay_comparables"][0]["price_gbp_minor"] = 999
    result["evidence"]["cardmarket_provenance"]["product_id"] = "other"
    assert values == before


def test_rest_variation_ids_cannot_inflate_independent_legacy_items():
    values = inputs()
    duplicate = deepcopy(values[1]["comparables"][0])
    duplicate["item_id"] = "v1|1000|123"
    values[1]["comparables"].append(duplicate)
    result = calculate(values)
    assert result["status"] == "READY"
    assert result["observation_count"] == 4
    assert [row["item_id"] for row in result["evidence"]["ebay_comparables"]] == ["1000", "1001", "1002"]


@pytest.mark.parametrize("item_id", ["unknown", "v1|bad|0", "00123", "0", "https://ebay.co.uk/itm/123", "9" * 21])
def test_invalid_provider_identifier_is_excluded(item_id):
    values = inputs()
    values[1]["comparables"][0]["item_id"] = item_id
    assert calculate(values)["status"] == "INSUFFICIENT_INDEPENDENT_LISTINGS"


@pytest.mark.parametrize("end_at", [NOW.isoformat(), (NOW-timedelta(seconds=1)).isoformat(), "bad", NOW.replace(tzinfo=None).isoformat()])
def test_known_ended_or_invalid_listing_time_excludes_comparable(end_at):
    values = inputs()
    values[1]["comparables"][0]["listing_evidence"]["item_end_date"] = end_at
    assert calculate(values)["status"] == "INSUFFICIENT_INDEPENDENT_LISTINGS"


@pytest.mark.parametrize("end_at", [None, (NOW+timedelta(hours=1)).isoformat()])
def test_unknown_or_future_listing_end_uses_existing_evidence_ttl(end_at):
    values = inputs()
    values[1]["comparables"][0]["listing_evidence"]["item_end_date"] = end_at
    result = calculate(values)
    assert result["status"] == "READY"
    assert result["expires_at"] == (end_at or (NOW+timedelta(days=3)).isoformat())


def test_overflowing_source_timestamp_is_rejected_without_crashing():
    values = inputs()
    values[2]["observed_at"] = "0001-01-01T00:00:00+14:00"
    assert calculate(values)["status"] == "STALE_OR_INVALID_EVIDENCE_TIME"


def test_corrupt_listing_evidence_cannot_hide_end_time_or_crash_calculation():
    values = inputs()
    values[1]["comparables"][0]["listing_evidence"] = ["invalid"]
    assert calculate(values)["status"] == "INSUFFICIENT_INDEPENDENT_LISTINGS"
