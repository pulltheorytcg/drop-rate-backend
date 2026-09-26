from datetime import datetime, timezone
from pathlib import Path

from app.market_adapters import NormalizedMarketObservation
from app.pricing_engine import PricingPolicy
from app.pricing_preview import PREVIEW_SOURCES, _evidence_sample, _pricing_observation, _pricing_policy


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
    assert "app.include_router(pricing_preview_router, dependencies=[Depends(require_platform_admin_request)])" in main


def test_workbench_calls_preview_and_discloses_non_persistence() -> None:
    source = WORKBENCH.read_text()
    assert "/api/v1/pricing/preview/" in source
    assert "/api/v1/pricing/preview-items/" in source
    assert "no observations, snapshots, Market Value or Store Price are saved" in source


def test_evidence_sample_exposes_only_normalized_fields() -> None:
    observed_at = datetime.now(timezone.utc)
    normalized = NormalizedMarketObservation(
        source="TCGPLAYER",
        source_record_key="secret-record-key",
        observation_type="SOLD",
        observed_at=observed_at,
        price_minor=10000,
        currency="USD",
        price_gbp_minor=7500,
        fx_rate_to_gbp=0.75,
        catalogue_id="catalogue-1",
        shipping_minor=500,
        shipping_gbp_minor=375,
        condition="Near Mint",
        language="English",
        source_country="US",
        sample_size=1,
        evidence_quality=1.0,
        metadata={
            "listing_title": "raw provider title",
            "seller": "do-not-expose",
            "api_key": "never",
        },
    )

    sample = _evidence_sample(normalized)

    assert sample["source"] == "TCGPLAYER"
    assert sample["price_gbp_minor"] == 7500
    assert sample["shipping_gbp_minor"] == 375
    assert sample["condition"] == "Near Mint"
    assert "metadata" not in sample
    assert "source_record_key" not in sample
    assert "seller" not in sample
    assert "api_key" not in sample


def test_workbench_renders_sanitized_evidence_rows() -> None:
    source = WORKBENCH.read_text()
    assert "renderEvidenceSources" in source
    assert "evidence_sample" in source
    assert "price_gbp_minor" in source


def test_unconfirmed_identity_blocks_before_provider_fetch() -> None:
    source = PREVIEW.read_text()
    identity_guard = 'if not item["identity_confirmed"]:'
    provider_loop = "for source in PREVIEW_SOURCES:"
    assert identity_guard in source
    assert 'block_reasons": ["Physical card identity has not been confirmed"]' in source
    assert source.index(identity_guard) < source.index(provider_loop)
