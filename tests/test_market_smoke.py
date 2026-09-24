from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.market_smoke import MarketSmokeRequest, _price_summary


ROOT = Path(__file__).parents[1]
SMOKE = ROOT / "backend" / "app" / "market_smoke.py"
SMOKE_PANEL = ROOT / "backend" / "app" / "static" / "market-smoke-panel.js"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_price_summary_is_deterministic() -> None:
    assert _price_summary([]) is None
    assert _price_summary([1200]) == {
        "min_minor": 1200,
        "median_minor": 1200,
        "max_minor": 1200,
    }
    assert _price_summary([2500, 1000, 1500, 2000]) == {
        "min_minor": 1000,
        "median_minor": 1750,
        "max_minor": 2500,
    }


def test_smoke_request_requires_provider_identity() -> None:
    with pytest.raises(ValidationError):
        MarketSmokeRequest(
            catalogue_id=uuid4(),
            source_product_id="",
        )


def test_smoke_request_limits_provider_identity_size() -> None:
    with pytest.raises(ValidationError):
        MarketSmokeRequest(
            catalogue_id=uuid4(),
            source_product_id="x" * 10001,
        )


def test_smoke_endpoint_logs_diagnostics_but_not_market_data() -> None:
    source = SMOKE.read_text()
    lowered = source.lower()

    assert '"diagnostic": "smoke_test"' in lowered
    assert "_record_run(" in source
    assert "inserted_count=0" in source
    assert '"persisted": false' in lowered
    assert "insert into tcg.market_observations" not in lowered
    assert "insert into tcg.pricing_snapshots" not in lowered
    assert "update tcg.inventory_items" not in lowered
    assert "delete from tcg.market_observations" not in lowered


def test_smoke_diagnostic_logging_is_isolated_by_savepoint() -> None:
    source = SMOKE.read_text()
    assert "async with connection.transaction():" in source
    assert "return None, False" in source
    assert '"diagnostic_logged": diagnostic_logged' in source
    assert '"stage": "PROVIDER_FETCH_OR_VALIDATION"' in source


def test_provider_wait_does_not_hold_one_long_database_transaction() -> None:
    source = SMOKE.read_text()
    assert "select clock_timestamp()" in source
    assert "No database connection or transaction is held while waiting on Parse/eBay." in source
    assert source.count("async with user_connection(") >= 3
    assert source.index("await adapter.fetch_observations(") > source.index("started_at = await connection.fetchval")


def test_smoke_failure_is_visible_in_safe_runtime_logs() -> None:
    source = SMOKE.read_text()
    assert "market_smoke_failed" in source
    assert 'safe_error.get("detail")' in source
    assert 'safe_error.get("provider_status_code")' in source
    assert 'safe_error.get("retryable")' in source


def test_dashboard_smoke_matrix_uses_official_active_ebay_only() -> None:
    source = SMOKE_PANEL.read_text()
    assert source.count("include_sold: false") == 5
    assert source.count("include_active: true") == 5
    assert "sold-history access remains a separate restricted capability" in source.casefold()


def test_smoke_router_is_wired_into_app() -> None:
    main = MAIN.read_text()
    assert "from .market_smoke import router as market_smoke_router" in main
    assert "app.include_router(market_smoke_router)" in main
