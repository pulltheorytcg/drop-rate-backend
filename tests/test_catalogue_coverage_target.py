"""Source-aware global pricing KPI: never pass 89% by counting digital or US asks."""
from app.catalogue_coverage import coverage_summary


def sample(status, count, *, kind="CARD", game="POKEMON_TCG", language="English"):
    return {"kind": kind, "system_code": game, "language": language,
            "status": status, "products": count, "oldest_check": None,
            "incomplete_references": 0}


def test_historical_baseline_keeps_actual_counts_under_current_target():
    rows = [
        sample("REFERENCE_AVAILABLE", 21581),
        sample("MIXED_LANGUAGE_GUIDE", 18862),
        sample("PROVIDER_MAPPING_REQUIRED", 9358),
        sample("SOURCE_ACCESS_REQUIRED", 13064),
        sample("EXACT_QUOTE_UNAVAILABLE", 4167),
        sample("US_CONTEXT_ONLY", 28),
        sample("NOT_APPLICABLE_DIGITAL", 2480),
    ]
    report = coverage_summary(rows)
    assert report["physical_cards"] == {
        "total": 67060, "priced": 40443, "missing": 26617,
    }
    assert report["non_physical_cards"] == 2480
    goal = report["coverage_target"]
    assert (goal["eligible"], goal["priced"], goal["minimum_priced"]) == (67060, 40443, 59684)
    assert (goal["coverage_percent"], goal["additional_needed"], goal["target_met"]) == (60.31, 19241, False)
    assert goal["target_percent"] == 89
    assert goal["by_game_language"][0]["eligible"] == 67060
    assert goal["by_game_language"][0]["missing"] == 26617
    assert report["missing_by_reason"][0]["count"] == 13064


def test_exact_threshold_never_uses_rounded_percent_to_pass():
    for priced, passed in [(88, False), (89, True), (90, True)]:
        report = coverage_summary([sample("REFERENCE_AVAILABLE", priced),
                                   sample("EXACT_QUOTE_UNAVAILABLE", 100 - priced),
                                   sample("NOT_APPLICABLE_DIGITAL", 20)])
        goal = report["coverage_target"]
        assert goal["eligible"] == 100
        assert goal["minimum_priced"] == 89
        assert goal["additional_needed"] == max(0, 89 - priced)
        assert goal["target_met"] is passed


def test_scope_excludes_digital_and_source_context_and_handles_empty():
    report = coverage_summary([
        sample("MIXED_LANGUAGE_GUIDE", 19, game="ONE_PIECE_CARD_GAME"),
        sample("US_CONTEXT_ONLY", 1, game="ONE_PIECE_CARD_GAME"),
        sample("NOT_APPLICABLE_DIGITAL", 100),
        sample("REFERENCE_AVAILABLE", 1, kind="SEALED"),
    ])
    goal = report["coverage_target"]
    assert (goal["eligible"], goal["priced"], goal["coverage_percent"]) == (20, 19, 95.0)
    assert goal["target_met"] is True
    assert report["non_physical_cards"] == 100
    assert report["by_kind"]["SEALED"]["priced"] == 1
    assert len(goal["by_game_language"]) == 1
    assert goal["by_game_language"][0]["system_code"] == "ONE_PIECE_CARD_GAME"
    empty = coverage_summary([sample("REFERENCE_AVAILABLE", 5, kind="SEALED")])
    assert empty["coverage_target"]["coverage_percent"] == 0.0
    assert empty["coverage_target"]["target_met"] is False
    assert empty["coverage_target"]["additional_needed"] == 0


def test_language_cohorts_remain_separate():
    summary = coverage_summary([
        sample("REFERENCE_AVAILABLE", 20, game="ONE_PIECE_CARD_GAME", language="English"),
        sample("SOURCE_ACCESS_REQUIRED", 80, game="ONE_PIECE_CARD_GAME", language="English"),
        sample("MIXED_LANGUAGE_GUIDE", 95, game="ONE_PIECE_CARD_GAME", language="Japanese"),
        sample("EXACT_QUOTE_UNAVAILABLE", 5, game="ONE_PIECE_CARD_GAME", language="Japanese"),
    ])
    by_language = {r["language"]: r for r in summary["coverage_target"]["by_game_language"]}
    assert by_language["English"]["target_met"] is False
    assert by_language["Japanese"]["target_met"] is True
    assert by_language["English"]["additional_needed"] == 69
    assert by_language["Japanese"]["additional_needed"] == 0


def test_current_catalogue_needs_exact_count_even_when_percentage_rounds_to_89():
    for priced, passed in [(43208, False), (59687, False), (59688, True)]:
        report = coverage_summary([
            sample("REFERENCE_AVAILABLE", priced),
            sample("EXACT_QUOTE_UNAVAILABLE", 67065 - priced),
            sample("NOT_APPLICABLE_DIGITAL", 2480),
        ])
        goal = report["coverage_target"]
        assert goal["eligible"] == 67065
        assert goal["minimum_priced"] == 59688
        assert goal["additional_needed"] == max(0, 59688 - priced)
        assert goal["target_met"] is passed
        if priced == 59687:
            assert goal["coverage_percent"] == 89.0
