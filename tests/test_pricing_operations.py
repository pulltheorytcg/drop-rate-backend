from pathlib import Path


ROOT = Path(__file__).parents[1]
PRICING = ROOT / "backend" / "app" / "pricing.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_pricing_router_is_wired_into_app() -> None:
    main = MAIN.read_text()
    assert "from .pricing import router as pricing_router" in main
    assert "app.include_router(pricing_router, dependencies=[Depends(require_platform_admin_request)])" in main


def test_pricing_recalculation_updates_recommendation_not_store_price() -> None:
    pricing = PRICING.read_text()
    assert "market_value_minor = $2" in pricing
    assert "recommended_retail_minor = $3" in pricing
    update_block = pricing.split("update tcg.inventory_items", 1)[1].split("where id = $1", 1)[0]
    assert "store_price_minor" not in update_block


def test_pricing_history_remains_snapshot_based() -> None:
    pricing = PRICING.read_text()
    assert "insert into tcg.pricing_snapshots" in pricing
    assert "order by calculated_at desc" in pricing


def test_batch_repricing_is_bounded() -> None:
    pricing = PRICING.read_text()
    assert "max_length=100" in pricing


def test_pricing_recalculation_blocks_historical_inventory() -> None:
    pricing = PRICING.read_text()
    assert 'item["status"] in {"SOLD", "WITHDRAWN"}' in pricing
    assert "Sold or withdrawn inventory cannot be repriced" in pricing
