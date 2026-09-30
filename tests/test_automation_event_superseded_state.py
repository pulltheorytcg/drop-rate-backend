from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930035500_automation_event_superseded_state.sql"
)


def test_superseded_state_is_terminal_and_audited() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "'superseded'::text" in lower
    assert "superseded_at timestamptz" in lower
    assert "superseded_reason text" in lower
    assert "automation_events_terminal_check" in lower
    assert "status='superseded'" in lower
    assert "automation_event_superseded" in lower
    assert "insert into tcg.audit_events" in lower


def test_backlog_supersede_is_narrow_and_fail_closed() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "supersede_published_inventory_approved_events" in lower
    assert "ae.status='pending'" in lower
    assert "ae.event_type='inventory.approved'" in lower
    assert "ae.aggregate_type='inventory_item'" in lower
    assert "sil.sync_state='published'" in lower
    assert "for update of ae skip locked" in lower
    assert "limit p_limit" in lower

    # The cleanup may retire orchestration history only. It must not mutate
    # inventory, Shopify links, orders, pricing or finance.
    assert "update tcg.inventory_items" not in lower
    assert "update tcg.shopify_inventory_links" not in lower
    assert "update tcg.orders" not in lower
    assert "financial_ledger_entries" not in lower


def test_backlog_supersede_is_not_exposed_to_user_roles() -> None:
    lower = MIGRATION.read_text().lower()
    assert (
        "revoke all on function tcg.supersede_published_inventory_approved_events"
        in lower
    )
    assert "from anon, authenticated, service_role, tcg_auditor" in lower
    assert (
        "grant execute on function tcg.supersede_published_inventory_approved_events"
        "(text,text,integer) to tcg_api"
    ) in lower
