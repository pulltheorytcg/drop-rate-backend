from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID


EVALUATION_SPLITS = {"VALIDATION", "HOLDOUT"}
TERMINAL_DECISIONS = {"EXACT_CANDIDATE", "NEEDS_REVIEW", "NO_MATCH", "FAILED"}
POSITIVE_LABELS = {"CONFIRMED_TOP", "CORRECTED_TO_CANDIDATE", "CORRECTED_BY_SEARCH"}
ALL_LABELS = POSITIVE_LABELS | {"REJECTED_ALL"}


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 5)


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    result = ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)
    return round(result, 2)


def _identifier(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _validate_row(row: Mapping[str, Any], *, expected_split: str | None) -> None:
    split = str(row.get("dataset_split") or "").strip().upper()
    if split not in EVALUATION_SPLITS:
        raise ValueError("Recognition evaluation accepts VALIDATION or HOLDOUT rows only")
    if expected_split is not None and split != expected_split:
        raise ValueError("Recognition evaluation row does not match the requested split")

    label = str(row.get("label_outcome") or "").strip().upper()
    if label not in ALL_LABELS:
        raise ValueError("Recognition evaluation row has an unsupported human label")

    selected = row.get("selected_catalogue_id")
    if label in POSITIVE_LABELS and selected is None:
        raise ValueError("Positive recognition label is missing selected catalogue truth")
    if label == "REJECTED_ALL" and selected is not None:
        raise ValueError("REJECTED_ALL recognition truth must not select a catalogue card")

    decision = str(row.get("decision") or "").strip().upper()
    if decision not in TERMINAL_DECISIONS:
        raise ValueError("Recognition evaluation requires a terminal production decision")


def _latency_ms(row: Mapping[str, Any]) -> float | None:
    raw = row.get("latency_ms")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _bucket_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sample_count = len(rows)
    decision_counts = Counter(
        str(row.get("decision") or "").strip().upper()
        for row in rows
    )
    label_counts = Counter(
        str(row.get("label_outcome") or "").strip().upper()
        for row in rows
    )

    positive_rows = [
        row
        for row in rows
        if str(row.get("label_outcome") or "").strip().upper() in POSITIVE_LABELS
    ]
    reject_all_rows = [
        row
        for row in rows
        if str(row.get("label_outcome") or "").strip().upper() == "REJECTED_ALL"
    ]
    exact_rows = [
        row
        for row in rows
        if str(row.get("decision") or "").strip().upper() == "EXACT_CANDIDATE"
    ]

    def top_is_truth(row: Mapping[str, Any]) -> bool:
        selected = _identifier(row.get("selected_catalogue_id"))
        top = _identifier(row.get("top_catalogue_id"))
        return selected is not None and selected == top

    correct_top1 = sum(1 for row in positive_rows if top_is_truth(row))
    correct_exact = sum(1 for row in exact_rows if top_is_truth(row))
    unsafe_exact = len(exact_rows) - correct_exact
    review_count = decision_counts.get("NEEDS_REVIEW", 0)
    no_match_count = decision_counts.get("NO_MATCH", 0)
    failed_count = decision_counts.get("FAILED", 0)

    latencies = [
        value
        for row in rows
        if (value := _latency_ms(row)) is not None
    ]

    return {
        "sample_count": sample_count,
        "positive_truth_count": len(positive_rows),
        "reject_all_truth_count": len(reject_all_rows),
        "decision_counts": {
            decision: int(decision_counts.get(decision, 0))
            for decision in sorted(TERMINAL_DECISIONS)
        },
        "label_counts": {
            label: int(label_counts.get(label, 0))
            for label in sorted(ALL_LABELS)
        },
        "correct_top1_count": correct_top1,
        "top1_accuracy": _ratio(correct_top1, len(positive_rows)),
        "exact_decision_count": len(exact_rows),
        "correct_exact_count": correct_exact,
        "unsafe_exact_count": unsafe_exact,
        "exact_precision": _ratio(correct_exact, len(exact_rows)),
        "exact_recall": _ratio(correct_exact, len(positive_rows)),
        "review_rate": _ratio(review_count, sample_count),
        "no_match_rate": _ratio(no_match_count, sample_count),
        "failure_rate": _ratio(failed_count, sample_count),
        "safe_abstention_rate": _ratio(review_count + no_match_count, sample_count),
        "latency_ms": {
            "sample_count": len(latencies),
            "median": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
    }


def evaluate_recognition_examples(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_split: str | None = None,
) -> dict[str, Any]:
    """Measure historical scanner quality from active human-labelled evidence only.

    This function does not rescore cards and cannot change recognition, catalogue,
    inventory, pricing, ownership or Shopify state. It measures what the production
    engine actually decided for examples that humans later labelled.
    """
    normalized_split = expected_split.strip().upper() if expected_split else None
    if normalized_split is not None and normalized_split not in EVALUATION_SPLITS:
        raise ValueError("Recognition evaluation split must be VALIDATION or HOLDOUT")

    materialized = [dict(row) for row in rows]
    for row in materialized:
        _validate_row(row, expected_split=normalized_split)

    base = _bucket_metrics(materialized)

    confusion_counter: Counter[tuple[str, str, str]] = Counter()
    risk_counter: Counter[str] = Counter()
    for row in materialized:
        label = str(row.get("label_outcome") or "").strip().upper()
        truth = _identifier(row.get("selected_catalogue_id"))
        predicted = _identifier(row.get("top_catalogue_id"))
        system = str(row.get("system_code") or "UNKNOWN")
        if label in POSITIVE_LABELS and truth and predicted and truth != predicted:
            confusion_counter[(system, predicted, truth)] += 1

        flags = row.get("risk_flags")
        if isinstance(flags, list):
            for flag in flags:
                value = str(flag or "").strip()
                if value:
                    risk_counter[value] += 1

    by_system: dict[str, dict[str, Any]] = {}
    systems = sorted(
        {
            str(row.get("system_code") or "UNKNOWN")
            for row in materialized
        }
    )
    for system in systems:
        system_rows = [
            row
            for row in materialized
            if str(row.get("system_code") or "UNKNOWN") == system
        ]
        by_system[system] = _bucket_metrics(system_rows)

    if normalized_split:
        split_name = normalized_split
    else:
        present_splits = sorted(
            {
                str(row.get("dataset_split") or "").strip().upper()
                for row in materialized
            }
        )
        split_name = present_splits[0] if len(present_splits) == 1 else "MIXED"

    return {
        "dataset_split": split_name,
        **base,
        "zero_false_exact_target_met": base["unsafe_exact_count"] == 0,
        "confusion_pairs": [
            {
                "system_code": system,
                "predicted_catalogue_id": predicted,
                "truth_catalogue_id": truth,
                "count": count,
            }
            for (system, predicted, truth), count in sorted(
                confusion_counter.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "risk_flag_counts": [
            {"risk_flag": flag, "count": count}
            for flag, count in risk_counter.most_common()
        ],
        "by_system": by_system,
        "evaluation_contract": {
            "human_labels_only": True,
            "train_split_excluded": True,
            "mutates_production_state": False,
            "auto_promotes_models_or_thresholds": False,
        },
    }


async def load_recognition_evaluation_examples(
    connection,
    *,
    owner_id: UUID,
    dataset_split: str,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Load active reviewed examples without exposing TRAIN rows to evaluation."""
    split = dataset_split.strip().upper()
    if split not in EVALUATION_SPLITS:
        raise ValueError("Recognition evaluation split must be VALIDATION or HOLDOUT")
    bounded_limit = max(1, min(int(limit), 5000))

    rows = await connection.fetch(
        """
        select
            e.id as learning_example_id,
            e.run_id,
            e.system_code,
            e.label_outcome,
            e.selected_catalogue_id,
            e.dataset_split,
            e.engine_version,
            e.vision_model,
            r.decision,
            r.top_catalogue_id,
            r.top_score,
            r.runner_up_score,
            r.score_margin,
            r.risk_flags,
            case
                when r.completed_at is not null and r.started_at is not null
                then extract(epoch from (r.completed_at-r.started_at))*1000.0
                else null
            end as latency_ms
        from tcg.recognition_learning_examples e
        join tcg.recognition_runs r on r.id=e.run_id
        where e.owner_id=$1
          and e.dataset_split=$2
          and not exists (
              select 1
              from tcg.recognition_learning_examples newer
              where newer.supersedes_example_id=e.id
          )
        order by e.created_at asc,e.id asc
        limit $3
        """,
        owner_id,
        split,
        bounded_limit,
    )
    return [dict(row) for row in rows]
