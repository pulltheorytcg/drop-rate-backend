from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "automation" / "n8n" / "workflows" / "dr-92-workflow-heartbeat.json"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930051000_n8n_workflow_heartbeat.sql"
)
WRAPPER = ROOT / "backend" / "app" / "automation_heartbeat.py"
SCRIPT = ROOT / "backend" / "scripts" / "check_n8n_workflow_heartbeat.py"
MONITOR = ROOT / "backend" / "scripts" / "run_operations_monitor.py"


def _workflow() -> dict:
    return json.loads(WORKFLOW.read_text())


def test_dr92_is_inactive_scheduled_and_uses_dr91() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR92WorkflowHeartbeatV1"
    assert workflow["active"] is False
    assert workflow["settings"]["errorWorkflow"] == "DR90GlobalErrorV1"

    schedule = nodes["Every 5 Minutes"]
    assert schedule["type"] == "n8n-nodes-base.scheduleTrigger"
    assert schedule["parameters"]["rule"]["interval"] == [
        {"field": "minutes", "minutesInterval": 5}
    ]

    receipt = nodes["Record Durable Heartbeat"]
    assert receipt["type"] == "n8n-nodes-base.executeWorkflow"
    assert receipt["parameters"]["workflowId"]["value"] == "DR91SuccessReceiptV1"
    assert receipt["parameters"]["workflowId"]["mode"] == "id"
    assert receipt["parameters"]["options"]["waitForSubWorkflow"] is True

    values = receipt["parameters"]["workflowInputs"]["value"]
    assert set(values) == {
        "workflow_key",
        "workflow_version",
        "execution_id",
        "idempotency_key",
        "occurred_at",
        "owner_id",
        "event_id",
    }


def test_dr92_heartbeat_is_bucket_idempotent_and_verified() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    prepare = nodes["Prepare Heartbeat Receipt"]["parameters"]["jsCode"]
    verify = nodes["Heartbeat Receipt Recorded?"]["parameters"]["jsCode"]

    assert "5 * 60 * 1000" in prepare
    assert "n8n-heartbeat:" in prepare
    assert "workflow-heartbeat" in prepare
    assert "$execution.id" in prepare
    assert "heartbeat_receipt_not_recorded" in verify


def test_backend_heartbeat_is_guarded_dormant_and_deduped() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "check_n8n_workflow_heartbeat" in lower
    assert "p_alert_enabled boolean default false" in lower
    assert "N8N:workflow-heartbeat" in sql
    assert "N8N_HEARTBEAT_STALE" in sql
    assert "system:n8n-workflow-heartbeat" in sql
    assert "on conflict(owner_id,dedupe_key)" in lower
    assert "status='RESOLVED'" in sql
    assert "security definer" in lower
    assert "grant execute on function tcg.check_n8n_workflow_heartbeat" in lower
    assert "grant select on tcg.automation_runs" not in lower

    for forbidden in (
        "update tcg.inventory_items",
        "update tcg.shopify_inventory_links",
        "financial_ledger_entries",
        "settlement_allocations",
    ):
        assert forbidden not in lower


def test_operations_monitor_runs_heartbeat_checker_and_defaults_alerts_off() -> None:
    wrapper = WRAPPER.read_text()
    script = SCRIPT.read_text()
    monitor = MONITOR.read_text()

    assert "tcg.check_n8n_workflow_heartbeat($1,$2::interval)" in wrapper
    assert 'TCG_N8N_HEARTBEAT_ALERTS_ENABLED", False' in script
    assert 'TCG_N8N_HEARTBEAT_THRESHOLD_MINUTES", "15"' in script
    assert "check_n8n_workflow_heartbeat.py" in monitor
    assert "n8n_heartbeat_code" in monitor
