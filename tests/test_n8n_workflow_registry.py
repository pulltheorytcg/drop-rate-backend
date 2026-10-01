from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "automation" / "n8n" / "workflow-registry.json"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text())


def test_n8n_workflow_registry_covers_43_founder_workflows() -> None:
    registry = _registry()
    workflows = registry["workflows"]
    assert registry["schema_version"] == 1
    assert len(workflows) == 43
    assert [row["sequence"] for row in workflows] == list(range(1, 44))
    assert len({row["key"] for row in workflows}) == 43


def test_every_workflow_has_safety_and_activation_contract() -> None:
    registry = _registry()
    valid_authority = set(registry["authority_levels"])
    valid_states = set(registry["lifecycle_states"])
    for row in registry["workflows"]:
        assert row["authority"] in valid_authority
        assert row["status"] in valid_states
        assert row["source_of_truth"] == "PostgreSQL/Supabase"
        assert row["decision_engine"] == "FastAPI"
        assert row["orchestrator"] == "n8n"
        assert row["idempotency_required"] is True
        assert row["version_control_required"] is True
        assert row["error_workflow_required"] is True
        assert "deterministic backend contract" in row["activation_requires"]
        assert "duplicate-delivery test" in row["activation_requires"]


def test_high_impact_financial_and_stock_workflows_do_not_delegate_truth_to_ai() -> None:
    registry = _registry()
    by_key = {row["key"]: row for row in registry["workflows"]}
    for key in (
        "multi-owner-order-allocation",
        "settlement-preparation",
        "payout-monitoring",
        "cross-channel-inventory-protection",
    ):
        assert by_key[key]["authority"] in {"OBSERVE", "HIGH_IMPACT"}
        assert by_key[key]["ai_may_assist"] is False
