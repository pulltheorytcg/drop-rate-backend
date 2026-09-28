from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT
    / "automation"
    / "n8n"
    / "workflows"
    / "dr-01-inventory-approved-shopify.json"
)
START = ROOT / "automation" / "n8n" / "start.sh"


def _workflow() -> dict:
    return json.loads(WORKFLOW.read_text())


def test_dr01_is_a_new_inactive_versioned_ingress() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR01InventoryApprovedV1"
    assert workflow["active"] is False
    assert workflow["meta"]["dropRate"]["contract"] == "DR-01"
    assert nodes["Drop Rate Event Webhook V2"]["parameters"]["path"] == "drop-rate/events-v2"
    assert nodes["Drop Rate Event Webhook V2"]["parameters"]["options"]["rawBody"] is True


def test_dr01_verifies_ingress_before_event_routing() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    verifier = nodes["Verify Signature + Envelope"]["parameters"]["jsCode"]

    assert "DROP_RATE_AUTOMATION_WEBHOOK_SECRET" in verifier
    assert "timingSafeEqual" in verifier
    assert "timestamp + '.' + rawBody" in verifier
    assert "item.binary?.data?.data" in verifier
    assert "owner_id" in verifier

    signature_edges = workflow["connections"]["Signature Valid?"]["main"]
    assert signature_edges[0][0]["node"] == "Inventory Approved?"
    assert signature_edges[1][0]["node"] == "Rejected"
    assert nodes["Rejected"]["parameters"]["options"]["responseCode"] == 401


def test_dr01_uses_separate_signed_fastapi_command_secret() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    signer = nodes["Sign FastAPI Command"]["parameters"]["jsCode"]
    request = nodes["Publish Inventory via FastAPI"]["parameters"]

    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in signer
    assert "DROP_RATE_API_AUTOMATION_URL" in signer
    assert "createHmac('sha256'" in signer
    assert "JSON.stringify(event)" in signer
    assert "command_signature" in signer

    assert request["method"] == "POST"
    assert request["contentType"] == "raw"
    assert request["rawContentType"] == "application/json"
    assert request["body"] == "={{ $json.command_body }}"
    assert request["options"]["timeout"] == 90000
    assert request["options"]["response"]["response"]["fullResponse"] is True
    assert request["options"]["response"]["response"]["neverError"] is True

    headers = {
        row["name"]: row["value"]
        for row in request["headerParameters"]["parameters"]
    }
    assert headers["X-Drop-Rate-Timestamp"] == "={{ $json.command_timestamp }}"
    assert headers["X-Drop-Rate-Signature"] == "={{ $json.command_signature }}"


def test_dr01_only_acks_after_fastapi_success() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    connections = workflow["connections"]

    assert connections["Sign FastAPI Command"]["main"][0][0]["node"] == "Publish Inventory via FastAPI"
    assert connections["Publish Inventory via FastAPI"]["main"][0][0]["node"] == "Normalize FastAPI Result"
    assert connections["Normalize FastAPI Result"]["main"][0][0]["node"] == "FastAPI Succeeded?"

    result_edges = connections["FastAPI Succeeded?"]["main"]
    assert result_edges[0][0]["node"] == "Publication Accepted"
    assert result_edges[1][0]["node"] == "Publication Failed"
    assert nodes["Publication Accepted"]["parameters"]["options"]["responseCode"] == 200
    assert nodes["Unsupported Event"]["parameters"]["options"]["responseCode"] == 422

    failure_code = nodes["Publication Failed"]["parameters"]["options"]["responseCode"]
    assert "$json.status_code" in failure_code


def test_dr01_runtime_fails_closed_without_command_configuration() -> None:
    source = START.read_text()
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in source
    assert "DROP_RATE_API_AUTOMATION_URL" in source
    assert '"${#command_secret}" -lt 32' in source
    assert "railway.internal" in source


def test_dr01_commits_no_secret_or_fixed_internal_hostname() -> None:
    source = WORKFLOW.read_text()
    assert "DROP_RATE_AUTOMATION_WEBHOOK_SECRET" in source
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in source
    assert "DROP_RATE_API_AUTOMATION_URL" in source
    assert ".railway.internal:" not in source
