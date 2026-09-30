from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930040500_repair_automation_supersede_audit.sql"
)


def test_supersede_function_audits_each_updated_event() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "for v_event in" in lower
    assert "for update of ae skip locked" in lower
    assert "update tcg.automation_events" in lower
    assert "and status='pending'" in lower
    assert "if found then" in lower
    assert "insert into tcg.audit_events" in lower
    assert "'automation_event_superseded'" in lower
    assert "v_count := v_count + 1" in lower


def test_audit_repair_is_idempotent_and_narrow() -> None:
    lower = MIGRATION.read_text().lower()

    assert "'phase2-n8n-backlog-reconciliation-audit-repair'" in lower
    assert "where ae.status='superseded'" in lower
    assert "ae.event_type='inventory.approved'" in lower
    assert "not exists" in lower
    assert "au.entity_id=ae.id" in lower
    assert "'audit_repair',true" in lower

    assert "update tcg.inventory_items" not in lower
    assert "update tcg.shopify_inventory_links" not in lower
    assert "financial_ledger_entries" not in lower
