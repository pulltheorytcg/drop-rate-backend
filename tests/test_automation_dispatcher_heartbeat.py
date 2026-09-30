from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930051500_automation_dispatcher_heartbeat.sql"
)
DISPATCHER = ROOT / "backend" / "scripts" / "run_automation_dispatcher.py"
CHECKER = ROOT / "backend" / "scripts" / "check_automation_dispatcher_heartbeat.py"
MONITOR = ROOT / "backend" / "scripts" / "run_operations_monitor.py"


def test_dispatcher_heartbeat_table_is_private_and_write_is_narrow() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "create table if not exists tcg.automation_component_heartbeats" in lower
    assert "enable row level security" in lower
    assert "force row level security" in lower
    assert "revoke all on tcg.automation_component_heartbeats from tcg_api" in lower
    assert "record_automation_component_heartbeat" in lower
    assert "grant execute on function tcg.record_automation_component_heartbeat" in lower
    assert "grant select on tcg.automation_component_heartbeats" not in lower


def test_dispatcher_emits_startup_and_periodic_heartbeat() -> None:
    source = DISPATCHER.read_text()

    assert "async def _record_heartbeat(" in source
    assert '"DISPATCHER"' in source
    assert "TCG_AUTOMATION_HEARTBEAT_SECONDS" in source
    assert "TCG_AUTOMATION_COMPONENT_VERSION" in source
    assert "await _record_heartbeat(" in source
    assert "next_heartbeat_at = loop.time() + heartbeat_seconds" in source
    assert "if loop.time() >= next_heartbeat_at:" in source


def test_dispatcher_heartbeat_monitor_is_dormant_until_explicitly_enabled() -> None:
    source = CHECKER.read_text()
    monitor = MONITOR.read_text()

    assert "TCG_AUTOMATION_DISPATCHER_ALERTS_ENABLED" in source
    assert '"AUTOMATION_DISPATCHER_HEARTBEAT_OBSERVED_DORMANT"' in source
    assert "if not alert_enabled:" in source
    assert "return 0" in source
    assert '"AUTOMATION_DISPATCHER_UNHEALTHY"' in source
    assert "return 2" in source

    assert 'check_automation_dispatcher_heartbeat.py' in monitor
    assert "dispatcher_code == 0" in monitor
    assert '"dispatcher_code": dispatcher_code' in monitor


def test_active_stale_dispatcher_is_critical_founder_exception() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "automation_dispatcher_unhealthy" in lower
    assert "'critical'" in lower
    assert "owner_type='founder'" in lower
    assert "p_alert_enabled" in lower
    assert "last_seen_at >= clock_timestamp()-p_threshold" in lower
    assert "threshold must be 30 seconds to 15 minutes" in lower


def test_heartbeat_does_not_touch_business_state() -> None:
    sql = MIGRATION.read_text().lower()

    for forbidden in (
        "update tcg.inventory_items",
        "update tcg.orders",
        "update tcg.shopify_inventory_links",
        "update tcg.financial_ledger_entries",
        "update tcg.settlements",
        "delete from tcg.automation_events",
    ):
        assert forbidden not in sql
