from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930050000_automation_runs_n8n_contract.sql"
)
CONTROL = ROOT / "backend" / "app" / "automation_control.py"


def test_automation_runs_keeps_legacy_values_and_adds_bounded_n8n_values() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "job_type='INVENTORY_REVIEW'" in sql
    assert "^N8N:[a-z0-9][a-z0-9-]{1,119}$" in sql
    assert "char_length(job_type) between 6 and 124" in lower
    assert "initiated_by in ('AUTOMATION_SERVICE','N8N')" in sql
    assert "length(run_key) between 1 and 255" in lower


def test_receipt_contract_fits_automation_runs_constraints() -> None:
    source = CONTROL.read_text()

    assert 'f"N8N:{receipt.workflow_key}"' in source
    assert "'N8N'" in source
    assert "receipt.execution_id" in source or "receipt.idempotency_key" in source
    assert "workflow_key: str = Field(pattern=" in source
    assert "max_length=255" in source


def test_migration_does_not_weaken_unique_or_owner_constraints() -> None:
    sql = MIGRATION.read_text().lower()

    assert "drop constraint if exists automation_runs_owner_id_job_type_run_key_key" not in sql
    assert "drop constraint if exists automation_runs_owner_id_fkey" not in sql
    assert "alter column" not in sql
    assert "drop table" not in sql
