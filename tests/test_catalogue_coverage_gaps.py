"""Actionable global price coverage without fabricating GBP market values."""

import pytest

from app.catalogue_coverage import (
    COVERAGE_SQL,
    PRICED_REFERENCE_STATUSES,
    UNPRICED_REFERENCE_ACTIONS,
    coverage_summary,
)


def row(kind, game, language, status, products):
    return {"kind": kind, "system_code": game, "language": language,
            "status": status, "products": products}


def test_gap_summary_preserves_every_reference_and_reports_actionable_source_gaps():
    rows = [
        row("CARD", "ONE_PIECE_CARD_GAME", "Japanese", "SOURCE_ACCESS_REQUIRED", 4480),
        row("CARD", "DRAGON_BALL_SUPER_FUSION_WORLD", "Japanese", "SOURCE_ACCESS_REQUIRED", 3227),
        row("CARD", "NARUTO_BANDAI_LEGACY", "Unknown", "SOURCE_ACCESS_REQUIRED", 4487),
        row("CARD", "NARUTO_KAYOU", "Unknown", "SOURCE_ACCESS_REQUIRED", 2679),
        row("CARD", "POKEMON_TCG", "English", "REFERENCE_AVAILABLE", 12127),
        row("CARD", "POKEMON_TCG", "English", "MIXED_LANGUAGE_GUIDE", 4397),
        row("CARD", "POKEMON_TCG", "English", "EXACT_QUOTE_UNAVAILABLE", 7246),
        row("SEALED", "ONE_PIECE_CARD_GAME", "Unknown", "PROVIDER_MAPPING_REQUIRED", 156),
        row("SEALED", "ONE_PIECE_CARD_GAME", "Unknown", "MIXED_LANGUAGE_GUIDE", 270),
    ]
    result = coverage_summary(rows)
    cards = result["by_kind"]["CARD"]
    assert cards["total"] == 38643
    assert cards["priced"] == 16524
    assert cards["missing"] == 22119
    assert result["by_kind"]["SEALED"] == {"total": 426, "priced": 270, "missing": 156}
    assert result["by_status"]["SOURCE_ACCESS_REQUIRED"] == 14873
    assert result["missing_by_reason"][0] == {
        "status": "SOURCE_ACCESS_REQUIRED",
        "count": 14873,
        "next_action": UNPRICED_REFERENCE_ACTIONS["SOURCE_ACCESS_REQUIRED"],
        "needs_external_data_access": True,
    }
    assert result["by_game"][0]["status_counts"]
    assert result["pricing_scope"] == "GLOBAL_REFERENCE_LIBRARY"
    assert result["valuation_currency"] == "GBP"
    assert all(x["count"] > 0 and x["status"] not in PRICED_REFERENCE_STATUSES
               for x in result["missing_by_reason"])


def test_unpriced_does_not_turn_into_free_cards_and_source_mappings_remain_gated():
    assert "p.market_value_minor>0" in COVERAGE_SQL
    assert "b.market_value_minor>0" in COVERAGE_SQL
    assert "p.market_value_minor is not null" not in COVERAGE_SQL
    assert "or (r.language='Japanese'" in COVERAGE_SQL
    assert "'NARUTO_BANDAI_LEGACY','NARUTO_KAYOU'" in COVERAGE_SQL
    assert "'SOURCE_ACCESS_REQUIRED'" in COVERAGE_SQL
    assert "now()-interval '7 days'" in COVERAGE_SQL
    assert "reference_identity'=jsonb_build_object(" in COVERAGE_SQL
    assert "tcg.inventory_items" not in COVERAGE_SQL
    assert "owner_id" not in COVERAGE_SQL


def test_coverage_remains_account_independent_and_is_strict_on_negative_counts():
    rows = [row("CARD", "POKEMON_TCG", "Japanese", "REFERENCE_AVAILABLE", 5),
            row("CARD", "POKEMON_TCG", "Japanese", "US_CONTEXT_ONLY", 3)]
    assert coverage_summary(rows) == coverage_summary([dict(x) for x in rows])
    summary = coverage_summary(rows)
    assert summary["by_kind"]["CARD"] == {"total": 8, "priced": 5, "missing": 3}
    assert summary["missing_by_reason"][0]["status"] == "US_CONTEXT_ONLY"
    assert summary["missing_by_reason"][0]["needs_external_data_access"] is False
    with pytest.raises(ValueError, match="Invalid catalogue"):
        coverage_summary([row("CARD", "POKEMON_TCG", "Japanese", "REFERENCE_AVAILABLE", -1)])
