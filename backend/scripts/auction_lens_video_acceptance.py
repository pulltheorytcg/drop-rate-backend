"""Offline, privacy-preserving Auction Lens accuracy/latency release gate.

Consumes a JSONL log of *labelled* results from authorised auction-style footage.
NO video/frames, links, usernames, account identifiers or secrets are accepted.
This is not a simulator of real recognition; tests with synthetic cases only
verify the measurement harness, not the product's measured accuracy.

Example:
 python backend/scripts/auction_lens_video_acceptance.py results.jsonl \
     --min-exact-precision 0.995 --min-coverage 0.75 --p95-ms 4000
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ALLOWED_FIELDS = frozenset({
    "case_id", "cohort", "expected_identity", "returned_identity",
    "decision", "elapsed_ms", "expected_generation", "returned_generation",
    "price_displayed", "market_value_eligible", "source_authorised",
    "lot_changed_during_request",
})
REQUIRED_FIELDS = ALLOWED_FIELDS
DECISIONS = frozenset({"EXACT", "CHECK_VERSION", "NO_MATCH", "NO_VALUE", "ERROR"})
COHORTS = frozenset({
    "english_pokemon_raw", "japanese_pokemon_raw", "one_piece_raw",
    "graded", "sealed", "comics", "manga", "multiple_items",
    "blurred", "mirrored", "lookalike", "no_collectible", "lot_transition",
})


@dataclass(frozen=True)
class AcceptanceSummary:
    cases: int
    exact_matched: int
    returned_exact: int
    supported_cases: int
    wrong_exact: int
    stale_generation: int
    unsafe_price: int
    unauthorized_cases: int
    precision: float | None
    coverage: float | None
    median_ms: float | None
    p95_ms: float | None
    by_cohort: dict[str, dict[str, int]]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _record(value: object, index: int) -> dict:
    if not isinstance(value, dict) or set(value) != ALLOWED_FIELDS:
        raise ValueError(f"Row {index}: unexpected/missing keys; use privacy-safe manifest")
    if not isinstance(value["case_id"], str) or not value["case_id"].strip():
        raise ValueError(f"Row {index}: invalid case_id")
    if value["cohort"] not in COHORTS:
        raise ValueError(f"Row {index}: invalid cohort")
    for name in ("expected_identity", "returned_identity"):
        if value[name] is not None and (
            not isinstance(value[name], str) or not value[name].strip()
            or len(value[name]) > 160
        ):
            raise ValueError(f"Row {index}: invalid {name}")
    if value["decision"] not in DECISIONS:
        raise ValueError(f"Row {index}: invalid decision")
    for name in ("expected_generation", "returned_generation"):
        _positive_int(value[name], f"Row {index} {name}")
    elapsed = value["elapsed_ms"]
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError(f"Row {index}: elapsed_ms must be finite and >= 0")
    for name in ("price_displayed", "market_value_eligible",
                 "source_authorised", "lot_changed_during_request"):
        if type(value[name]) is not bool:
            raise ValueError(f"Row {index}: {name} must be boolean")
    return value


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    rank = math.ceil(fraction * len(sorted_values))
    return sorted_values[max(0, rank - 1)]


def evaluate(records: list[dict]) -> AcceptanceSummary:
    if not records:
        raise ValueError("At least one labelled authorised footage case is required")
    seen: set[str] = set()
    correct = returned = wrong = supported = stale = unsafe = unauthorized = 0
    timings: list[float] = []
    by_cohort: dict[str, Counter] = {}
    for index, raw in enumerate(records, 1):
        row = _record(raw, index)
        if row["case_id"] in seen:
            raise ValueError(f"Row {index}: duplicate case_id")
        seen.add(row["case_id"])
        c = by_cohort.setdefault(row["cohort"], Counter())
        c["cases"] += 1
        is_exact = row["decision"] == "EXACT"
        is_correct = (is_exact
                      and row["expected_identity"] is not None
                      and row["expected_identity"] == row["returned_identity"]
                      and row["expected_generation"] == row["returned_generation"]
                      and not row["lot_changed_during_request"])
        if row["expected_identity"] is not None:
            supported += 1
            c["supported_cases"] += 1
        if is_exact:
            returned += 1
            c["returned_exact"] += 1
            if is_correct:
                correct += 1
                c["exact_matched"] += 1
            else:
                wrong += 1
                c["wrong_exact"] += 1
        if row["returned_generation"] != row["expected_generation"] or (
            row["lot_changed_during_request"] and is_exact
        ):
            stale += 1
            c["stale_generation"] += 1
        if row["price_displayed"] and (
            not is_correct or not row["market_value_eligible"]
            or not row["source_authorised"]
        ):
            unsafe += 1
            c["unsafe_price"] += 1
        if not row["source_authorised"]:
            unauthorized += 1
            c["unauthorized_cases"] += 1
        timings.append(float(row["elapsed_ms"]))
    return AcceptanceSummary(
        cases=len(records), exact_matched=correct, returned_exact=returned,
        supported_cases=supported, wrong_exact=wrong,
        stale_generation=stale, unsafe_price=unsafe,
        unauthorized_cases=unauthorized,
        precision=correct / returned if returned else None,
        coverage=correct / supported if supported else None,
        median_ms=statistics.median(timings),
        p95_ms=_percentile(timings, .95),
        by_cohort={key: dict(count) for key, count in sorted(by_cohort.items())},
    )


def gate(summary: AcceptanceSummary, *, min_exact_precision: float,
         min_coverage: float, p95_ms: float, min_cases: int) -> list[str]:
    if not 0 <= min_exact_precision <= 1 or not 0 <= min_coverage <= 1:
        raise ValueError("Precision/coverage thresholds must lie between 0 and 1")
    if p95_ms <= 0 or min_cases < 1:
        raise ValueError("Invalid performance/sample gate")
    failures = []
    if summary.cases < min_cases:
        failures.append("INSUFFICIENT_CASES")
    if summary.wrong_exact:
        failures.append("WRONG_EXACT_MATCH")
    if summary.stale_generation:
        failures.append("STALE_GENERATION")
    if summary.unsafe_price:
        failures.append("UNSAFE_PRICE")
    if summary.unauthorized_cases:
        failures.append("SOURCE_NOT_AUTHORISED")
    if summary.precision is None or summary.precision < min_exact_precision:
        failures.append("PRECISION_GATE")
    if summary.coverage is None or summary.coverage < min_coverage:
        failures.append("COVERAGE_GATE")
    if summary.p95_ms is None or summary.p95_ms > p95_ms:
        failures.append("P95_LATENCY_GATE")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--min-exact-precision", type=float, default=.995)
    parser.add_argument("--min-coverage", type=float, default=.75)
    parser.add_argument("--p95-ms", type=float, default=4000)
    parser.add_argument("--min-cases", type=int, default=100)
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    summary = evaluate(rows)
    failures = gate(summary, min_exact_precision=args.min_exact_precision,
                    min_coverage=args.min_coverage, p95_ms=args.p95_ms,
                    min_cases=args.min_cases)
    print(json.dumps({"status": "PASS" if not failures else "FAIL",
                      "failures": failures, "metrics": summary.to_dict()},
                     indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
