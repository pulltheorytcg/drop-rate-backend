from __future__ import annotations

from pathlib import Path

from scripts.bootstrap_cardtrader_sealed_market import _eligible_marketplace_rows


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "backend" / "scripts" / "bootstrap_cardtrader_sealed_market.py"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20261001192500_add_cardtrader_market_source.sql"
)


def test_bootstrap_accepts_only_available_single_unit_listings() -> None:
    rows = _eligible_marketplace_rows(
        [
            {
                "id": 1,
                "quantity": 1,
                "bundle_size": 1,
                "price": {"cents": 500, "currency": "EUR"},
                "user": {"on_vacation": False},
            },
            {
                "id": 2,
                "quantity": 1,
                "bundle_size": 24,
                "price": {"cents": 8000, "currency": "EUR"},
            },
            {
                "id": 3,
                "quantity": 0,
                "bundle_size": 1,
                "price": {"cents": 450, "currency": "EUR"},
            },
            {
                "id": 4,
                "quantity": 1,
                "bundle_size": 1,
                "price": {"cents": 450, "currency": "EUR"},
                "on_vacation": True,
            },
        ]
    )

    assert [row["id"] for row in rows] == [1]


def test_bootstrap_is_fail_closed_and_reprices_only_confirmed_inventory() -> None:
    source = SCRIPT.read_text()

    assert "if len(viable) != 1:" in source
    assert "requires exactly one JP single-pack blueprint" in source
    assert "match_status,match_confidence,metadata" in source
    assert "'VERIFIED',1.0000" in source
    assert '"verification_basis": "DETERMINISTIC_EXACT_SEALED_BOOTSTRAP"' in source
    assert "bundle_size != 1" in source
    assert "identity_confirmed=true" in source
    assert "_recalculate_one(" in source


def test_cardtrader_market_source_migration_updates_all_three_source_constraints() -> None:
    sql = MIGRATION.read_text()

    assert "market_observations_source_check" in sql
    assert "market_source_mappings_source_check" in sql
    assert "market_ingestion_runs_source_check" in sql
    assert "'CARDTRADER'" in sql
    assert "'MANUAL'" in sql
