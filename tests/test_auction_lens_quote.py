"""Authorised video market comparison is deterministic and fails closed."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.auction_lens_quote import compare_verified_quote

NOW = datetime(2026, 11, 8, 15, 30, tzinfo=timezone.utc)
PRICE = {
    "marketValueMinor": 10000,
    "currency": "GBP",
    "source": "Drop Rate eligible UK sold",
    "evidenceAtMs": int((NOW - timedelta(hours=1)).timestamp() * 1000),
    "expiresAtMs": int((NOW + timedelta(hours=1)).timestamp() * 1000),
    "valuationEligible": True,
}
QUOTE = {
    "lot_ref": "owner-recording-001",
    "status": "ACTIVE",
    "currency": "GBP",
    "bid_minor": 5000,
    "shipping_minor": 600,
    "buyer_fees_minor": 900,
    "import_tax_minor": 0,
    "additional_costs_minor": 0,
    "bid_observed_at": NOW - timedelta(seconds=2),
}


def compare(*, price=PRICE, rights=True, changed=None):
    quote = SimpleNamespace(**{**QUOTE, **(changed or {})})
    return compare_verified_quote(
        quote=quote, identity_key="card:exact",
        scene_generation=12, verified_uk_value=price,
        display_rights_approved=rights, now=NOW,
    )


def test_verified_uk_pence_bid_comparison():
    result = compare()
    assert result["status"] == "UNDER_MARKET"
    assert result["allInMinor"] == 6500
    assert result["bidExpiresAtMs"] == int((QUOTE["bid_observed_at"] + timedelta(seconds=30)).timestamp() * 1000)
    assert result["marketValueMinor"] == 10000
    assert result["differenceMinor"] == 3500
    assert result["evidenceAtMs"] == PRICE["evidenceAtMs"]
    assert result["source"] == PRICE["source"]


@pytest.mark.parametrize("cost,status", [
    ({"bid_minor": 8500}, "AROUND_MARKET"),
    ({"bid_minor": 11000}, "OVER_MARKET"),
    ({"status": "ENDED"}, "AUCTION_NOT_ACTIVE"),
    ({"shipping_minor": None}, "CHARGES_UNKNOWN"),
    ({"buyer_fees_minor": None}, "CHARGES_UNKNOWN"),
    ({"import_tax_minor": None}, "CHARGES_UNKNOWN"),
    ({"additional_costs_minor": None}, "CHARGES_UNKNOWN"),
    ({"bid_observed_at": NOW - timedelta(seconds=31)}, "STALE_BID"),
    ({"bid_observed_at": NOW + timedelta(seconds=1)}, "STALE_BID"),
    ({"currency": "USD"}, "UNSUPPORTED_CURRENCY"),
])
def test_no_bargain_badge_for_unsupported_or_unknown_costs(cost, status):
    result = compare(changed=cost)
    assert result["status"] == status
    if status not in {"AROUND_MARKET", "OVER_MARKET"}:
        assert not any(field in result for field in ("marketValueMinor", "allInMinor", "differenceMinor"))


def test_missing_unapproved_or_expired_prices_are_never_replaced_by_guides():
    for value, rights in (
        (None, True),
        (PRICE, False),
        ({**PRICE, "valuationEligible": False}, True),
        ({**PRICE, "currency": "USD"}, True),
        ({**PRICE, "expiresAtMs": int((NOW - timedelta(seconds=1)).timestamp() * 1000)}, True),
        ({**PRICE, "source": ""}, True),
        ({**PRICE, "evidenceAtMs": None}, True),
    ):
        result = compare(price=value, rights=rights)
        assert result == {"status": "NO_CURRENT_MARKET_VALUE"}


def test_exact_int_pence_and_unknown_is_not_zero():
    with pytest.raises(ValueError):
        compare(changed={"shipping_minor": -1})
    with pytest.raises(ValueError):
        compare(changed={"bid_minor": 5.5})
