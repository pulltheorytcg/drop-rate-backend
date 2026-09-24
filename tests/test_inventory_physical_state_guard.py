from pathlib import Path

import pytest

from app.physical_state import validate_physical_state


ROOT = Path(__file__).parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "202609240005_inventory_physical_state_separation.sql"
)


def test_database_guard_keeps_condition_grading_and_seal_separate() -> None:
    sql = MIGRATION.read_text()
    assert "Graded card inventory cannot also use raw card condition" in sql
    assert "Non-card inventory cannot use raw card condition" in sql
    assert "Never mirror seal state into condition" in sql
    assert "new.condition := 'Sealed'" not in sql
    assert "new.condition := 'Unsealed'" not in sql
    assert "inventory_items_physical_state_separation_check" in sql


def test_raw_card_condition_scale_is_database_enforced() -> None:
    sql = MIGRATION.read_text()
    for condition in (
        "Near Mint",
        "Lightly Played",
        "Moderately Played",
        "Heavily Played",
        "Damaged",
    ):
        assert condition in sql


def test_raw_card_can_have_condition_without_grading() -> None:
    validate_physical_state(
        product_type="CARD",
        condition="Near Mint",
        seal_status=None,
        grading_company=None,
        grade=None,
    )


def test_graded_card_cannot_also_have_raw_condition() -> None:
    with pytest.raises(ValueError, match="must not also have a raw card condition"):
        validate_physical_state(
            product_type="CARD",
            condition="Near Mint",
            seal_status=None,
            grading_company="PSA",
            grade="10",
        )


def test_graded_card_uses_grading_without_raw_condition() -> None:
    validate_physical_state(
        product_type="CARD",
        condition=None,
        seal_status=None,
        grading_company="PSA",
        grade="10",
        certificate_number="12345678",
    )


def test_sealed_product_uses_seal_status_only() -> None:
    validate_physical_state(
        product_type="SEALED",
        condition=None,
        seal_status="SEALED",
        grading_company=None,
        grade=None,
    )

    with pytest.raises(ValueError, match="do not use raw card condition"):
        validate_physical_state(
            product_type="SEALED",
            condition="Sealed",
            seal_status="SEALED",
            grading_company=None,
            grade=None,
        )
