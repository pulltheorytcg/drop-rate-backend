"""Offline, time-ordered accuracy measurement for the existing UK pricing core.

No source calls, database writes, automatic repricing, or fitted constants.
A price is predicted immediately before a later UK sale using only records
already ingested then. Imported historical data is not retroactively available.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from statistics import median
from typing import Iterable

from .pricing_engine import ComparableTarget, MarketObservation, calculate_price

DIMENSIONS = ("condition", "grading_company", "grade", "language", "seal_status")
WINDOWS = (5, 10, 20)
MINIMUM_SALES = 5


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    catalogue_id: str
    category: str
    available_at: datetime
    observation: MarketObservation
    shipping_gbp_minor: int | None = None


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _basis(observation: MarketObservation) -> tuple:
    return tuple((getattr(observation, name) or "").strip().casefold() for name in DIMENSIONS)


def _valid_sale(record: EvidenceRecord) -> bool:
    o = record.observation
    return (
        bool(record.catalogue_id.strip()) and bool(record.category.strip())
        and _aware(record.available_at) and _aware(o.observed_at)
        and record.available_at >= o.observed_at
        and o.source == "EBAY" and o.source_country == "GB" and o.observation_type == "SOLD"
        and isinstance(o.source_record_key, str) and bool(o.source_record_key.strip())
        and type(o.price_gbp_minor) is int and 0 < o.price_gbp_minor <= 1_000_000_000_000
        and type(o.sample_size) is int and o.sample_size == 1
        and isinstance(o.evidence_quality, (int, float)) and 0 < o.evidence_quality <= 1
        and all(getattr(o, name) is None or isinstance(getattr(o, name), str) for name in DIMENSIONS)
        and bool(o.language and o.language.strip())
        and ((o.grading_company is None) == (o.grade is None))
        and bool(o.condition or (o.grading_company and o.grade) or o.seal_status)
    )


def _facts(record: EvidenceRecord) -> tuple:
    o = record.observation
    return (record.catalogue_id, record.category, _basis(o), o.observed_at,
            o.price_gbp_minor, o.evidence_quality, o.sample_size)


def _unique(records: Iterable[EvidenceRecord]) -> tuple[list[EvidenceRecord], int]:
    """Collapse repeated receipts, exclude contradictory facts for one sale."""
    by_id: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        by_id[record.observation.source_record_key.strip()].append(record)
    result = []
    conflicts = 0
    for same_id in by_id.values():
        if len({_facts(r) for r in same_id}) != 1:
            conflicts += 1
            continue
        result.append(min(same_id, key=lambda r: r.available_at))
    return result, conflicts


def evaluate_accuracy(records: Iterable[EvidenceRecord], *, expected_categories: Iterable[str] = (),
                      price_basis: str = "item") -> dict:
    """Compare 5/10/20-sale windows on the same later observed transactions.

    Item-price and delivered-price runs are separate; shipping is never guessed.
    Report all categories, including zero eligible holdouts. No weights or
    production policy are changed by this diagnostic.
    """
    records = list(records)
    if price_basis not in {"item", "delivered"}:
        raise ValueError("price_basis must be item or delivered")
    categories = sorted({r.category for r in records} | set(expected_categories))
    valid = [r for r in records if _valid_sale(r)]
    invalid_records = len(records) - len(valid)
    missing_shipping = 0
    if price_basis == "delivered":
        with_shipping = [r for r in valid if type(r.shipping_gbp_minor) is int
                         and 0 <= r.shipping_gbp_minor <= 1_000_000_000_000
                         and r.observation.price_gbp_minor + r.shipping_gbp_minor <= 1_000_000_000_000]
        missing_shipping = len(valid) - len(with_shipping)
        valid = [replace(r, observation=replace(r.observation,
                 price_gbp_minor=r.observation.price_gbp_minor + r.shipping_gbp_minor))
                 for r in with_shipping]
    outcomes, truth_conflicts = _unique(valid)
    groups: dict[tuple, list[EvidenceRecord]] = defaultdict(list)
    for record in valid:
        groups[(record.catalogue_id, _basis(record.observation))].append(record)
    versions = defaultdict(list)
    for record in valid:
        versions[record.observation.source_record_key.strip()].append(record)
    errors: dict[tuple, list[tuple[float, int, float]]] = defaultdict(list)
    scored = defaultdict(int)
    skipped = defaultdict(int)
    eligible_truths = defaultdict(int)
    prior_sales = []
    different_window_predictions = 0
    tier_errors = defaultdict(list)
    for later in sorted(outcomes, key=lambda r: (r.observation.observed_at, r.observation.source_record_key)):
        sale = later.observation
        eligible_truths[later.category] += 1
        # Strictly earlier observation and ingestion times exclude the held-out
        # sale, simultaneous batches, later receipts and look-ahead leakage.
        known = [
            r for r in groups[(later.catalogue_id, _basis(sale))]
            if sale.observed_at - timedelta(days=90) <= r.observation.observed_at < sale.observed_at
            and r.available_at < sale.observed_at
            and r.observation.source_record_key != sale.source_record_key
        ]
        known, _ = _unique(known)
        # A listing assigned to two products is not independent evidence for
        # either product. Inspect only versions already known at this cutoff.
        known = [r for r in known if len({
            _facts(v) for v in versions[r.observation.source_record_key.strip()]
            if v.available_at < sale.observed_at
        }) == 1]
        known.sort(key=lambda r: (r.observation.observed_at, r.observation.source_record_key), reverse=True)
        if len(known) < MINIMUM_SALES:
            skipped[later.category] += 1
            continue
        target = ComparableTarget(**{name: getattr(sale, name) for name in DIMENSIONS})
        predictions = {}
        for window in WINDOWS:
            try:
                result = calculate_price(
                    [r.observation for r in known[:window]],
                    target=target, as_of=sale.observed_at,
                )
            except ValueError:
                break
            predictions[window] = result.market_value_minor
        if len(predictions) != len(WINDOWS):
            skipped[later.category] += 1
            continue
        scored[later.category] += 1
        prior_sales.append(len(known))
        different_window_predictions += len(set(predictions.values())) > 1
        tier = "UNDER_GBP_5" if sale.price_gbp_minor < 500 else (
            "GBP_5_TO_50" if sale.price_gbp_minor < 5000 else "GBP_50_AND_OVER")
        for window, predicted in predictions.items():
            delta = predicted - sale.price_gbp_minor
            error = (abs(delta) / sale.price_gbp_minor * 100, abs(delta), delta / sale.price_gbp_minor * 100)
            errors[(later.category, window)].append(error)
            tier_errors[(tier, window)].append(error)

    def metrics(rows: list[tuple]) -> dict:
        if not rows:
            return dict(n=0, median_absolute_percentage_error=None,
                        median_absolute_error_gbp=None, median_signed_percentage_error=None,
                        within_10_percent=None, within_20_percent=None)
        return dict(
            n=len(rows),
            median_absolute_percentage_error=round(median(x[0] for x in rows), 4),
            median_absolute_error_gbp=round(median(x[1] for x in rows) / 100, 4),
            median_signed_percentage_error=round(median(x[2] for x in rows), 4),
            within_10_percent=round(sum(x[0] <= 10 for x in rows) / len(rows), 4),
            within_20_percent=round(sum(x[0] <= 20 for x in rows) / len(rows), 4),
        )

    return {
        "method": "UK_SOLD_WALK_FORWARD_V1",
        "price_basis": "GBP_ITEM_PRICE_EXCLUDING_SHIPPING" if price_basis == "item" else "GBP_DELIVERED_PRICE",
        "minimum_prior_independent_sales": MINIMUM_SALES,
        "requires_ingested_before_holdout": True,
        "input_records": len(records),
        "invalid_records": invalid_records,
        "missing_or_invalid_shipping_records": missing_shipping,
        "conflicting_sale_ids": truth_conflicts,
        "independent_sales": len(outcomes),
        "scored_sales_with_more_than_five_prior": sum(n > 5 for n in prior_sales),
        "maximum_prior_sales": max(prior_sales, default=0),
        "holdouts_with_different_window_predictions": different_window_predictions,
        "price_tiers": {
            tier: {str(w): metrics(tier_errors[(tier, w)]) for w in WINDOWS}
            for tier in ("UNDER_GBP_5", "GBP_5_TO_50", "GBP_50_AND_OVER")
        },
        "categories": [
            {"category": category, "independent_sales": eligible_truths[category],
             "scored_sales": scored[category], "insufficient_prior_evidence": skipped[category],
             "windows": {str(w): metrics(errors[(category, w)]) for w in WINDOWS}}
            for category in categories
        ],
        "overall_windows": {
            str(w): metrics([row for category in categories for row in errors[(category, w)]])
            for w in WINDOWS
        },
        "production_prices_changed": False,
    }

