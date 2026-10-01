from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend" / "app" / "competitive_intelligence_automation.py"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20261001025500_competitive_intelligence_shadow_provenance.sql"
)


def test_shadow_api_sends_full_workflow_provenance() -> None:
    source = API.read_text()

    assert "payload.workflow_key" in source
    assert "payload.workflow_version" in source
    assert "payload.execution_id" in source
    assert "$1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb" in source
    assert "$11,$12,$13,$14" in source


def test_provenance_migration_is_forward_only_and_rollout_compatible() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "drop table" not in lower
    assert "delete from tcg." not in lower
    assert "automation_workflow_key" in sql
    assert "automation_workflow_version" in sql
    assert "automation_execution_id" in sql
    assert "legacy-shadow-v1" in sql

    new_signature = (
        "text,text,text,text,uuid,text,text,text,"
        "jsonb,jsonb,numeric,numeric,timestamptz,timestamptz"
    )
    old_signature = (
        "text,uuid,text,text,text,jsonb,jsonb,numeric,numeric,"
        "timestamptz,timestamptz"
    )
    assert sql.count(new_signature) >= 2
    assert (
        "create or replace function tcg.ingest_competitive_observation_system(\n"
        "    p_request_id text,\n"
        "    p_source_id uuid,"
    ) in sql
    assert (
        "revoke all on function tcg.ingest_competitive_observation_system(\n"
        f"    {old_signature}\n"
        ") from public,anon,authenticated,service_role,tcg_auditor;"
    ) in sql
    assert (
        "grant execute on function tcg.ingest_competitive_observation_system(\n"
        f"    {old_signature}\n"
        ") to tcg_api;"
    ) in sql


def test_provenance_is_required_for_system_rows_only() -> None:
    sql = MIGRATION.read_text()

    assert "actor_type='HUMAN'" in sql
    assert "automation_workflow_key is null" in sql
    assert "actor_type='SYSTEM'" in sql
    assert "automation_workflow_key is not null" in sql
    assert "automation_execution_id is not null" in sql
    assert "validate constraint competitive_observations_automation_provenance_check" in sql


def test_new_ingestion_function_preserves_source_safety_gates() -> None:
    sql = MIGRATION.read_text()

    assert "v_source.competitor_status <> 'APPROVED'" in sql
    assert "v_source.source_status <> 'ACTIVE'" in sql
    assert "v_source.collection_method='MANUAL_REVIEW'" in sql
    assert "v_source.terms_review_status <> 'REVIEWED'" in sql
    assert "Competitive observation dedupe key collision" in sql
    assert "v_existing.facts = p_facts" in sql
    assert "v_existing.evidence = p_evidence" in sql


def test_automation_audit_actor_is_explicit() -> None:
    sql = MIGRATION.read_text()

    assert "tcg.competitive_automation_actor" in sql
    assert "automation:competitive-intelligence" in sql
    assert "current_setting('tcg.competitive_automation_actor',true)" in sql


def test_provenance_hardening_cannot_mutate_commerce_or_finance() -> None:
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
