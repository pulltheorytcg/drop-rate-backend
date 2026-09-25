from datetime import datetime, timezone
from decimal import Decimal

from app.imported_benchmark_pricing import (
    _money_minor,
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


def test_positive_price_override_wins_over_market_price() -> None:
    result = extract_imported_benchmark(
        {
            "Price Override": "40",
            "Market Price (As of 2026-09-20)": "63.61",
        }
    )
    assert result == {
        "basis": "PRICE_OVERRIDE",
        "price_minor": 4000,
        "observed_at": None,
        "source_field": "Price Override",
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
    assert result["price_minor"] == 1234
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


def test_collectr_market_price_becomes_reusable_market_observation() -> None:
    source = (
        __import__("pathlib").Path(__file__).parents[1]
        / "backend"
        / "app"
        / "imported_benchmark_pricing.py"
    ).read_text()
    assert "'COLLECTR',$2,'MARKET_AGGREGATE'" in source
    assert "on conflict (source,source_record_key) do nothing" in source
    assert "evidence_quality" in source
    assert "0.65" in source


def test_price_override_is_not_misrepresented_as_market_observation() -> None:
    source = (
        __import__("pathlib").Path(__file__).parents[1]
        / "backend"
        / "app"
        / "imported_benchmark_pricing.py"
    ).read_text()
    assert 'if benchmark["basis"] != "MARKET_PRICE":' in source
    assert "return False" in source
