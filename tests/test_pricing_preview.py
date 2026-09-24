from datetime import datetime, timezone
from pathlib import Path

from app.market_adapters import NormalizedMarketObservation
from app.pricing_engine import PricingPolicy
from app.pricing_preview import PREVIEW_SOURCES, _pricing_observation, _pricing_policy


ROOT = Path(__file__).parents[1]
PREVIEW = ROOT / "backend" / "app" / "pricing_preview.py"
MAIN = ROOT / "backend" / "app" / "main.py"
WORKBENCH = ROOT / "backend" / "app" / "static" / "market-mapping-workbench.js"


def test_preview_sources_fit_current_parse_budget_and_exclude_ebay() -> None:
    assert PREVIEW_SOURCES == ("CARDMARKET", "TCGPLAYER", "COLLECTR")
    assert "EBAY" not in PREVIEW_SOURCES


def test_preview_policy_defaults_without_persisting_a_policy() -> None:
    policy = _pricing_policy(None)
    assert policy == PricingPolicy()


def test_normalized_observation_is_converted_without_losing_comparability() -> None:
    observed_at = datetime.now(timezone.utc)
    normalized = NormalizedMarketObservation(
        source="CARDMARKET",
        source_record_key="record-1",
        observation_type="MARKET_AGGREGATE",
        observed_at=observed_at,
        price_minor=10000,
        currency="EUR",
        price_gbp_minor=8500,
        fx_rate_to_gbp=0.85,
        catalogue_id="catalogue-1",
        condition="Near Mint",
        grading_company=None,
        grade=None,
        language="English",
        source_country="DE",
        sample_size=3,
        evidence_quality=0.9,
    )
    result = _pricing_observation(normalized)
    assert result.source == "CARDMARKET"
    assert result.price_gbp_minor == 8500
    assert result.condition == "Near Mint"
    assert result.language == "English"
    assert result.sample_size == 3
    assert result.evidence_quality == 0.9


def test_preview_module_contains_no_market_or_inventory_write_sql() -> None:
    source = PREVIEW.read_text().casefold()
    assert "insert into tcg.market_observations" not in source
    assert "insert into tcg.pricing_snapshots" not in source
    assert "update tcg.inventory_items" not in source
    assert "delete from" not in source


def test_pricing_preview_router_is_wired_into_app() -> None:
    main = MAIN.read_text()
    assert "from .pricing_preview import router as pricing_preview_router" in main
    assert "app.include_router(pricing_preview_router)" in main


def test_workbench_calls_preview_and_discloses_non_persistence() -> None:
    source = WORKBENCH.read_text()
    assert "/api/v1/pricing/preview/" in source
    assert "/api/v1/pricing/preview-items/" in source
    assert "no observations, snapshots, Market Value or Store Price are saved" in source
