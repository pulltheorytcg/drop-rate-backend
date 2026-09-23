from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.market_smoke import MarketSmokeRequest, _price_summary


ROOT = Path(__file__).parents[1]
SMOKE = ROOT / "backend" / "app" / "market_smoke.py"
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


def test_smoke_router_is_wired_into_app() -> None:
    main = MAIN.read_text()
    assert "from .market_smoke import router as market_smoke_router" in main
    assert "app.include_router(market_smoke_router)" in main
