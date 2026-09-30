from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INGRESS = ROOT / "automation" / "n8n" / "workflows" / "dr-00-v2-signed-event-router.json"
DR01 = ROOT / "automation" / "n8n" / "workflows" / "dr-01-inventory-approved-shopify.json"
DR01_V2 = ROOT / "automation" / "n8n" / "workflows" / "dr-01-v2-inventory-approved-shopify.json"
INGRESS_V3 = ROOT / "automation" / "n8n" / "workflows" / "dr-00-v3-signed-event-router.json"
COMMANDS = ROOT / "backend" / "app" / "automation_commands.py"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_dr00_v2_is_inactive_signed_versioned_router() -> None:
    workflow = _load(INGRESS)
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR00IngressV2"
    assert workflow["active"] is False
    assert workflow["meta"]["dropRate"]["version"] == 2
    assert nodes["Drop Rate Event Webhook V2"]["parameters"]["path"] == "drop-rate/events-v2"
    assert nodes["Drop Rate Event Webhook V2"]["parameters"]["options"]["rawBody"] is True

    verifier = nodes["Verify Signature + Envelope"]["parameters"]["jsCode"]
    assert "DROP_RATE_AUTOMATION_WEBHOOK_SECRET" in verifier
    assert "timingSafeEqual" in verifier
    assert "timestamp + '.' + rawBody" in verifier

    route = nodes["Run DR-01"]["parameters"]
    assert route["workflowId"]["value"] == "DR01InventoryApprovedShopifyV1"
    assert route["options"]["waitForSubWorkflow"] is True
    assert nodes["Handled"]["parameters"]["options"]["responseCode"] == 200
    assert nodes["Unsupported Event"]["parameters"]["options"]["responseCode"] == 422
    assert nodes["Rejected"]["parameters"]["options"]["responseCode"] == 401


def test_dr01_calls_fastapi_then_dr91_and_routes_errors_to_dr90() -> None:
    workflow = _load(DR01)
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR01InventoryApprovedShopifyV1"
    assert workflow["active"] is False
    assert workflow["settings"]["errorWorkflow"] == "DR90GlobalErrorV1"

    signer = nodes["Sign Shopify Publication Command"]["parameters"]["jsCode"]
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in signer
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in signer
    assert "shopify/inventory-approved" in signer
    assert "createHmac('sha256'" in signer

    request = nodes["Publish via FastAPI"]["parameters"]
    assert request["method"] == "POST"
    assert request["options"]["timeout"] == 90000
    assert request["options"]["response"]["response"]["neverError"] is True

    receipt = nodes["Record Durable Success"]["parameters"]
    assert receipt["workflowId"]["value"] == "DR91SuccessReceiptV1"
    assert receipt["options"]["waitForSubWorkflow"] is True
    values = receipt["workflowInputs"]["value"]
    assert values["workflow_key"] == "shopify-product-creation"
    assert "idempotency_key" in values
    assert "owner_id" in values
    assert "event_id" in values

    connections = workflow["connections"]
    assert connections["Publish via FastAPI"]["main"][0][0]["node"] == "Shopify Publication Verified?"
    assert connections["Shopify Publication Verified?"]["main"][0][0]["node"] == "Record Durable Success"


def test_dr01_fastapi_command_is_signed_gated_and_uses_reusable_service() -> None:
    source = COMMANDS.read_text()

    assert '@router.post("/shopify/inventory-approved")' in source
    assert "InventoryApprovedEvent.model_validate_json" in source
    assert "if not settings.shopify_publish_enabled" in source
    assert "_verified_command_body(" in source
    assert "publish_inventory_to_shopify(" in source
    assert "automation_event_id=event.event_id" in source
    assert "actor_user_id=None" in source


def test_dr01_does_not_embed_business_rules_in_n8n() -> None:
    source = DR01.read_text().lower()

    for forbidden in (
        "update tcg.inventory_items",
        "insert into tcg.shopify_inventory_links",
        "financial_ledger_entries",
        "settlement_allocations",
        "shopify graphql",
        "productcreate",
    ):
        assert forbidden not in source


def test_dr01_v2_uses_commands_router_not_control_router() -> None:
    workflow = _load(DR01_V2)
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR01InventoryApprovedShopifyV2"
    assert workflow["active"] is False
    assert workflow["meta"]["dropRate"]["version"] == 2

    signer = nodes["Sign Shopify Publication Command"]["parameters"]["jsCode"]
    assert "automation\\/control\\/receipt" in signer
    assert "/automation/commands/shopify/inventory-approved" in signer
    assert "replace(/\\/automation\\/control\\/receipt$/" in signer
    assert "\\\\n" not in signer

    request = nodes["Publish via FastAPI"]["parameters"]
    assert request["url"] == "={{ $json.command_url }}"


def test_dr00_v3_routes_inventory_approved_to_dr01_v2() -> None:
    workflow = _load(INGRESS_V3)
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR00IngressV3"
    assert workflow["active"] is False
    assert nodes["Drop Rate Event Webhook V3"]["parameters"]["path"] == "drop-rate/events-v3"
    assert nodes["Run DR-01 V2"]["parameters"]["workflowId"]["value"] == "DR01InventoryApprovedShopifyV2"
    assert nodes["Run DR-01 V2"]["parameters"]["options"]["waitForSubWorkflow"] is True
