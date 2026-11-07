from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.automation_control import AutomationExecutionReceipt


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend" / "app" / "automation_control.py"
MAIN = ROOT / "backend" / "app" / "main.py"
REPAIR = ROOT / "database" / "migrations" / "20261027164716_automation_control_runtime_repair.sql"


def _receipt(**overrides) -> dict:
    row = {
        "workflow_key": "inventory-intelligence",
        "workflow_version": "v1",
        "execution_id": "12345",
        "status": "FAILED",
        "idempotency_key": "n8n-error:inventory-intelligence:12345",
        "occurred_at": "2026-09-30T03:30:00+00:00",
        "owner_id": None,
        "event_id": None,
        "error_code": "UPSTREAM_TIMEOUT",
        "error_message": "Provider timed out",
    }
    row.update(overrides)
    return row


def test_automation_receipt_contract_is_bounded_and_failure_requires_context() -> None:
    receipt = AutomationExecutionReceipt.model_validate(_receipt())
    assert receipt.status == "FAILED"
    assert receipt.workflow_key == "inventory-intelligence"

    with pytest.raises(ValidationError):
        AutomationExecutionReceipt.model_validate(
            _receipt(error_code=None, error_message=None)
        )

    with pytest.raises(ValidationError):
        AutomationExecutionReceipt.model_validate(
            _receipt(workflow_key="Not A Safe Workflow Key")
        )


def test_control_endpoint_is_signed_idempotent_and_business_state_safe() -> None:
    source = SOURCE.read_text()
    main = MAIN.read_text()
    sql = REPAIR.read_text()

    assert "TCG_AUTOMATION_COMMAND_SECRET" not in source
    assert "automation_command_secret" in source
    assert "verify_signed_body" in source
    assert "MAX_AUTOMATION_CONTROL_BODY_BYTES = 64 * 1024" in source
    assert "on conflict(owner_id,job_type,run_key) do nothing" in sql
    assert "insert into tcg.automation_runs" in sql
    assert "receipt.idempotency_key" in source
    assert "tcg_private.record_automation_execution_receipt" in source
    assert "insert into tcg.action_required_items" in sql
    assert "'AUTOMATION','N8N_WORKFLOW_FAILED','HIGH','OWNER'" in sql
    assert "owner_type='FOUNDER'" in sql
    assert "from tcg.owners" not in source
    assert "set_config(" not in source
    assert "insert into" not in source.lower()
    assert "update tcg.inventory_items" not in source.lower()
    assert "financial_ledger_entries" not in source.lower()
    assert "shopify" not in source.lower()
    assert "app.include_router(automation_control_router)" in main


def test_control_endpoint_does_not_trust_n8n_for_severity_or_action_required_code() -> None:
    fields = AutomationExecutionReceipt.model_fields
    assert "severity" not in fields
    assert "action_required_code" not in fields
    assert "category" not in fields
