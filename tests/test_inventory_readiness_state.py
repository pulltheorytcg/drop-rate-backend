from pathlib import Path

from app.api import (
    GRADED_CARD_READY_SQL,
    ISSUE_FILTERS,
    NON_CARD_READY_SQL,
    RAW_CARD_READY_SQL,
)


def test_raw_card_readiness_uses_condition_not_grade() -> None:
    assert "p.product_type = 'CARD'" in RAW_CARD_READY_SQL
    assert "i.grading_company is null" in RAW_CARD_READY_SQL
    assert "i.grade is null" in RAW_CARD_READY_SQL
    assert "i.condition is not null" in RAW_CARD_READY_SQL


def test_graded_card_readiness_does_not_require_raw_condition() -> None:
    assert "i.grading_company is not null" in GRADED_CARD_READY_SQL
    assert "i.grade is not null" in GRADED_CARD_READY_SQL
    assert "i.condition is null" in GRADED_CARD_READY_SQL


def test_non_card_readiness_uses_seal_status_only() -> None:
    assert "p.product_type <> 'CARD'" in NON_CARD_READY_SQL
    assert "i.seal_status is not null" in NON_CARD_READY_SQL
    assert "i.grading_company is null" in NON_CARD_READY_SQL
    assert "i.condition is null" in NON_CARD_READY_SQL


def test_action_required_separates_raw_condition_from_seal_status() -> None:
    assert "p.product_type = 'CARD'" in ISSUE_FILTERS["missing_condition"]
    assert "i.grading_company is null" in ISSUE_FILTERS["missing_condition"]
    assert "p.product_type <> 'CARD'" in ISSUE_FILTERS["missing_seal_status"]
    assert "i.seal_status is null" in ISSUE_FILTERS["missing_seal_status"]


def test_inventory_ui_exposes_core_readiness_per_item() -> None:
    app_js = (
        Path(__file__).parents[1] / "backend" / "app" / "static" / "app.js"
    ).read_text()
    assert "function itemCoreReadiness(item)" in app_js
    assert '"Language"' in app_js
    assert '"Location"' in app_js
    assert '"Price"' in app_js
    assert '"Identity"' in app_js
    assert "core-readiness" in app_js
