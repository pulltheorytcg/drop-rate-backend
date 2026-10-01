from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.competitive_intelligence_automation import (
    MAX_COMPETITIVE_SHADOW_BODY_BYTES,
    ShadowObservationBatch,
)


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend" / "app" / "competitive_intelligence_automation.py"
MAIN = ROOT / "backend" / "app" / "main.py"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20261001024000_competitive_intelligence_shadow_ingestion.sql"
)


def _batch(**overrides) -> dict:
    payload = {
        "workflow_key": "competitive-intelligence",
        "workflow_version": "v1",
        "execution_id": "shadow-run-1",
        "observations": [
            {
                "source_id": "00000000-0000-0000-0000-000000000001",
                "dedupe_key": "competitor-a:homepage:2026-10-01:v1",
                "observation_type": "MERCHANDISING",
                "subject": "Homepage merchandising changed",
                "facts": {"module": "grails"},
                "evidence": [{"kind": "normalized-fact", "value": "grails-module"}],
                "confidence": 0.9123456,
                "relevance": 0.8765432,
                "observed_at": "2026-10-01T01:30:00+00:00",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_shadow_batch_is_bounded_and_normalizes_metrics() -> None:
    payload = ShadowObservationBatch.model_validate(_batch())
    observation = payload.observations[0]

    assert payload.workflow_key == "competitive-intelligence"
    assert observation.confidence == 0.91235
    assert observation.relevance == 0.87654
    assert MAX_COMPETITIVE_SHADOW_BODY_BYTES == 128 * 1024

    with pytest.raises(ValidationError):
        ShadowObservationBatch.model_validate(
            _batch(workflow_key="some-other-workflow")
        )


def test_shadow_batch_rejects_duplicate_dedupe_keys() -> None:
    first = _batch()["observations"][0]
    with pytest.raises(ValidationError, match="duplicate observation dedupe keys"):
        ShadowObservationBatch.model_validate(
            _batch(observations=[first, dict(first)])
        )


def test_shadow_api_is_hmac_only_and_has_no_external_action() -> None:
    source = API.read_text()
    main = MAIN.read_text()

    assert "verify_signed_body" in source
    assert "automation_command_secret" in source
    assert 'alias="X-Drop-Rate-Timestamp"' in source
    assert 'alias="X-Drop-Rate-Signature"' in source
    assert '@router.post("/observations/shadow")' in source
    assert '"mode": "SHADOW"' in source
    assert '"external_action_taken": False' in source
    assert "require_user" not in source
    assert "competitive_intelligence_automation_router" in main
    assert "dependencies=[Depends(require_platform_admin_request)]" not in (
        main.split("app.include_router(competitive_intelligence_automation_router",1)[1][:120]
    )


def test_shadow_api_does_not_fetch_publish_price_or_touch_finance() -> None:
    source = API.read_text().casefold()

    assert "httpx" not in source
    assert "requests." not in source
    assert "playwright" not in source
    assert "selenium" not in source
    assert "shopify" not in source
    assert "ebay" not in source
    assert "financial_ledger" not in source
    assert "inventory_items" not in source
    assert "pricing_" not in source


def test_database_function_rechecks_source_contract_and_is_system_only() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "security definer" in lower
    assert "v_source.competitor_status <> 'APPROVED'" in sql
    assert "v_source.source_status <> 'ACTIVE'" in sql
    assert "v_source.collection_method='MANUAL_REVIEW'" in sql
    assert "v_source.terms_review_status <> 'REVIEWED'" in sql
    assert "'SYSTEM'" in sql
    assert "created_by_user_id" in sql
    assert "v_source.rights_status" in sql
    assert "grant execute on function tcg.ingest_competitive_observation_system" in lower
    assert "to tcg_api;" in lower
    assert "from anon,authenticated,service_role,tcg_auditor" in lower


def test_database_function_is_strictly_idempotent() -> None:
    sql = MIGRATION.read_text()

    assert "where dedupe_key=v_dedupe_key" in sql
    assert "v_existing.facts = p_facts" in sql
    assert "v_existing.evidence = p_evidence" in sql
    assert "v_existing.observed_at = p_observed_at" in sql
    assert "v_existing.source_published_at is not distinct from p_source_published_at" in sql
    assert "v_existing.actor_type = 'SYSTEM'" in sql
    assert "Competitive observation dedupe key collision" in sql


def test_shadow_migration_does_not_mutate_commerce_state() -> None:
    sql = MIGRATION.read_text().casefold()
    forbidden = (
        "update tcg.inventory_items",
        "update tcg.orders",
        "update tcg.order_items",
        "insert into tcg.financial_ledger_entries",
        "update tcg.pricing_",
        "update tcg.shopify_",
        "update tcg.ebay_",
    )
    for statement in forbidden:
        assert statement not in sql
