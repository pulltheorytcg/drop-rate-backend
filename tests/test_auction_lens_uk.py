"""UK auction buyer-signal safeguards; all figures are invented fixtures."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.auction_lens_uk import AuctionLot, MarketEvidence, compare_uk_auction

NOW = datetime(2026, 11, 7, 16, 0, tzinfo=timezone.utc)


def lot(**changes):
    item = AuctionLot(
        listing_id="test-auction-1",
        identity_key="POKEMON|TEF|001|English|Normal|Raw",
        scene_generation=4,
        identity_confirmed=True,
        bid_minor=8500,
        shipping_minor=450,
        buyer_fees_minor=150,
        import_tax_minor=0,
        additional_costs_minor=0,
        bid_observed_at=NOW,
    )
    return replace(item, **changes)


def evidence(**changes):
    value = MarketEvidence(
        identity_key="POKEMON|TEF|001|English|Normal|Raw",
        scene_generation=4,
        exact_match=True,
        market_value_minor=12000,
        evidence_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=1),
        source="Verified UK sold-evidence calculation",
        valuation_eligible=True,
        display_permitted=True,
    )
    return replace(value, **changes)


def compare(l=None, e=None, **changes):
    return compare_uk_auction(
        l or lot(), e or evidence(), now=NOW,
        around_basis_points=changes.get("around_basis_points", 500),
        max_bid_age_seconds=changes.get("max_bid_age_seconds", 15),
    )


def test_under_market_uses_all_charges_and_minor_units():
    result = compare()
    assert result.status == "UNDER_MARKET"
    assert result.all_in_minor == 9100
    assert result.market_value_minor == 12000
    assert result.saving_vs_market_minor == 2900
    assert result.source == "Verified UK sold-evidence calculation"


def test_near_market_and_over_market_compare_all_in_not_raw_bid():
    assert compare(lot(bid_minor=11400)).status == "AROUND_MARKET"
    above = compare(lot(bid_minor=12500))
    assert above.status == "OVER_MARKET"
    assert above.saving_vs_market_minor == -1100


@pytest.mark.parametrize("changes", [
    {"shipping_minor": None},
    {"buyer_fees_minor": None},
    {"import_tax_minor": None},
    {"additional_costs_minor": None},
])
def test_unknown_cost_never_acts_like_free_shipping_or_zero_tax(changes):
    result = compare(lot(**changes))
    assert result.status == "CHARGES_UNKNOWN"
    assert result.all_in_minor is None
    assert result.market_value_minor is None


@pytest.mark.parametrize("changes", [
    {"kind": "GUIDE"}, {"kind": "ACTIVE_ASKING_PRICE"},
    {"status": "REFERENCE_ESTIMATE"}, {"market_region": "US"},
    {"currency": "EUR"}, {"valuation_eligible": False},
    {"display_permitted": False}, {"source": ""},
    {"market_value_minor": None}, {"market_value_minor": 0},
    {"expires_at": NOW}, {"expires_at": NOW - timedelta(seconds=1)},
    {"evidence_at": NOW + timedelta(seconds=1)},
    {"evidence_at": None},
])
def test_unverified_guide_expired_or_unlicensed_value_is_not_market_value(changes):
    result = compare(e=evidence(**changes))
    assert result.status == "NO_CURRENT_MARKET_VALUE"
    assert result.market_value_minor is None
    assert result.all_in_minor is None


@pytest.mark.parametrize("l_changes,e_changes", [
    ({"scene_generation": 5}, {}),
    ({"identity_key": "OTHER"}, {}),
    ({"identity_confirmed": False}, {}),
    ({}, {"exact_match": False}),
    ({}, {"identity_key": "OTHER"}),
])
def test_cross_lot_stale_response_or_ambiguous_version_abstains(l_changes, e_changes):
    result = compare(lot(**l_changes), evidence(**e_changes))
    assert result.status == "CHECK_VERSION"
    assert result.market_value_minor is None
    assert result.all_in_minor is None


def test_stale_or_future_bid_and_ended_auction_abstain():
    assert compare(lot(bid_observed_at=NOW-timedelta(seconds=16))).status == "STALE_BID"
    assert compare(lot(bid_observed_at=NOW+timedelta(seconds=1))).status == "STALE_BID"
    assert compare(lot(status="ENDED")).status == "AUCTION_NOT_ACTIVE"


def test_non_gbp_bid_requires_upstream_normalisation_not_silent_fx():
    assert compare(lot(currency="USD")).status == "UNSUPPORTED_CURRENCY"


@pytest.mark.parametrize("changes", [
    {"bid_minor": -1}, {"shipping_minor": -1},
    {"buyer_fees_minor": 1.5}, {"import_tax_minor": True},
])
def test_bad_money_does_not_get_coerced_to_a_plausible_uk_bid(changes):
    with pytest.raises(ValueError):
        compare(lot(**changes))


def test_missing_or_invalid_price_minor_units_fail():
    with pytest.raises(ValueError):
        compare(e=evidence(market_value_minor=-100))


def test_tolerance_must_be_explicit_and_valid():
    with pytest.raises(ValueError):
        compare(around_basis_points=-1)
    with pytest.raises(ValueError):
        compare(max_bid_age_seconds=0)
