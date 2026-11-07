"""Source-integrity, seller independence and 4,096 seeded adversarial price cases."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from random import Random

import pytest

from app.pricing_engine import (
    ALGORITHM_VERSION, RULESET_REVISION, ComparableTarget, MarketObservation,
    PricingPolicy, calculate_price,
)

NOW = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)
TARGET = ComparableTarget(condition="Near Mint", language="English")
POLICY = PricingPolicy(min_confidence=0, min_sources=1, max_volatility_pct=25,
                       max_auto_change_pct=100, high_value_review_minor=100_000_000)


def sold(price, key, *, source="EBAY", days=1):
    return MarketObservation(
        source=source, observation_type="SOLD",
        observed_at=NOW-timedelta(days=days), price_gbp_minor=price,
        source_record_key=key, sample_size=1, evidence_quality=1,
        condition="Near Mint", language="English", source_country="GB",
    )


def guide(price, *, source="CARDMARKET", kind="PRICE_GUIDE", days=1, country=None):
    return MarketObservation(
        source=source, observation_type=kind,
        observed_at=NOW-timedelta(days=days), price_gbp_minor=price,
        evidence_quality=1, condition="Near Mint", language="English",
        source_country=country,
    )


def calc(data, **changes):
    return calculate_price(data, target=TARGET, policy=POLICY, as_of=NOW, **changes)


def test_duplicated_sale_cannot_manufacture_five_independent_comps():
    one = sold(10_000, "same-listing")
    result = calc([one] * 5)
    assert result.sold_observation_count == result.observation_count == 1
    assert result.excluded_observation_count == 4
    assert "INSUFFICIENT_INDEPENDENT_SALES" in result.block_reasons
    assert "INVALID_OR_DUPLICATE_EVIDENCE_EXCLUDED" in result.block_reasons
    assert not result.auto_publish_eligible
    # Even a huge count on one SOLD row means one independently sourced sale.
    oversized = calc([replace(one, sample_size=100_000)])
    assert oversized.sold_observation_count == 1
    assert not oversized.auto_publish_eligible


def test_conflicting_prices_with_same_provider_sale_id_are_quarantined():
    conflict = [sold(10_000, "clash"), sold(800_000, "clash")]
    with pytest.raises(ValueError, match="No comparable"):
        calc(conflict)
    valid = [sold(11_000+i*50, str(i)) for i in range(5)]
    result = calc(valid + conflict)
    assert result.excluded_observation_count == 2
    assert result.sold_observation_count == 5
    assert 11_000 <= result.market_value_minor <= 11_200
    assert not result.auto_publish_eligible


def test_guides_active_listings_and_us_comps_cannot_automatically_publish():
    rows = [guide(9_950)]
    rows += [sold(10_000+i*20, str(i), source="TCGPLAYER") for i in range(15)]
    rows.append(guide(50_000, source="EBAY", kind="ACTIVE", country="GB"))
    result = calc(rows)
    assert result.market_value_minor == 9_950
    assert "INSUFFICIENT_INDEPENDENT_SALES" in result.block_reasons
    assert not result.auto_publish_eligible
    with pytest.raises(ValueError, match="No UK/EU market anchor"):
        calc([guide(80_000, source="EBAY", kind="ACTIVE", country="GB")])
    with pytest.raises(ValueError, match="No UK/EU market anchor"):
        calc([guide(75_000, country="US")])


def test_stale_future_invalid_currency_region_and_malformed_evidence_are_rejected():
    invalid = [
        guide(500_000, days=8),
        sold(100_000, "old", days=91),
        replace(sold(100_000, "future"), observed_at=NOW+timedelta(days=1)),
        replace(sold(999_000, "bool"), price_gbp_minor=True),
        replace(sold(999_000, "wrong-country"), source_country="US"),
        replace(guide(50_000), evidence_quality=float("nan")),
        replace(guide(50_000), evidence_quality=float("inf")),
        replace(sold(5, "unknown"), source="fake-uk-feed"),
        replace(sold(42, "naive"), observed_at=NOW.replace(tzinfo=None)),
        replace(sold(42, "partial-grade"), grading_company="PSA"),
        replace(sold(42, "lang-malformed"), language=42),
        None, "bad-provider-payload",
    ]
    result = calc(invalid + [guide(12_300)])
    assert result.market_value_minor == 12_300
    assert result.excluded_observation_count == len(invalid)-1 # US country is valid supporting evidence but not anchor
    assert not result.auto_publish_eligible
    assert "INVALID_OR_DUPLICATE_EVIDENCE_EXCLUDED" in result.block_reasons


def test_incomplete_physical_language_condition_remains_nonpublishable_guide():
    q = replace(guide(3_000), language=None, condition=None)
    result = calc([q])
    assert result.market_value_minor == 3_000
    assert "INCOMPLETE_PHYSICAL_MATCH_BASIS" in result.block_reasons
    assert not result.auto_publish_eligible


def test_wild_one_source_sales_volatility_triggers_human_review():
    result = calc([sold(value, str(i)) for i,value in
                   enumerate((9_700,9_900,10_000,10_300,100_000))])
    assert 9_700 <= result.market_value_minor <= 10_300
    assert result.volatility_pct > 25
    assert "HIGH_VOLATILITY" in result.block_reasons
    assert not result.auto_publish_eligible


def test_policy_nan_invalid_grade_and_bad_multipliers_fail_closed():
    rows = [sold(10_000, "1")]
    for changes in ({"min_confidence":float("nan")}, {"retail_multiplier":float("inf")},
                    {"quick_sale_multiplier":-1}, {"max_volatility_pct":-1},
                    {"min_sources":0}, {"acquisition_multiplier":0}):
        with pytest.raises(ValueError, match="Invalid pricing policy"):
            calculate_price(rows,target=TARGET,policy=replace(POLICY,**changes),as_of=NOW)
    for target in (replace(TARGET,grading_company="PSA"),
                   replace(TARGET,grade="10"),replace(TARGET,language=100)):
        with pytest.raises(ValueError, match="Invalid physical pricing target|Grading company and grade"):
            calculate_price(rows,target=target,policy=POLICY,as_of=NOW)


def test_five_distinct_sold_records_can_pass_relaxed_human_review_policy():
    result = calc([sold(10_000+i*20,str(i)) for i in range(5)])
    assert result.source_count == 1
    assert result.sold_observation_count == 5
    assert result.excluded_observation_count == 0
    assert "INSUFFICIENT_INDEPENDENT_SALES" not in result.block_reasons
    assert result.auto_publish_eligible
    assert result.algorithm_version == ALGORITHM_VERSION
    assert result.ruleset_revision == RULESET_REVISION


def test_price_calculation_stress_4096_input_orders_us_support_outliers_and_replays():
    rng=Random(721094)
    for trial in range(4096):
        base=rng.randint(101,100_000)
        sales=[sold(max(1,base+rng.randint(-max(base//20,1),max(base//20,1))),str(i))
               for i in range(5)]
        data=sales+[guide(max(1,base+rng.randint(-base//10,base//10)))]
        result=calc(data)
        backwards=calc(data[::-1])
        assert result.market_value_minor==backwards.market_value_minor
        assert result.confidence==backwards.confidence
        assert result.sold_observation_count==backwards.sold_observation_count
        assert result.auto_publish_eligible==backwards.auto_publish_eligible
        assert 0 < result.market_value_minor <= max(x.price_gbp_minor for x in data)
        assert 0<=result.confidence<=1
        assert result.source_count==2
        if trial%7==0:
            supporting=calc(data+[guide(9_999_999,source="TCGPLAYER")])
            assert supporting.market_value_minor==result.market_value_minor
        if trial%9==0:
            replay=calc(data+[data[0]])
            assert replay.market_value_minor==result.market_value_minor
            assert replay.excluded_observation_count==1
            assert not replay.auto_publish_eligible
