from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT
    / "automation"
    / "n8n"
    / "workflows"
    / "dr-91-success-receipt.json"
)


def _workflow() -> dict:
    return json.loads(WORKFLOW.read_text())


def test_dr91_is_typed_reusable_and_inactive() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR91SuccessReceiptV1"
    assert workflow["active"] is False
    trigger = nodes["When Executed by Another Workflow"]
    assert trigger["type"] == "n8n-nodes-base.executeWorkflowTrigger"
    fields = {
        value["name"]: value.get("type", "string")
        for value in trigger["parameters"]["workflowInputs"]["values"]
    }
    assert fields == {
        "workflow_key": "string",
        "workflow_version": "string",
        "execution_id": "string",
        "idempotency_key": "string",
        "occurred_at": "string",
        "owner_id": "string",
        "event_id": "string",
    }


def test_dr91_validates_and_signs_success_receipt() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    normalize = nodes["Normalize Success Receipt"]["parameters"]["jsCode"]
    signer = nodes["Sign Success Receipt"]["parameters"]["jsCode"]

    assert "status:'SUCCEEDED'" in normalize
    assert "idempotency_key" in normalize
    assert "invalid_workflow_key" in normalize
    assert "invalid_owner_id" in normalize
    assert "invalid_event_id" in normalize
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in signer
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in signer
    assert "createHmac('sha256'" in signer


def test_dr91_requires_durable_fastapi_acceptance() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    request = nodes["Record Success in FastAPI"]["parameters"]
    verify = nodes["Success Receipt Accepted?"]["parameters"]["jsCode"]

    assert request["method"] == "POST"
    assert request["contentType"] == "raw"
    assert request["rawContentType"] == "application/json"
    assert request["options"]["response"]["response"]["fullResponse"] is True
    assert request["options"]["response"]["response"]["neverError"] is True
    assert "body.accepted !== true" in verify
    assert "body.status !== 'SUCCEEDED'" in verify


def test_dr91_contains_no_secret_values_or_hardcoded_host() -> None:
    source = WORKFLOW.read_text()
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in source
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in source
    assert ".railway.internal" not in source
    assert "password" not in source.lower()
    assert "api_key" not in source.lower()
