from datetime import datetime, timezone
from decimal import Decimal

from app.fx import FxQuote
from app.imported_benchmark_pricing import (
    _money_minor,
    _to_gbp_minor,
    extract_imported_benchmark,
)


def test_money_minor_rejects_non_positive_and_malformed_values() -> None:
    assert _money_minor(None) is None
    assert _money_minor("") is None
    assert _money_minor("0") is None
    assert _money_minor("-1") is None
    assert _money_minor("abc") is None
    assert _money_minor("12.34") == 1234
    assert _money_minor(Decimal("1.005")) == 101


def test_price_override_is_ignored_when_currency_is_not_declared() -> None:
    result = extract_imported_benchmark(
        {
            "Price Override": "40",
            "Market Price (As of 2026-09-20)": "63.61",
        }
    )
    assert result == {
        "basis": "MARKET_PRICE",
        "source_currency": "USD",
        "source_price_minor": 6361,
        "observed_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
        "source_field": "Market Price (As of 2026-09-20)",
    }


def test_newest_positive_market_price_is_selected() -> None:
    result = extract_imported_benchmark(
        {
            "Price Override": "0",
            "Market Price (As of 2026-08-20)": "10.00",
            "Market Price (As of 2026-09-20)": "12.34",
        }
    )
    assert result["basis"] == "MARKET_PRICE"
    assert result["source_currency"] == "USD"
    assert result["source_price_minor"] == 1234
    assert result["observed_at"] == datetime(2026, 9, 20, tzinfo=timezone.utc)
    assert result["source_field"] == "Market Price (As of 2026-09-20)"


def test_zero_benchmark_is_not_accepted() -> None:
    assert (
        extract_imported_benchmark(
            {
                "Price Override": "0",
                "Market Price (As of 2026-09-20)": "0",
            }
        )
        is None
    )


def test_provisional_pricing_never_auto_publishes() -> None:
    source = (
        __import__("pathlib").Path(__file__).parents[1]
        / "backend"
        / "app"
        / "imported_benchmark_pricing.py"
    ).read_text()
    assert "auto_publish_eligible,block_reasons" in source
    assert "false,$14::jsonb" in source
    assert "PROVISIONAL_IMPORTED_BENCHMARK" in source
    assert "NO_COMPARABLE_SOLD_HISTORY" in source


def test_existing_store_price_is_never_overwritten() -> None:
    source = (
        __import__("pathlib").Path(__file__).parents[1]
        / "backend"
        / "app"
        / "imported_benchmark_pricing.py"
    ).read_text()
    assert "and i.store_price_minor is null" in source
    assert "and store_price_minor is null" in source


def test_collectr_market_price_becomes_reusable_market_observation_only_after_identity_confirmation() -> None:
    source = (
        __import__("pathlib").Path(__file__).parents[1]
        / "backend"
        / "app"
        / "imported_benchmark_pricing.py"
    ).read_text()
    assert "'COLLECTR',$2,'MARKET_AGGREGATE'" in source
    assert 'not item["identity_confirmed"]' in source
    assert "on conflict (source,source_record_key) do nothing" in source
    assert "evidence_quality" in source
    assert "0.65" in source


def test_batch_limit_is_applied_after_evidence_filtering() -> None:
    source = (
        __import__("pathlib").Path(__file__).parents[1]
        / "backend"
        / "app"
        / "imported_benchmark_pricing.py"
    ).read_text()
    assert "owner_id,\n        2000," in source
    assert "if len(candidates) >= limit:" in source


def test_usd_collectr_price_is_normalized_to_gbp_with_auditable_quote() -> None:
    quote = FxQuote(
        base_currency="USD",
        quote_currency="GBP",
        rate=Decimal("0.75"),
        effective_at=datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 9, 25, 23, 0, tzinfo=timezone.utc),
        source="TEST_ECB",
    )
    assert _to_gbp_minor(6361, quote) == 4771


def test_collectr_observation_preserves_usd_and_fx_provenance() -> None:
    source = (
        __import__("pathlib").Path(__file__).parents[1]
        / "backend"
        / "app"
        / "imported_benchmark_pricing.py"
    ).read_text()
    assert "'USD',$5,null" in source
    assert '"fx_source": fx_quote.source' in source
    assert '"fx_effective_at": fx_quote.effective_at.isoformat()' in source
    assert '"normalized_gbp_minor": market_value_minor' in source
    assert '"store_price_floor_applied": store_price_minor > market_value_minor' in source
    assert "EcbHistoricalFxProvider()" in source
    assert "Phase 2: fetch auditable historical FX quotes outside any DB transaction." in source
