from __future__ import annotations

from pathlib import Path

from app.competitive_intelligence_api import (
    OpportunityEvidenceInput,
    SourceCreate,
    SourceReviewUpdate,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20261001023000_competitive_intelligence_v1.sql"
)
API = ROOT / "backend" / "app" / "competitive_intelligence_api.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_schema_is_backend_only_and_forces_rls() -> None:
    sql = MIGRATION.read_text().lower()

    for table in (
        "competitors",
        "competitor_sources",
        "competitive_observations",
        "competitive_opportunities",
        "competitive_opportunity_evidence",
    ):
        assert f"alter table tcg.{table} enable row level security" in sql
        assert f"alter table tcg.{table} force row level security" in sql

    assert "from public,anon,authenticated,service_role" in sql
    assert "tcg.is_platform_admin()" in sql


def test_observations_and_evidence_are_immutable() -> None:
    sql = MIGRATION.read_text().lower()

    assert "competitive_observations_immutable" in sql
    assert "competitive_opportunity_evidence_immutable" in sql
    assert "competitive intelligence evidence is immutable" in sql
    assert "revoke update on tcg.competitive_observations" in sql
    assert "tcg.competitive_opportunity_evidence" in sql
    assert "revoke delete on tcg.competitors" in sql


def test_active_sources_require_reviewed_or_not_required_terms_state() -> None:
    sql = MIGRATION.read_text()

    assert "status <> 'ACTIVE'" in sql
    assert "terms_review_status in ('REVIEWED','NOT_REQUIRED')" in sql
    assert "collection_method <> 'MANUAL_REVIEW'" in sql


def test_competitive_tables_are_audited() -> None:
    sql = MIGRATION.read_text().lower()

    assert "audit_competitive_intelligence_change" in sql
    assert "insert into tcg.audit_events" in sql
    assert "competitors_audit" in sql
    assert "competitor_sources_audit" in sql
    assert "competitive_observations_audit" in sql
    assert "competitive_opportunities_audit" in sql


def test_active_source_payload_fails_closed_without_terms_review() -> None:
    try:
        SourceCreate(
            source_key="competitor-a:website",
            source_type="WEBSITE",
            collection_method="PUBLIC_PAGE",
            source_url="https://example.com",
            rights_status="REFERENCE_ONLY",
            terms_reviewed=False,
            status="ACTIVE",
        )
    except ValueError as exc:
        assert "provider_terms_review_required" in str(exc)
    else:
        raise AssertionError("ACTIVE unreviewed public source should fail")


def test_manual_review_source_can_be_active_without_terms_review() -> None:
    payload = SourceCreate(
        source_key="competitor-a:manual",
        source_type="OTHER",
        collection_method="MANUAL_REVIEW",
        rights_status="REFERENCE_ONLY",
        status="ACTIVE",
    )
    assert payload.status == "ACTIVE"


def test_competitor_evidence_cannot_supply_its_own_source_key() -> None:
    try:
        OpportunityEvidenceInput(
            origin="COMPETITOR",
            source_key="fake-independent-source",
            competitor_observation_id="00000000-0000-0000-0000-000000000001",
        )
    except ValueError as exc:
        assert "derived from stored observation" in str(exc)
    else:
        raise AssertionError("Competitor evidence source key must come from stored observation")


def test_non_competitor_evidence_requires_measured_scores() -> None:
    try:
        OpportunityEvidenceInput(
            origin="MARKET",
            source_key="market:one-piece:manga:2026-w40",
        )
    except ValueError as exc:
        assert "confidence and relevance" in str(exc)
    else:
        raise AssertionError("External corroboration must carry scores")


def test_api_is_admin_scoped_and_has_no_external_fetch_adapter() -> None:
    api = API.read_text()
    main = MAIN.read_text()

    assert 'prefix="/api/v1/competitive-intelligence"' in api
    assert "competitive_intelligence_router" in main
    assert "dependencies=[Depends(require_platform_admin_request)]" in main
    assert "requests." not in api
    assert "httpx." not in api
    assert "shopify" not in api.casefold()
    assert "ebay" not in api.casefold()


def test_source_review_contract_supports_founder_approval_and_activation() -> None:
    review = SourceReviewUpdate(
        expected_version=1,
        decision="APPROVE",
        notes="Public-page automation reviewed against provider terms.",
        activate=True,
    )
    assert review.activate is True
    assert review.decision == "APPROVE"

    source = API.read_text()
    assert '@router.post("/sources/{source_id}/review")' in source
    assert "terms_reviewed_by_user_id" in source
    assert '"ACTIVE" if payload.activate else "PAUSED"' in source


def test_competitor_status_has_version_checked_pause_reject_path() -> None:
    source = API.read_text()
    assert '@router.patch("/competitors/{competitor_id}/status")' in source
    assert 'where id=$1 and version=$3' in source


def test_opportunity_persistence_dedupes_evidence_by_source_key() -> None:
    source = API.read_text()
    assert "best_evidence_by_source" in source
    assert "previous_strength" in source
    assert "evidence_records = list(best_evidence_by_source.values())" in source


def test_not_required_terms_state_is_reserved_for_manual_review() -> None:
    sql = MIGRATION.read_text()
    assert "terms_review_status <> 'NOT_REQUIRED'" in sql
    assert "or collection_method='MANUAL_REVIEW'" in sql


def test_foreign_key_supporting_indexes_are_present() -> None:
    sql = MIGRATION.read_text().lower()
    assert "competitors_created_by_user_idx" in sql
    assert "competitor_sources_terms_reviewer_idx" in sql
    assert "competitor_sources_created_by_user_idx" in sql
    assert "competitive_observations_created_by_user_idx" in sql
    assert "competitive_opportunities_created_by_user_idx" in sql
    assert "competitive_opportunity_evidence_observation_idx" in sql


def test_observation_dedupe_key_reuse_with_different_content_is_rejected() -> None:
    source = API.read_text()
    assert "observation dedupe key already exists with different content" in source.lower()
    assert 'existing["observed_at"] == payload.observed_at' in source


def test_observation_idempotency_compares_full_immutable_contract() -> None:
    source = API.read_text()
    assert 'existing["source_published_at"] == payload.source_published_at' in source
    assert 'existing["facts"] == payload.facts' in source
    assert 'existing["evidence"] == payload.evidence' in source
    assert 'float(existing["confidence"]) == payload.confidence' in source
    assert 'float(existing["relevance"]) == payload.relevance' in source


def test_blocked_or_rejected_competitor_evidence_cannot_qualify_new_opportunity() -> None:
    source = API.read_text()
    assert 'row["source_status"] == "BLOCKED"' in source
    assert 'row["competitor_status"] == "REJECTED"' in source
    assert "Blocked or rejected competitive evidence cannot qualify" in source


def test_opportunity_idempotency_includes_threshold_and_evidence_contract() -> None:
    source = API.read_text()
    sql = MIGRATION.read_text()
    assert "qualification_threshold numeric(6,5)" in sql
    assert 'float(existing["qualification_threshold"]) == payload.qualification_threshold' in source
    assert "existing_evidence_contract" in source
    assert "incoming_evidence_contract" in source
    assert "different evaluation contract" in source
