from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "automation" / "n8n" / "workflow-registry.json"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text())


def test_n8n_workflow_registry_covers_46_founder_workflows() -> None:
    registry = _registry()
    workflows = registry["workflows"]
    assert registry["schema_version"] == 1
    assert len(workflows) == 46
    assert [row["sequence"] for row in workflows] == list(range(1, 47))
    assert len({row["key"] for row in workflows}) == 46


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


def test_automated_artwork_sync_is_backend_gated_and_not_claimed_active() -> None:
    from pathlib import Path
    registry = _registry()
    row, = [w for w in registry["workflows"] if w["key"] == "automated-card-artwork-refresh"]
    assert row["status"] == "BUILT_INACTIVE"
    assert row["authority"] == "ORCHESTRATE"
    assert row["ai_may_assist"] is False
    assert row["implementation_id"] == "DR95EligibleArtworkSyncV1"
    assert (ROOT / row["implementation_path"]).is_file()
    assert "R2-first" in row["activation_note"]


def test_per_game_release_scouts_are_metadata_only_and_source_scoped() -> None:
    row, = [entry for entry in _registry()["workflows"]
            if entry["key"] == "per-game-new-release-discovery"]
    assert row["authority"] == "ORCHESTRATE"
    assert row["status"] == "BUILT_INACTIVE"
    assert row["decision_engine"] == "FastAPI"
    assert row["ai_may_assist"] is False
    assert len(row["implementation_paths"]) == 6
    assert all((ROOT / p).exists() for p in row["implementation_paths"])
    assert row["control_contract"] == "/api/v1/automation/commands/catalogue/refresh-release-source"


def test_original_game_release_watches_stay_backend_gated_and_riot_permitted_only() -> None:
    row, = [w for w in _registry()["workflows"]
            if w["key"] == "legacy-game-release-monitors"]
    assert row["status"] == "BUILT_INACTIVE"
    assert row["authority"] == "ORCHESTRATE"
    assert row["decision_engine"] == "FastAPI"
    assert row["ai_may_assist"] is False
    assert len(row["implementation_paths"]) == 5
    assert all((ROOT / p).is_file() for p in row["implementation_paths"])
    assert "Riot" in row["activation_note"] and "capacity" in row["activation_note"]
