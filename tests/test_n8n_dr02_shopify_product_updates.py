from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "automation" / "n8n" / "workflows" / "dr-02-shopify-product-updates.json"


def _workflow() -> dict:
    return json.loads(WORKFLOW.read_text())


def test_dr02_is_inactive_bounded_schedule_with_global_error_route() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["id"] == "DR02ShopifyProductUpdatesV1"
    assert workflow["active"] is False
    assert workflow["settings"]["errorWorkflow"] == "DR90GlobalErrorV1"
    assert nodes["Every 15 Minutes"]["parameters"]["rule"]["interval"] == [
        {"field": "minutes", "minutesInterval": 15}
    ]

    prepare = nodes["Prepare Product Update Command"]["parameters"]["jsCode"]
    assert "15 * 60 * 1000" in prepare
    assert "shopify-product-updates:v1:" in prepare
    assert "limit: 50" in prepare


def test_dr02_calls_signed_fastapi_command_then_durable_success_receipt() -> None:
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    signer = nodes["Sign Product Update Command"]["parameters"]["jsCode"]
    assert "DROP_RATE_AUTOMATION_COMMAND_SECRET" in signer
    assert "DROP_RATE_API_AUTOMATION_CONTROL_URL" in signer
    assert "/automation/commands/shopify/product-updates" in signer
    assert "\\n" not in signer

    request = nodes["Reconcile via FastAPI"]["parameters"]
    assert request["method"] == "POST"
    assert request["options"]["timeout"] == 90000
    assert request["options"]["response"]["response"]["neverError"] is True

    receipt = nodes["Record Durable Success"]["parameters"]
    assert receipt["workflowId"]["value"] == "DR91SuccessReceiptV1"
    assert receipt["workflowInputs"]["value"]["workflow_key"] == "shopify-product-updates"
    assert receipt["options"]["waitForSubWorkflow"] is True


def test_dr02_n8n_contains_no_canonical_price_or_database_business_rules() -> None:
    source = WORKFLOW.read_text().lower()
    for forbidden in (
        "update tcg.inventory_items",
        "update tcg.shopify_inventory_links",
        "insert into tcg",
        "store_price_minor =",
        "financial_ledger_entries",
        "settlement_allocations",
        "productvariantsbulkupdate",
    ):
        assert forbidden not in source
