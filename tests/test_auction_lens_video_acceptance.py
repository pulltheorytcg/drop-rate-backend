"""Only harness correctness, NOT real video recognizer accuracy."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "backend/scripts/auction_lens_video_acceptance.py"
spec = spec_from_file_location("auction_lens_video_acceptance", SCRIPT)
module = module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def case(case_id="a", **changes):
    sample = {
        "case_id": case_id,
        "cohort": "english_pokemon_raw",
        "expected_identity": "pokemon:example-print:english:normal",
        "returned_identity": "pokemon:example-print:english:normal",
        "decision": "EXACT",
        "elapsed_ms": 850,
        "expected_generation": 9,
        "returned_generation": 9,
        "price_displayed": True,
        "market_value_eligible": True,
        "source_authorised": True,
        "lot_changed_during_request": False,
    }
    sample.update(changes)
    return sample


def test_correct_labelled_case_calculates_metrics_without_video_or_private_info():
    summary = module.evaluate([case("a"), case("b", elapsed_ms=1250)])
    assert summary.cases == 2
    assert summary.exact_matched == 2
    assert summary.precision == 1
    assert summary.coverage == 1
    assert summary.median_ms == 1050
    assert summary.p95_ms == 1250
    assert module.gate(summary, min_exact_precision=.99, min_coverage=.75,
                       p95_ms=4000, min_cases=2) == []


def test_false_positive_must_fail_even_when_precision_threshold_is_lenient():
    summary = module.evaluate([case("a"),case("b",returned_identity="wrong")])
    assert summary.wrong_exact == 1
    assert "WRONG_EXACT_MATCH" in module.gate(
        summary, min_exact_precision=.5, min_coverage=.5, p95_ms=4000, min_cases=2)


def test_abstentions_are_visible_in_coverage_denominator_not_precision():
    summary = module.evaluate([
        case("a"), case("b", decision="CHECK_VERSION",
                        returned_identity=None, price_displayed=False),
    ])
    assert summary.precision == 1
    assert summary.coverage == .5
    assert "COVERAGE_GATE" in module.gate(
        summary, min_exact_precision=.99, min_coverage=.75, p95_ms=4000, min_cases=2)


@pytest.mark.parametrize("fields,reason", [
    ({"returned_generation": 8}, "STALE_GENERATION"),
    ({"lot_changed_during_request": True}, "STALE_GENERATION"),
    ({"market_value_eligible": False}, "UNSAFE_PRICE"),
    ({"source_authorised": False}, "SOURCE_NOT_AUTHORISED"),
    ({"expected_identity": None}, "WRONG_EXACT_MATCH"),
    ({"elapsed_ms": 4100}, "P95_LATENCY_GATE"),
])
def test_unsafe_cases_fail_closed(fields, reason):
    summary = module.evaluate([case(**fields)])
    assert reason in module.gate(
        summary, min_exact_precision=.0, min_coverage=.0, p95_ms=4000, min_cases=1)


@pytest.mark.parametrize("fields", [
    {"elapsed_ms": float("nan")}, {"elapsed_ms": -1}, {"elapsed_ms": "fast"},
    {"price_displayed": 1}, {"expected_generation": True},
    {"cohort": "nonexistent"}, {"video_url": "https://private.example/video"},
])
def test_invalid_or_privacy_sensitive_schema_rejected(fields):
    with pytest.raises(ValueError):
        module.evaluate([case(**fields)])


def test_duplicate_case_ids_and_empty_corpus_rejected():
    with pytest.raises(ValueError):
        module.evaluate([])
    with pytest.raises(ValueError):
        module.evaluate([case("a"),case("a")])


def test_cli_returns_failure_for_small_sample(tmp_path, capsys):
    import json
    path = tmp_path / "manifest.jsonl"
    path.write_text(json.dumps(case()) + "\n", encoding="utf-8")
    assert module.main([str(path)]) == 1
    content = json.loads(capsys.readouterr().out)
    assert content["status"] == "FAIL"
    assert "INSUFFICIENT_CASES" in content["failures"]
