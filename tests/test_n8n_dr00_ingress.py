from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "automation" / "n8n" / "workflows" / "dr-00-signed-event-ingress.json"


def _workflow() -> dict:
    return json.loads(WORKFLOW.read_text())


def test_dr00_is_importable_but_inactive_until_routing_is_proven() -> None:
    workflow = _workflow()
    assert workflow["id"] == "DR00IngressV1"
    assert workflow["active"] is False
    assert workflow["settings"]["executionOrder"] == "v1"
    assert workflow["meta"]["dropRate"]["activationGate"]


def test_dr00_uses_private_signed_event_contract() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    webhook = nodes["Drop Rate Event Webhook"]
    assert webhook["parameters"]["httpMethod"] == "POST"
    assert webhook["parameters"]["path"] == "drop-rate/events"
    assert webhook["parameters"]["responseMode"] == "responseNode"

    verifier = nodes["Verify Signature + Envelope"]["parameters"]["jsCode"]
    assert "DROP_RATE_AUTOMATION_WEBHOOK_SECRET" in verifier
    assert "x-drop-rate-timestamp" in verifier
    assert "x-drop-rate-signature" in verifier
    assert "createHmac('sha256'" in verifier
    assert "timingSafeEqual" in verifier
    assert "Math.abs(now-ts) > 300" in verifier
    assert "event_id" in verifier
    assert "idempotency_key" in verifier
    assert "schema_version" in verifier


def test_dr00_rejects_bad_auth_and_only_acks_valid_envelopes() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert nodes["Accepted"]["parameters"]["options"]["responseCode"] == 202
    assert nodes["Rejected"]["parameters"]["options"]["responseCode"] == 401

    connections = workflow["connections"]["Signature Valid?"]["main"]
    assert connections[0][0]["node"] == "Accepted"
    assert connections[1][0]["node"] == "Rejected"


def test_dr00_contains_no_secret_value() -> None:
    text = WORKFLOW.read_text()
    assert "DROP_RATE_AUTOMATION_WEBHOOK_SECRET" in text
    assert "sha256=" in text
    assert "password" not in text.lower()
    assert "api_key" not in text.lower()
