"""Safeguards for the signed-in, manually reviewed eBay research bridge."""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.ebay_signed_in_research import build_sold_search_url, preview_product_research

NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)


def target(**overrides):
    value = {
        "game": "Pokemon",
        "name": "Seel",
        "set_name": "Phantasmal Flames",
        "card_number": "021/094",
        "variant": "Normal",
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
        "language": "English",
    }
    value.update(overrides)
    return value


def reviewed(item_id, *, price="5.00", days_ago=1, **overrides):
    row = {
        "source": "EBAY_PRODUCT_RESEARCH",
        "sale_price_basis": "ACTUAL_PAID_PRICE",
        "item_id": str(item_id),
        "title": "Pokemon Seel 021/094 Phantasmal Flames Near Mint",
        "sold_at": (NOW - timedelta(days=days_ago)).isoformat(),
        "price_gbp": price,
        "shipping_gbp": "0",
        "currency": "GBP",
        "item_country": "GB",
        "set_name": "Phantasmal Flames",
        "card_number": "021/094",
        "variant": "Normal",
        "language": "English",
        "condition_raw": "Near Mint",
    }
    row.update(overrides)
    return row


def test_builds_browser_search_link_without_secret_or_network():
    url = build_sold_search_url(target())
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.hostname == "www.ebay.co.uk"
    assert query["LH_Sold"] == ["1"]
    assert query["LH_Complete"] == ["1"]
    assert "Seel" in query["_nkw"][0]
    assert "021/094" in query["_nkw"][0]


def test_preview_five_exact_sales_without_live_price_write():
    rows = [reviewed(i, price=price, days_ago=day) for i, price, day in (
        (1001, "5.00", 1), (1002, "7.00", 2), (1003, "3.00", 3),
        (1004, "6.00", 4), (1005, "4.00", 5)
    )]
    result = preview_product_research(target(), rows, now=NOW)
    assert result["candidate_median_item_price_minor"] == 500
    assert result["newest_five_count"] == 5
    assert result["eligible_exact_count"] == 5
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["candidate_is_market_value"] is False
    assert result["price_publication_enabled"] is False
    assert result["database_writes"] is False and result["shopify_writes"] is False
    assert "1001" not in str(result)


@pytest.mark.parametrize("override,reason", [
    ({"sale_price_basis": "ASKING_PRICE"}, "UNCONFIRMED_ACTUAL_SALE_PRICE"),
    ({"source": "EBAY_SOLD_LISTING"}, "UNCONFIRMED_ACTUAL_SALE_PRICE"),
    ({"currency": "USD"}, "NON_GB_OR_NON_GBP"),
    ({"item_country": "US"}, "NON_GB_OR_NON_GBP"),
    ({"title": "Pokemon Seel 021/094 PSA 10"}, "EXACT_PRINT_MISMATCH"),
    ({"title": "Pokemon Seel 021/094 Japanese Near Mint"}, "EXACT_PRINT_MISMATCH"),
    ({"title": "Pokemon Seel 021/094 Holo Near Mint"}, "EXACT_PRINT_MISMATCH"),
    ({"title": "Pokemon Seel 021/094 bundle x2 Near Mint"}, "EXACT_PRINT_MISMATCH"),
    ({"price_gbp": "4.999"}, "INVALID_PRICE"),
    ({"price_gbp": "0"}, "INVALID_PRICE"),
    ({"sold_at": "2026-11-11T11:00:00"}, "INVALID_OR_STALE_SOLD_DATE"),
    ({"set_name": "Different Set"}, "EXACT_PRINT_MISMATCH"),
    ({"sold_at": "2025-01-01T00:00:00+00:00"}, "INVALID_OR_STALE_SOLD_DATE"),
])
def test_invalid_or_unproven_comps_are_excluded(override, reason):
    result = preview_product_research(target(), [reviewed(1001, **override)], now=NOW)
    assert result["eligible_exact_count"] == 0
    assert result["candidate_median_item_price_minor"] is None
    assert result["excluded_reasons"][reason] == 1


def test_duplicate_listing_id_cannot_inflate_five_comps():
    rows = [reviewed(1001), reviewed(1001), reviewed(1002),
            reviewed(1003), reviewed(1004), reviewed(1005)]
    result = preview_product_research(target(), rows, now=NOW)
    assert result["eligible_exact_count"] == 4
    assert result["candidate_median_item_price_minor"] is None
    assert result["excluded_reasons"]["DUPLICATE_ITEM_ID"] == 2


def test_old_comps_without_one_recent_sale_do_not_produce_candidate():
    rows = [reviewed(1000 + i, days_ago=15 + i) for i in range(5)]
    result = preview_product_research(target(), rows, now=NOW)
    assert result["eligible_exact_count"] == 5
    assert result["recent_14d_count"] == 0
    assert result["candidate_median_item_price_minor"] is None


def test_rejects_unbounded_input_and_incomplete_canonical_identity():
    with pytest.raises(ValueError):
        preview_product_research(target(), [reviewed(i + 1000) for i in range(101)], now=NOW)
    with pytest.raises(ValueError):
        build_sold_search_url(target(card_number=""))
    with pytest.raises(ValueError):
        preview_product_research(target(grade="10"), [], now=NOW)


def test_date_only_sales_from_product_research_are_review_only():
    rows = [reviewed(1000 + i, sold_at="2026-11-11") for i in range(5)]
    result = preview_product_research(target(), rows, now=NOW)
    assert result["eligible_exact_count"] == 5
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["candidate_median_item_price_minor"] == 500
    assert result["candidate_is_market_value"] is False
