from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT
    / "automation"
    / "n8n"
    / "workflows"
    / "dr-90-global-error.json"
)


def _workflow() -> dict:
    return json.loads(WORKFLOW.read_text())


def test_dr90_is_versioned_inactive_and_error_triggered() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR90GlobalErrorV1"
    assert workflow["active"] is False
    assert workflow["meta"]["dropRate"]["contract"] == "DR-90"
    assert workflow["meta"]["dropRate"]["recursiveErrorWorkflowForbidden"] is True
    assert nodes["Workflow Error"]["type"] == "n8n-nodes-base.errorTrigger"


def test_dr90_sends_signed_failure_receipt_to_fastapi() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    normalize = nodes["Normalize Failure"]["parameters"]["jsCode"]
    signer = nodes["Sign Control Receipt"]["parameters"]["jsCode"]
    request = nodes["Record Failure in FastAPI"]["parameters"]

    assert "execution.id" in normalize
    assert "workflow.name" in normalize
    assert "status: 'FAILED'" in normalize
    assert "idempotency_key" in normalize
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in signer
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in signer
    assert "createHmac('sha256'" in signer
    assert request["method"] == "POST"
    assert request["contentType"] == "raw"
    assert request["rawContentType"] == "application/json"
    assert request["options"]["response"]["response"]["fullResponse"] is True
    assert request["options"]["response"]["response"]["neverError"] is True


def test_dr90_contains_no_secret_or_hardcoded_backend_hostname() -> None:
    source = WORKFLOW.read_text()
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in source
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in source
    assert ".railway.internal" not in source
    assert "api_key" not in source.lower()
    assert "password" not in source.lower()
