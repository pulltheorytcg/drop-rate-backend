from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT
    / "automation"
    / "n8n"
    / "workflows"
    / "dr-43-competitive-intelligence-shadow-ingest.json"
)
REGISTRY = ROOT / "automation" / "n8n" / "workflow-registry.json"


def _workflow() -> dict:
    return json.loads(WORKFLOW.read_text())


def test_dr43_is_versioned_inactive_observe_only_and_error_routed() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR43CompetitiveIntelligenceShadowV1"
    assert workflow["active"] is False
    assert workflow["settings"]["errorWorkflow"] == "DR90GlobalErrorV1"
    assert workflow["meta"]["dropRate"]["contract"] == "DR-43"
    assert workflow["meta"]["dropRate"]["authority"] == "OBSERVE"
    assert "no external collection" in workflow["meta"]["dropRate"]["activationGate"].lower()
    assert nodes["When Executed by Another Workflow"]["type"] == "n8n-nodes-base.executeWorkflowTrigger"


def test_dr43_validates_and_normalizes_before_http() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    normalize = nodes["Normalize Shadow Observations"]["parameters"]["jsCode"]

    assert "input.length < 1 || input.length > 50" in normalize
    assert "invalid_competitive_source_id_" in normalize
    assert "allowedTypes" in normalize
    assert "unexpected_competitive_observation_field_" in normalize
    assert "duplicate_competitive_dedupe_key_" in normalize
    assert "invalid_competitive_confidence_" in normalize
    assert "invalid_competitive_relevance_" in normalize
    assert "invalid_competitive_observed_at_" in normalize
    assert "competitive_source_published_after_observed_" in normalize
    assert "workflow_key: 'competitive-intelligence'" in normalize
    assert "workflow_version: 'v1'" in normalize


def test_dr43_uses_existing_hmac_secret_and_derives_only_shadow_endpoint() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    signer = nodes["Sign Shadow Observation Batch"]["parameters"]["jsCode"]
    request = nodes["Submit Shadow Observations"]["parameters"]

    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in signer
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in signer
    assert "createHmac('sha256'" in signer
    assert "createHash('sha256')" in signer
    assert "/api/v1/automation/competitive-intelligence/observations/shadow" in signer
    assert request["method"] == "POST"
    assert request["contentType"] == "raw"
    assert request["rawContentType"] == "application/json"
    headers = request["headerParameters"]["parameters"]
    assert {row["name"] for row in headers} == {
        "X-Drop-Rate-Timestamp",
        "X-Drop-Rate-Signature",
    }


def test_dr43_requires_shadow_no_action_response_and_durable_success_receipt() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    verify = nodes["Shadow Ingestion Verified?"]["parameters"]["jsCode"]
    receipt = nodes["Record Durable Success"]["parameters"]

    assert "body.accepted !== true" in verify
    assert "body.mode || '') !== 'SHADOW'" in verify
    assert "body.external_action_taken !== false" in verify
    assert "competitive_shadow_count_mismatch" in verify
    assert "competitive_shadow_dedupe_key_mismatch" in verify
    assert receipt["workflowId"]["value"] == "DR91SuccessReceiptV1"
    assert receipt["workflowInputs"]["value"]["workflow_key"] == "competitive-intelligence"
    assert "receipt_key" in receipt["workflowInputs"]["value"]["idempotency_key"]


def test_dr43_contains_no_external_provider_or_hardcoded_host() -> None:
    source = WORKFLOW.read_text().casefold()

    assert ".railway.internal" not in source
    assert "https://www." not in source
    assert "shopify" not in source
    assert "ebay" not in source
    assert "cardmarket" not in source
    assert "tcgplayer" not in source
    assert "whatnot" not in source
    assert "instagram" not in source
    assert "tiktok" not in source
    assert "reddit" not in source


def test_registry_marks_dr43_built_inactive_with_exact_implementation() -> None:
    registry = json.loads(REGISTRY.read_text())
    row = next(
        item for item in registry["workflows"]
        if item["key"] == "competitive-intelligence"
    )

    assert row["sequence"] == 43
    assert row["authority"] == "OBSERVE"
    assert row["status"] == "BUILT_INACTIVE"
    assert row["implementation_id"] == "DR43CompetitiveIntelligenceShadowV1"
    assert row["implementation_path"] == (
        "automation/n8n/workflows/dr-43-competitive-intelligence-shadow-ingest.json"
    )
    assert row["control_contract"] == (
        "/api/v1/automation/competitive-intelligence/observations/shadow"
    )
    assert "founder-approved competitor watchlist" in row["activation_requires"]
    assert "source-specific terms/rights review" in row["activation_requires"]
