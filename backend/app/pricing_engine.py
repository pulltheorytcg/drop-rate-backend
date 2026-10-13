from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import exp, isfinite, log, sqrt
from statistics import median
from typing import Iterable

from .pricing_rules import store_price_floor


ALGORITHM_VERSION = "drop-rate-market-v4"
# Keep the persisted v4 identifier compatible with the existing database CHECKs
# and historical snapshots. Record the exact hardening rule revision separately.
RULESET_REVISION = "2026-10-13-source-integrity-1"
MAX_MARKET_VALUE_MINOR = 1_000_000_000_000
MAX_FUTURE_CLOCK_DRIFT = timedelta(minutes=5)

SOURCE_RELIABILITY = {
    "EBAY": 1.00,
    "CARDMARKET": 0.98,
    "COLLECTR": 0.70,
    "TCGPLAYER": 0.75,
    "MANUAL": 1.00,
}

# Drop Rate is a UK marketplace. These factors affect confidence/supporting
# evidence only. The displayed Market Value is derived exclusively from UK/EU
# anchor observations (eBay UK and Cardmarket) so US/global prices can never
# become the customer-facing UK valuation by currency conversion alone.
UK_MARKET_RELEVANCE = {
    "EBAY": 1.00,
    "CARDMARKET": 0.95,
    "COLLECTR": 0.70,
    "TCGPLAYER": 0.60,
    "MANUAL": 1.00,
}

TYPE_QUALITY = {
    "SOLD": 1.00,
    "MARKET_AGGREGATE": 0.85,
    "PRICE_GUIDE": 0.75,
    "ACTIVE": 0.35,
}

HALF_LIFE_DAYS = {
    "SOLD": 21.0,
    "MARKET_AGGREGATE": 7.0,
    "PRICE_GUIDE": 7.0,
    "ACTIVE": 3.0,
}

# Never use old or future evidence as a current GBP anchor, no matter how many
# supporting USD/global observations are present. Daily Cardmarket guides are
# not completed sales and are intentionally subject to a shorter window.
MAX_OBSERVATION_AGE_DAYS = {
    "SOLD": 90,
    "MARKET_AGGREGATE": 7,
    "PRICE_GUIDE": 7,
    "ACTIVE": 3,
}


@dataclass(frozen=True, slots=True)
class ComparableTarget:
    condition: str | None = None
    grading_company: str | None = None
    grade: str | None = None
    language: str | None = None
    seal_status: str | None = None


@dataclass(frozen=True, slots=True)
class MarketObservation:
    source: str
    observation_type: str
    observed_at: datetime
    price_gbp_minor: int
    sample_size: int = 1
    evidence_quality: float = 1.0
    condition: str | None = None
    grading_company: str | None = None
    grade: str | None = None
    language: str | None = None
    seal_status: str | None = None
    source_country: str | None = None
    # Exact provider sale/listing ID. A duplicate event must not create another
    # independent sold comparable or inflate confidence in one seller's price.
    source_record_key: str | None = None


@dataclass(frozen=True, slots=True)
class PricingPolicy:
    min_confidence: float = 0.80
    min_sources: int = 2
    max_auto_change_pct: float = 10.0
    high_value_review_minor: int = 50_000
    min_price_change_minor: int = 100
    min_price_change_pct: float = 2.0
    max_volatility_pct: float = 20.0
    retail_multiplier: float = 1.0
    quick_sale_multiplier: float = 0.92
    acquisition_multiplier: float = 0.70


@dataclass(frozen=True, slots=True)
class SourceEstimate:
    source: str
    estimate_minor: int
    weight: float
    observation_count: int
    sold_observation_count: int
    newest_observation_at: datetime
    freshness: float
    evidence_quality: float
    market_relevance: float


@dataclass(frozen=True, slots=True)
class PricingResult:
    market_value_minor: int
    recommended_retail_minor: int
    quick_sale_minor: int
    target_acquisition_minor: int
    confidence: float
    source_count: int
    observation_count: int
    sold_observation_count: int
    volatility_pct: float
    newest_observation_at: datetime
    algorithm_version: str
    auto_publish_eligible: bool
    block_reasons: tuple[str, ...]
    source_estimates: tuple[SourceEstimate, ...]
    ruleset_revision: str = RULESET_REVISION
    excluded_observation_count: int = 0


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().casefold()
    return cleaned or None


def _dimension_match(observed: str | None, target: str | None, *, strict_missing: bool = False) -> tuple[bool, float]:
    observed_norm = _norm(observed)
    target_norm = _norm(target)
    if target_norm is None:
        return observed_norm is None, 1.0
    if observed_norm is None:
        return (False, 0.0) if strict_missing else (True, 0.75)
    return (observed_norm == target_norm, 1.0 if observed_norm == target_norm else 0.0)


def comparable_quality(observation: MarketObservation, target: ComparableTarget) -> float:
    """Return deterministic comparable quality for one market observation.

    For graded cards, grading company + exact grade define physical condition.
    Marketplace condition labels such as "Used" or "New (other)" describe the
    slab/listing and must not cause an otherwise exact PSA/CGC/BGS comparable to
    be discarded. Raw cards still require the normal condition comparison.
    """

    graded_target = _norm(target.grading_company) is not None and _norm(target.grade) is not None

    company_ok, company_factor = _dimension_match(
        observation.grading_company,
        target.grading_company,
        strict_missing=target.grading_company is not None,
    )
    grade_ok, grade_factor = _dimension_match(
        observation.grade,
        target.grade,
        strict_missing=target.grade is not None,
    )
    if graded_target:
        condition_ok, condition_factor = True, 1.0
    else:
        condition_ok, condition_factor = _dimension_match(observation.condition, target.condition)
    language_ok, language_factor = _dimension_match(observation.language, target.language)
    seal_ok, seal_factor = _dimension_match(observation.seal_status, target.seal_status)
    if not all((company_ok, grade_ok, condition_ok, language_ok, seal_ok)):
        return 0.0
    return company_factor * grade_factor * condition_factor * language_factor * seal_factor


def recency_weight(observation: MarketObservation, as_of: datetime) -> float:
    observed_at = observation.observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    age_seconds = max((as_of - observed_at).total_seconds(), 0.0)
    age_days = age_seconds / 86_400.0
    half_life = HALF_LIFE_DAYS.get(observation.observation_type, 7.0)
    return exp(-log(2.0) * age_days / half_life)


def weighted_median(values: list[tuple[int, float]]) -> int:
    valid = sorted(
        (value, weight)
        for value, weight in values
        if type(value) is int and value > 0
        and isinstance(weight, (int, float)) and isfinite(weight) and weight > 0
    )
    if not valid:
        raise ValueError("weighted median requires at least one positive weight")
    total = sum(weight for _, weight in valid)
    if not isfinite(total):
        raise ValueError("weighted median total weight must be finite")
    threshold = total / 2.0
    running = 0.0
    for value, weight in valid:
        running += weight
        if running >= threshold:
            return int(value)
    return int(valid[-1][0])


def _remove_extreme_outliers(observations: list[MarketObservation]) -> list[MarketObservation]:
    if len(observations) < 5:
        return observations
    prices = [item.price_gbp_minor for item in observations]
    centre = float(median(prices))
    deviations = [abs(value - centre) for value in prices]
    mad = float(median(deviations))
    robust_sigma = 1.4826 * mad
    threshold = max(3.5 * robust_sigma, centre * 0.35, 100.0)
    filtered = [item for item in observations if abs(item.price_gbp_minor - centre) <= threshold]
    return filtered if len(filtered) >= 3 else observations


def _market_relevance(source: str, observations: list[MarketObservation]) -> float:
    if source == "EBAY":
        if any((item.source_country or "").upper() == "GB" for item in observations):
            return 1.20
        return 0.65
    return UK_MARKET_RELEVANCE.get(source, 0.65)


def _is_uk_eu_anchor(observation: MarketObservation, target: ComparableTarget) -> bool:
    if comparable_quality(observation, target) <= 0:
        return False
    source = observation.source.upper().strip()
    country = (observation.source_country or "").upper().strip()
    if observation.observation_type == "ACTIVE":
        # An unsold asking price is only supporting context, not evidence of
        # clearing price, even when the seller is UK-based.
        return False
    if source == "CARDMARKET":
        # Cardmarket is the regional guide anchor, but do not relabel a source
        # record explicitly located outside Europe as a UK/EU price.
        return country in {"", "EU", "GB", "UK", "FR", "DE", "IT", "ES", "NL", "BE", "PT", "IE", "AT", "PL", "DK", "SE", "FI", "CZ", "SK", "HU", "RO", "BG", "HR", "SI", "EE", "LV", "LT", "LU", "GR", "CY", "MT"}
    return source == "EBAY" and country == "GB" and observation.observation_type == "SOLD"



def _eligible_observations(
    observations: list[MarketObservation], as_of: datetime,
) -> tuple[list[MarketObservation], int]:
    """Reject invalid, stale, future and duplicated evidence before pricing.

    One SOLD row represents **one** independent transaction, irrespective of a
    provider-supplied sample_size field. Provider IDs are authoritative for
    deduplication; conflicting payloads for one ID are quarantined, never
    resolved by whichever happens to arrive last. Legacy rows without IDs are
    deduplicated by their complete observed facts.
    """
    accepted: dict[tuple, MarketObservation] = {}
    conflicts: set[tuple] = set()
    rejected = 0
    for observation in observations:
        if not isinstance(observation, MarketObservation):
            rejected += 1
            continue
        source = str(observation.source or "").strip().upper()
        kind = str(observation.observation_type or "").strip().upper()
        at = observation.observed_at
        quality = observation.evidence_quality
        size = observation.sample_size
        if (
            source not in SOURCE_RELIABILITY
            or kind not in TYPE_QUALITY
            or type(observation.price_gbp_minor) is not int
            or not 0 < observation.price_gbp_minor <= MAX_MARKET_VALUE_MINOR
            or type(size) is not int or size < 1 or size > 1_000_000
            or not isinstance(quality, (int, float)) or not isfinite(quality)
            or not 0 < quality <= 1
            or not isinstance(at, datetime)
            or (observation.grading_company is None) != (observation.grade is None)
            or any(
                value is not None and not isinstance(value, str)
                for value in (
                    observation.condition, observation.grading_company,
                    observation.grade, observation.language, observation.seal_status,
                    observation.source_country, observation.source_record_key,
                )
            )
        ):
            rejected += 1
            continue
        if at.tzinfo is None or at.utcoffset() is None:
            # A source's timezone is part of the evidence, not a guess.
            rejected += 1
            continue
        at = at.astimezone(timezone.utc)
        if (
            at > as_of + MAX_FUTURE_CLOCK_DRIFT
            or at < as_of - timedelta(days=MAX_OBSERVATION_AGE_DAYS[kind])
        ):
            rejected += 1
            continue
        key = str(observation.source_record_key or "").strip() or None
        canonical = replace(
            observation, source=source, observation_type=kind,
            observed_at=at, source_country=(observation.source_country or "").strip().upper() or None,
            sample_size=1 if kind == "SOLD" else min(size, 25),
            source_record_key=key,
        )
        dedup_key = (
            ("provider", source, key)
            if key is not None else ("facts", canonical)
        )
        if dedup_key in conflicts:
            rejected += 1
        elif dedup_key in accepted:
            if accepted[dedup_key] != canonical:
                conflicts.add(dedup_key)
                accepted.pop(dedup_key)
                rejected += 2  # Both conflicting provider records are invalid.
            else:
                rejected += 1
        else:
            accepted[dedup_key] = canonical
    return list(accepted.values()), rejected


def _validate_policy(policy: PricingPolicy, target: ComparableTarget) -> None:
    """Reject invalid policy/target configuration instead of publishing a NaN.

    Normally FastAPI/DB enforce this, but a corrupted batch job, replay or
    manually supplied policy must fail closed in the deterministic core too.
    """
    for value in (target.condition, target.grading_company, target.grade, target.language, target.seal_status):
        if value is not None and not isinstance(value, str):
            raise ValueError("Invalid physical pricing target")
    if (target.grading_company is None) != (target.grade is None):
        raise ValueError("Grading company and grade must both be present")
    for name, maximum in (
        ("min_confidence", 1), ("max_auto_change_pct", 100),
        ("min_price_change_pct", 100), ("max_volatility_pct", 500),
        ("retail_multiplier", 5), ("quick_sale_multiplier", 5),
        ("acquisition_multiplier", 5),
    ):
        value = getattr(policy, name)
        if not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= maximum:
            raise ValueError(f"Invalid pricing policy: {name}")
    if (min(policy.retail_multiplier, policy.quick_sale_multiplier, policy.acquisition_multiplier) <= 0
            or type(policy.min_sources) is not int or not 1 <= policy.min_sources <= 10
            or type(policy.min_price_change_minor) is not int or policy.min_price_change_minor < 0
            or type(policy.high_value_review_minor) is not int or policy.high_value_review_minor < 0):
        raise ValueError("Invalid pricing policy")

def _source_estimate(
    source: str,
    observations: list[MarketObservation],
    target: ComparableTarget,
    as_of: datetime,
) -> SourceEstimate | None:
    comparable: list[tuple[MarketObservation, float]] = []
    for observation in observations:
        dimension_quality = comparable_quality(observation, target)
        if dimension_quality <= 0:
            continue
        freshness = recency_weight(observation, as_of)
        type_quality = TYPE_QUALITY.get(observation.observation_type, 0.25)
        weight = (
            max(0.0, min(observation.evidence_quality, 1.0))
            * dimension_quality
            * freshness
            * type_quality
            * max(1.0, sqrt(min(observation.sample_size, 25)))
        )
        if weight > 0:
            comparable.append((observation, weight))
    if not comparable:
        return None

    filtered_observations = _remove_extreme_outliers([item for item, _ in comparable])
    allowed_ids = {id(item) for item in filtered_observations}
    weighted_prices = [
        (item.price_gbp_minor, weight)
        for item, weight in comparable
        if id(item) in allowed_ids
    ]
    estimate = weighted_median(weighted_prices)
    newest = max(item.observed_at for item in filtered_observations)
    avg_freshness = sum(recency_weight(item, as_of) for item in filtered_observations) / len(filtered_observations)
    avg_quality = sum(item.evidence_quality for item in filtered_observations) / len(filtered_observations)
    sold_count = sum(item.sample_size for item in filtered_observations if item.observation_type == "SOLD")
    market_relevance = _market_relevance(source, filtered_observations)
    source_weight = (
        SOURCE_RELIABILITY.get(source, 0.70)
        * market_relevance
        * max(0.10, avg_freshness)
        * max(0.10, avg_quality)
        * min(1.50, 1.0 + 0.15 * sqrt(len(filtered_observations)))
    )
    return SourceEstimate(
        source=source,
        estimate_minor=estimate,
        weight=source_weight,
        observation_count=len(filtered_observations),
        sold_observation_count=sold_count,
        newest_observation_at=newest,
        freshness=avg_freshness,
        evidence_quality=avg_quality,
        market_relevance=market_relevance,
    )


def _volatility_pct(estimates: Iterable[SourceEstimate], market_value_minor: int) -> float:
    values = [estimate.estimate_minor for estimate in estimates]
    if market_value_minor <= 0 or len(values) < 2:
        return 0.0
    centre = float(median(values))
    mad = float(median(abs(value - centre) for value in values))
    return round((1.4826 * mad / market_value_minor) * 100.0, 4)


def calculate_price(
    observations: list[MarketObservation],
    *,
    target: ComparableTarget,
    policy: PricingPolicy | None = None,
    current_store_price_minor: int | None = None,
    as_of: datetime | None = None,
) -> PricingResult:
    if not observations:
        raise ValueError("No market observations supplied")
    policy = policy or PricingPolicy()
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    by_source: dict[str, list[MarketObservation]] = {}
    for observation in observations:
        if observation.price_gbp_minor <= 0:
            continue
        by_source.setdefault(observation.source, []).append(observation)

    estimates = tuple(
        estimate
        for source, source_observations in sorted(by_source.items())
        if (estimate := _source_estimate(source, source_observations, target, as_of)) is not None
    )
    if not estimates:
        raise ValueError("No comparable market observations supplied")

    anchor_observations = [item for item in observations if _is_uk_eu_anchor(item, target)]
    if not anchor_observations:
        raise ValueError("No UK/EU market anchor available")

    anchors_by_source: dict[str, list[MarketObservation]] = {}
    for observation in anchor_observations:
        anchors_by_source.setdefault(observation.source, []).append(observation)
    anchor_estimates = tuple(
        estimate
        for source, source_observations in sorted(anchors_by_source.items())
        if (estimate := _source_estimate(source, source_observations, target, as_of)) is not None
    )
    if not anchor_estimates:
        raise ValueError("No comparable UK/EU market anchor available")

    # The displayed UK Market Value is determined exclusively by UK/EU anchors.
    # US/global estimates remain in source_estimates and can strengthen or weaken
    # confidence, but they never directly move the customer-facing £ valuation.
    market_value = weighted_median(
        [(estimate.estimate_minor, estimate.weight) for estimate in anchor_estimates]
    )
    observation_count = sum(estimate.observation_count for estimate in estimates)
    sold_count = sum(estimate.sold_observation_count for estimate in estimates)
    source_count = len(estimates)
    regional_sold_count = sum(estimate.sold_observation_count for estimate in anchor_estimates)
    newest = max(estimate.newest_observation_at for estimate in estimates)
    volatility = _volatility_pct(anchor_estimates, market_value)

    source_score = min(source_count / 3.0, 1.0)
    sample_score = min((sold_count / 8.0) + ((observation_count - sold_count) / 12.0), 1.0)
    freshness_score = sum(estimate.freshness for estimate in estimates) / source_count
    quality_score = sum(estimate.evidence_quality for estimate in estimates) / source_count
    confidence = 0.30 * source_score + 0.25 * sample_score + 0.25 * freshness_score + 0.20 * quality_score
    confidence -= 0.15 * min(volatility / max(policy.max_volatility_pct, 1.0), 1.0)
    confidence = round(max(0.0, min(confidence, 1.0)), 4)

    recommended = store_price_floor(round(market_value * policy.retail_multiplier))
    quick_sale = store_price_floor(round(market_value * policy.quick_sale_multiplier))
    acquisition = max(0, round(market_value * policy.acquisition_multiplier))

    block_reasons: list[str] = []
    if confidence < policy.min_confidence:
        block_reasons.append("LOW_CONFIDENCE")
    if source_count < policy.min_sources and sold_count < 5:
        block_reasons.append("INSUFFICIENT_SOURCE_DIVERSITY")
    if len(anchor_estimates) < 2 and regional_sold_count < 5:
        block_reasons.append("INSUFFICIENT_REGIONAL_EVIDENCE")
    if volatility > policy.max_volatility_pct:
        block_reasons.append("HIGH_VOLATILITY")
    if recommended >= policy.high_value_review_minor:
        block_reasons.append("HIGH_VALUE_REVIEW")

    if current_store_price_minor is not None and current_store_price_minor > 0:
        absolute_change = abs(recommended - current_store_price_minor)
        change_pct = (absolute_change / current_store_price_minor) * 100.0
        if absolute_change < policy.min_price_change_minor and change_pct < policy.min_price_change_pct:
            block_reasons.append("MIN_CHANGE_NOT_REACHED")
        if change_pct > policy.max_auto_change_pct:
            block_reasons.append("CHANGE_TOO_LARGE")

    auto_publish = not block_reasons
    return PricingResult(
        market_value_minor=market_value,
        recommended_retail_minor=recommended,
        quick_sale_minor=quick_sale,
        target_acquisition_minor=acquisition,
        confidence=confidence,
        source_count=source_count,
        observation_count=observation_count,
        sold_observation_count=sold_count,
        volatility_pct=volatility,
        newest_observation_at=newest,
        algorithm_version=ALGORITHM_VERSION,
        auto_publish_eligible=auto_publish,
        block_reasons=tuple(block_reasons),
        source_estimates=estimates,
    )
