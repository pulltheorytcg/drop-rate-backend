from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT
    / "automation"
    / "n8n"
    / "workflows"
    / "dr-92-runtime-heartbeat.json"
)


def _workflow() -> dict:
    return json.loads(WORKFLOW.read_text())


def test_dr92_is_inactive_and_scheduled_every_five_minutes() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR92RuntimeHeartbeatV1"
    assert workflow["active"] is False
    schedule = nodes["Every 5 Minutes"]
    assert schedule["type"] == "n8n-nodes-base.scheduleTrigger"
    interval = schedule["parameters"]["rule"]["interval"][0]
    assert interval["field"] == "minutes"
    assert interval["minutesInterval"] == 5


def test_dr92_signs_fixed_runtime_heartbeat_and_requires_acceptance() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    signer = nodes["Build and Sign Heartbeat"]["parameters"]["jsCode"]
    request = nodes["Record Heartbeat in FastAPI"]["parameters"]
    verify = nodes["Heartbeat Accepted?"]["parameters"]["jsCode"]

    assert "heartbeat_key:'n8n-runtime'" in signer
    assert "$execution.id" in signer
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in signer
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in signer
    assert "createHmac('sha256'" in signer
    assert "replace(/\\/receipt$/, '/heartbeat')" in signer
    assert request["method"] == "POST"
    assert request["options"]["response"]["response"]["fullResponse"] is True
    assert request["options"]["response"]["response"]["neverError"] is True
    assert "body.accepted !== true" in verify
    assert "body.heartbeat_key !== 'n8n-runtime'" in verify


def test_dr92_contains_no_secret_values_or_public_host() -> None:
    source = WORKFLOW.read_text()
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in source
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in source
    assert ".up.railway.app" not in source
    assert "password" not in source.lower()
    assert "api_key" not in source.lower()
