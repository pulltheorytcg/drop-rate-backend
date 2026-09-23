from datetime import datetime, timedelta, timezone

import pytest

from app.pricing_engine import (
    ComparableTarget,
    MarketObservation,
    PricingPolicy,
    calculate_price,
    weighted_median,
)


NOW = datetime(2026, 9, 23, 2, 0, tzinfo=timezone.utc)


def obs(
    source: str,
    price: int,
    *,
    kind: str = "SOLD",
    days_old: int = 1,
    condition: str | None = "Near Mint",
    language: str | None = "English",
    sample_size: int = 1,
    country: str | None = None,
) -> MarketObservation:
    return MarketObservation(
        source=source,
        observation_type=kind,
        observed_at=NOW - timedelta(days=days_old),
        price_gbp_minor=price,
        sample_size=sample_size,
        evidence_quality=1.0,
        condition=condition,
        language=language,
        source_country=country,
    )


def target() -> ComparableTarget:
    return ComparableTarget(condition="Near Mint", language="English")


def test_weighted_median_is_not_simple_average() -> None:
    assert weighted_median([(1000, 1), (1100, 1), (10000, 0.1)]) == 1100


def test_extreme_single_source_outlier_does_not_set_market() -> None:
    observations = [
        obs("EBAY", 9800, country="GB"),
        obs("EBAY", 10000, country="GB"),
        obs("EBAY", 10100, country="GB"),
        obs("EBAY", 10200, country="GB"),
        obs("EBAY", 90000, country="GB"),
        obs("COLLECTR", 10050, kind="MARKET_AGGREGATE", sample_size=5),
        obs("CARDMARKET", 9900, kind="PRICE_GUIDE", sample_size=5),
    ]
    result = calculate_price(observations, target=target(), as_of=NOW)
    assert 9800 <= result.market_value_minor <= 10200
    assert result.market_value_minor != 90000


def test_language_mismatch_is_excluded() -> None:
    observations = [
        obs("EBAY", 10000, language="English", country="GB"),
        obs("COLLECTR", 10100, kind="MARKET_AGGREGATE", language="English", sample_size=4),
        obs("CARDMARKET", 25000, kind="PRICE_GUIDE", language="Japanese", sample_size=10),
    ]
    result = calculate_price(observations, target=target(), as_of=NOW)
    assert result.source_count == 2
    assert result.market_value_minor < 15000


def test_high_value_cards_require_review() -> None:
    observations = [
        obs("EBAY", 80000, country="GB", sample_size=5),
        obs("COLLECTR", 81000, kind="MARKET_AGGREGATE", sample_size=8),
        obs("CARDMARKET", 79000, kind="PRICE_GUIDE", sample_size=8),
    ]
    result = calculate_price(observations, target=target(), as_of=NOW)
    assert "HIGH_VALUE_REVIEW" in result.block_reasons
    assert not result.auto_publish_eligible


def test_large_price_change_blocks_automatic_publish() -> None:
    observations = [
        obs("EBAY", 12000, country="GB", sample_size=8),
        obs("COLLECTR", 12100, kind="MARKET_AGGREGATE", sample_size=8),
        obs("CARDMARKET", 11900, kind="PRICE_GUIDE", sample_size=8),
    ]
    result = calculate_price(
        observations,
        target=target(),
        current_store_price_minor=9000,
        as_of=NOW,
    )
    assert "CHANGE_TOO_LARGE" in result.block_reasons
    assert not result.auto_publish_eligible


def test_low_change_is_ignored_to_prevent_price_churn() -> None:
    policy = PricingPolicy(min_price_change_minor=100, min_price_change_pct=2.0)
    observations = [
        obs("EBAY", 10020, country="GB", sample_size=8),
        obs("COLLECTR", 10010, kind="MARKET_AGGREGATE", sample_size=8),
        obs("CARDMARKET", 10030, kind="PRICE_GUIDE", sample_size=8),
    ]
    result = calculate_price(
        observations,
        target=target(),
        policy=policy,
        current_store_price_minor=10000,
        as_of=NOW,
    )
    assert "MIN_CHANGE_NOT_REACHED" in result.block_reasons
    assert not result.auto_publish_eligible


def test_policy_generates_retail_quick_sale_and_acquisition_prices() -> None:
    policy = PricingPolicy(
        min_confidence=0.0,
        min_sources=1,
        high_value_review_minor=1_000_000,
        retail_multiplier=1.02,
        quick_sale_multiplier=0.90,
        acquisition_multiplier=0.70,
    )
    observations = [obs("EBAY", 10000, country="GB", sample_size=8)]
    result = calculate_price(observations, target=target(), policy=policy, as_of=NOW)
    assert result.market_value_minor == 10000
    assert result.recommended_retail_minor == 10200
    assert result.quick_sale_minor == 9000
    assert result.target_acquisition_minor == 7000


def test_no_comparable_observations_fails_closed() -> None:
    observations = [obs("EBAY", 10000, language="Japanese")]
    with pytest.raises(ValueError, match="No comparable"):
        calculate_price(observations, target=target(), as_of=NOW)


def test_us_and_global_only_evidence_cannot_set_uk_market_value() -> None:
    observations = [
        obs("TCGPLAYER", 15000, country="US", sample_size=8),
        obs("COLLECTR", 14800, kind="MARKET_AGGREGATE", sample_size=8),
    ]
    with pytest.raises(ValueError, match="No UK/EU market anchor"):
        calculate_price(observations, target=target(), as_of=NOW)


def test_extreme_us_price_does_not_move_displayed_uk_market_value() -> None:
    observations = [
        obs("EBAY", 10000, country="GB", sample_size=5),
        obs("CARDMARKET", 10100, kind="MARKET_AGGREGATE", sample_size=8),
        obs("TCGPLAYER", 30000, country="US", sample_size=8),
        obs("COLLECTR", 28000, kind="MARKET_AGGREGATE", sample_size=8),
    ]
    result = calculate_price(observations, target=target(), as_of=NOW)
    assert 10000 <= result.market_value_minor <= 10100
    assert result.market_value_minor not in (28000, 30000)
