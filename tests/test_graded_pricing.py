from datetime import datetime, timezone

import pytest

from app.pricing_engine import (
    ALGORITHM_VERSION,
    ComparableTarget,
    MarketObservation,
    PricingPolicy,
    calculate_price,
    comparable_quality,
)


NOW = datetime(2026, 9, 23, 19, 0, tzinfo=timezone.utc)


def graded_observation(*, grade: str = "9", condition: str | None = "Used") -> MarketObservation:
    return MarketObservation(
        source="EBAY",
        observation_type="SOLD",
        observed_at=NOW,
        price_gbp_minor=25000,
        sample_size=5,
        evidence_quality=1.0,
        condition=condition,
        grading_company="PSA",
        grade=grade,
        language="English",
        source_country="GB",
    )


def graded_target() -> ComparableTarget:
    return ComparableTarget(
        condition="Near Mint",
        grading_company="PSA",
        grade="9",
        language="English",
    )


def test_graded_comparable_ignores_marketplace_raw_condition_label() -> None:
    assert comparable_quality(graded_observation(condition="Used"), graded_target()) == 1.0
    assert comparable_quality(graded_observation(condition="New (other)"), graded_target()) == 1.0
    assert comparable_quality(graded_observation(condition=None), graded_target()) == 1.0


def test_graded_comparable_still_requires_exact_grading_company_and_grade() -> None:
    wrong_grade = graded_observation(grade="10")
    wrong_company = MarketObservation(
        **{
            **graded_observation().__dict__,
            "grading_company": "CGC",
        }
    )
    assert comparable_quality(wrong_grade, graded_target()) == 0.0
    assert comparable_quality(wrong_company, graded_target()) == 0.0


def test_graded_uk_sale_can_set_market_value_despite_generic_listing_condition() -> None:
    policy = PricingPolicy(
        min_confidence=0.0,
        min_sources=1,
        high_value_review_minor=1_000_000,
    )
    result = calculate_price(
        [graded_observation(condition="Used")],
        target=graded_target(),
        policy=policy,
        as_of=NOW,
    )
    assert result.market_value_minor == 25000
    assert result.algorithm_version == "drop-rate-market-v4"


def test_raw_comparable_still_rejects_wrong_condition() -> None:
    raw_target = ComparableTarget(condition="Near Mint", language="English")
    raw_observation = MarketObservation(
        source="EBAY",
        observation_type="SOLD",
        observed_at=NOW,
        price_gbp_minor=10000,
        condition="Lightly Played",
        language="English",
        source_country="GB",
    )
    assert comparable_quality(raw_observation, raw_target) == 0.0


def test_algorithm_version_bumped_for_comparable_semantics_change() -> None:
    assert ALGORITHM_VERSION == "drop-rate-market-v4"
