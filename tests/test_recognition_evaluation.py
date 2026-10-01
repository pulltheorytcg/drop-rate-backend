from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.recognition_evaluation import evaluate_recognition_examples


ROOT = Path(__file__).parents[1]
API = ROOT / "backend" / "app" / "recognition.py"
EVALUATION = ROOT / "backend" / "app" / "recognition_evaluation.py"


TRUTH_A = UUID("00000000-0000-0000-0000-000000000001")
TRUTH_B = UUID("00000000-0000-0000-0000-000000000002")
WRONG = UUID("00000000-0000-0000-0000-000000000003")


def row(
    *,
    selected=TRUTH_A,
    top=TRUTH_A,
    decision="EXACT_CANDIDATE",
    label="CONFIRMED_TOP",
    split="VALIDATION",
    system="ONE_PIECE",
    latency_ms=1000,
    risk_flags=None,
):
    return {
        "dataset_split": split,
        "label_outcome": label,
        "selected_catalogue_id": selected,
        "top_catalogue_id": top,
        "decision": decision,
        "system_code": system,
        "latency_ms": latency_ms,
        "risk_flags": list(risk_flags or []),
    }


def test_evaluation_counts_wrong_exact_as_unsafe_false_positive() -> None:
    result = evaluate_recognition_examples(
        [
            row(),
            row(
                selected=TRUTH_B,
                top=WRONG,
                label="CORRECTED_TO_CANDIDATE",
            ),
            row(
                selected=None,
                top=WRONG,
                label="REJECTED_ALL",
            ),
        ],
        expected_split="VALIDATION",
    )

    assert result["sample_count"] == 3
    assert result["exact_decision_count"] == 3
    assert result["correct_exact_count"] == 1
    assert result["unsafe_exact_count"] == 2
    assert result["exact_precision"] == pytest.approx(1 / 3, abs=1e-5)
    assert result["zero_false_exact_target_met"] is False
    assert result["confusion_pairs"] == [
        {
            "system_code": "ONE_PIECE",
            "predicted_catalogue_id": str(WRONG),
            "truth_catalogue_id": str(TRUTH_B),
            "count": 1,
        }
    ]


def test_review_is_measured_as_safe_abstention_not_false_exact() -> None:
    result = evaluate_recognition_examples(
        [
            row(decision="NEEDS_REVIEW", risk_flags=["AMBIGUOUS_PRINTING"]),
            row(decision="NO_MATCH"),
        ],
        expected_split="VALIDATION",
    )

    assert result["unsafe_exact_count"] == 0
    assert result["exact_decision_count"] == 0
    assert result["exact_precision"] is None
    assert result["safe_abstention_rate"] == 1.0
    assert result["risk_flag_counts"] == [
        {"risk_flag": "AMBIGUOUS_PRINTING", "count": 1}
    ]


def test_train_rows_are_rejected_from_quality_evaluation() -> None:
    with pytest.raises(ValueError, match="VALIDATION or HOLDOUT"):
        evaluate_recognition_examples([row(split="TRAIN")])


def test_requested_holdout_cannot_mix_validation_rows() -> None:
    with pytest.raises(ValueError, match="requested split"):
        evaluate_recognition_examples(
            [row(split="VALIDATION")],
            expected_split="HOLDOUT",
        )


def test_latency_percentiles_and_per_system_breakdown_are_reported() -> None:
    result = evaluate_recognition_examples(
        [
            row(latency_ms=100),
            row(latency_ms=200, system="POKEMON"),
            row(latency_ms=300, system="POKEMON"),
        ],
        expected_split="VALIDATION",
    )

    assert result["latency_ms"]["median"] == 200.0
    assert result["latency_ms"]["p95"] == 290.0
    assert result["by_system"]["ONE_PIECE"]["sample_count"] == 1
    assert result["by_system"]["POKEMON"]["sample_count"] == 2


def test_evaluation_code_is_read_only_and_api_excludes_train_split() -> None:
    source = EVALUATION.read_text()
    api = API.read_text()

    assert "insert into" not in source.casefold()
    assert "update tcg." not in source.casefold()
    assert "delete from" not in source.casefold()
    assert "VALIDATION" in source
    assert "HOLDOUT" in source
    assert 'Literal["VALIDATION", "HOLDOUT"]' in api
    assert '@router.get("/learning/evaluation")' in api
