"""Expired quote caches must never masquerade as current Market Value.

The input source's explicit expires_at is independent of the convenient
seven-day observation window. Missing sold evidence remains unavailable.
"""
from datetime import datetime, timedelta, timezone

from app import catalogue_browser as browser
from app import catalogue_coverage as coverage
from app.reference_market import current_cached_price_view, _cache_is_current


NOW = datetime(2026, 11, 7, 2, 0, tzinfo=timezone.utc)


def raw_reference(*, expires_at, catalogue_expires_at=None, price=500):
    identity={"name":"Bulbasaur","set_id":"x","card_number":"1/25","set_name":"Set"}
    return {
        "key":"r:fixture",**identity,
        "expires_at":expires_at,"catalogue_expires_at":catalogue_expires_at,
        "quotes":[{
            "source":"TCGDEX_CARDMARKET",
            "observed_at":(NOW-timedelta(hours=2)).isoformat(),
            "price_gbp_minor":price,
        }],
        "catalogue_quotes":[{
            "source":"CARDMARKET_CATALOGUE",
            "reference_identity":identity,
            "observed_at":(NOW-timedelta(hours=2)).isoformat(),
            "price_gbp_minor":price+100,
        }],
    }


def test_fresh_observation_does_not_resurrect_expired_market_row():
    expired=raw_reference(expires_at=NOW-timedelta(minutes=1))
    result=current_cached_price_view(expired,now=NOW)
    assert result["market_value_minor"] is None
    assert result["market_value_high_minor"] is None
    assert result["market_value_source"] is None
    assert result["market_quotes"]==[]


def test_unexpired_exact_market_row_can_display():
    valid=raw_reference(expires_at=NOW+timedelta(minutes=1))
    result=current_cached_price_view(valid,now=NOW)
    assert result["market_value_minor"]==500
    assert result["market_value_source"]=="TCGDEX_CARDMARKET"


def test_unexpired_exact_catalogue_fallback_cannot_resurrect_expired_market():
    row=raw_reference(
        expires_at=NOW-timedelta(minutes=1),
        catalogue_expires_at=NOW+timedelta(hours=1),
    )
    result=current_cached_price_view(row,now=NOW)
    assert result["market_value_minor"]==600
    assert result["market_value_source"]=="CARDMARKET_CATALOGUE"


def test_expired_or_missing_catalogue_fallback_is_not_current():
    for expiry in (None,NOW-timedelta(seconds=1),"invalid","2026-11-06T10:00:00Z"):
        row=raw_reference(expires_at=None,catalogue_expires_at=expiry)
        assert current_cached_price_view(row,now=NOW)["market_value_minor"] is None


def test_invalid_or_naive_quote_expiry_fails_closed():
    for expiry in (None, "", "2026-11-09T00:00:00", "not-a-time", 17,
                   NOW-timedelta(seconds=1)):
        assert _cache_is_current(expiry,NOW) is False


def test_catalogue_browser_sql_requires_expiry_in_all_market_columns():
    cte=browser.SOURCE_CTE
    assert "m.pricing_updated_at>=now()-interval '7 days' and m.expires_at>now()" in cte
    assert cte.count("m.expires_at>now()") >= 6
    assert "and b.expires_at>now()" in cte
    assert "m.market_value_minor end" in cte
    assert "when m.pricing_updated_at>=now()-interval '7 days' then m.market_value_minor" not in cte
    # Both value-sorted and regular searches must filter provisional guide
    # snapshots from a real sold-Market-Value display.
    assert "v.valuation_source='STORED_SNAPSHOT'" in browser.REFERENCE_VALUES_SQL
    import inspect
    query_fn=inspect.getsource(browser.product_query)
    assert "value.valuation_source='STORED_SNAPSHOT'" in query_fn


def test_coverage_counts_expired_source_value_as_stale_not_current():
    sql=coverage.COVERAGE_SQL
    assert "p.expires_at>now()" in sql
    assert "b.expires_at>now()" in sql
    assert "when p.market_value_minor>0 and (p.expires_at is null or p.expires_at<=now()) then 'STALE_EVIDENCE'" in sql
    assert "when b.market_value_minor>0 and (b.expires_at is null or b.expires_at<=now()) then 'STALE_EVIDENCE'" in sql
    assert "when p.expires_at is null or p.expires_at<=now() then 'STALE_EVIDENCE'" in sql
