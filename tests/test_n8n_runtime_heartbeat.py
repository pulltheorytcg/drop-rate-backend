from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.automation_control import AutomationHeartbeat


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930054500_n8n_runtime_heartbeat.sql"
)
CONTROL = ROOT / "backend" / "app" / "automation_control.py"
HEALTH = ROOT / "backend" / "app" / "automation_health.py"
MONITOR = ROOT / "backend" / "scripts" / "run_operations_monitor.py"
CHECKER = ROOT / "backend" / "scripts" / "check_n8n_runtime_heartbeat.py"


def test_heartbeat_contract_is_fixed_and_bounded() -> None:
    heartbeat = AutomationHeartbeat.model_validate(
        {
            "heartbeat_key": "n8n-runtime",
            "workflow_version": "v1",
            "execution_id": "123",
            "occurred_at": "2026-09-30T04:40:00+00:00",
        }
    )
    assert heartbeat.heartbeat_key == "n8n-runtime"

    with pytest.raises(ValidationError):
        AutomationHeartbeat.model_validate(
            {
                "heartbeat_key": "arbitrary-heartbeat",
                "workflow_version": "v1",
                "execution_id": "123",
                "occurred_at": "2026-09-30T04:40:00+00:00",
            }
        )


def test_heartbeat_database_contract_is_private_monotonic_and_dormant_by_default() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "create table if not exists tcg.automation_heartbeats" in lower
    assert "enable row level security" in lower
    assert "revoke all on table tcg.automation_heartbeats from tcg_api" in lower
    assert "security definer" in lower
    assert "p_heartbeat_key <> 'n8n-runtime'" in sql
    assert "excluded.observed_at > tcg.automation_heartbeats.observed_at" in sql
    assert "execution_id is distinct from excluded.execution_id" in sql
    assert "p_alert_enabled boolean default false" in lower
    assert "'N8N_HEARTBEAT_STALE'" in sql
    assert "'HIGH'" in sql
    assert "grant execute on function tcg.record_automation_heartbeat" in lower
    assert "grant execute on function tcg.check_n8n_runtime_heartbeat" in lower
    assert "grant select on tcg.automation_heartbeats" not in lower


def test_signed_heartbeat_endpoint_does_not_mutate_business_truth() -> None:
    source = CONTROL.read_text().lower()

    assert '@router.post("/heartbeat")' in source
    assert "automationheartbeat.model_validate_json" in source
    assert "record_automation_heartbeat" in source
    assert "_verified_control_body" in source
    assert "update tcg.inventory_items" not in source
    assert "financial_ledger_entries" not in source
    assert "settlement" not in source


def test_operations_monitor_includes_dormant_n8n_heartbeat_check() -> None:
    monitor = MONITOR.read_text()
    checker = CHECKER.read_text()

    assert 'check_n8n_runtime_heartbeat.py' in monitor
    assert '"n8n_heartbeat_code"' in monitor
    assert 'TCG_N8N_HEARTBEAT_ALERTS_ENABLED' in checker
    assert '_enabled("TCG_N8N_HEARTBEAT_ALERTS_ENABLED", False)' in checker
    assert 'TCG_N8N_HEARTBEAT_STALE_MINUTES' in checker


def test_python_health_adapter_bounds_staleness_window() -> None:
    source = HEALTH.read_text()
    assert "stale_threshold < timedelta(minutes=10)" in source
    assert "stale_threshold > timedelta(hours=24)" in source
