from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "database" / "migrations" / "202609230016_harden_inventory_physical_state.sql"


def test_physical_state_guard_covers_all_relevant_fields() -> None:
    sql = MIGRATION.read_text()
    assert "Card inventory cannot use seal_status" in sql
    assert "Non-card inventory cannot use grading fields" in sql
    assert "new.condition := 'Sealed'" in sql
    assert "new.condition := 'Unsealed'" in sql
    assert "new.condition := null" in sql
    assert "grading_company" in sql
    assert "certificate_number" in sql


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
