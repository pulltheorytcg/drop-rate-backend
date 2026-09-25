from pathlib import Path

import pytest
from pydantic import ValidationError

from app.identity_review import IdentityConfirmRequest, IdentityReviewSelection
from app.schemas import InventoryPatch, ManualInventoryCreate


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations" / "004_identity_verification_events.sql"
API = ROOT / "backend" / "app" / "identity_review.py"
MAIN = ROOT / "backend" / "app" / "main.py"
FRONTEND = ROOT / "backend" / "app" / "static" / "identity-review.js"


def test_identity_confirmation_selection_rejects_duplicate_inventory_ids() -> None:
    item_id = "11111111-1111-1111-1111-111111111111"
    with pytest.raises(ValidationError):
        IdentityConfirmRequest(
            items=[
                IdentityReviewSelection(inventory_id=item_id, version=1),
                IdentityReviewSelection(inventory_id=item_id, version=1),
            ]
        )


def test_generic_inventory_patch_cannot_change_identity_trust() -> None:
    with pytest.raises(ValidationError):
        InventoryPatch(version=1, identity_confirmed=True)
    with pytest.raises(ValidationError):
        InventoryPatch(version=1, identity_confirmed=False)


def test_manual_intake_cannot_start_identity_confirmed() -> None:
    with pytest.raises(ValidationError):
        ManualInventoryCreate(
            catalogue_id="11111111-1111-1111-1111-111111111111",
            identity_confirmed=True,
        )


def test_identity_evidence_table_is_insert_only_for_api_role_and_rls_protected() -> None:
    sql = MIGRATION.read_text().casefold()
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "grant select, insert on table tcg.identity_verification_events to tcg_api" in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
    assert "own_verification_read" in sql
    assert "own_verification_insert" in sql


def test_catalogue_change_invalidates_current_identity_confirmation() -> None:
    sql = MIGRATION.read_text()
    assert "invalidate_identity_on_catalogue_change" in sql
    assert "new.identity_confirmed := false" in sql
    assert "before update of catalogue_id" in sql


def test_identity_confirmation_is_owner_scoped_versioned_and_locked() -> None:
    source = API.read_text()
    assert "where i.owner_id=$1 and i.id=any($2::uuid[])" in source
    assert "for update" in source
    assert "where id=$4 and owner_id=$5 and version=$6" in source
    assert "Selected copies do not all belong to this canonical card" in source
    assert "identity_verification_events" in source
    assert "'PHYSICAL_REVIEW'" in source


def test_identity_review_router_is_wired() -> None:
    source = MAIN.read_text()
    assert "from .identity_review import router as identity_review_router" in source
    assert "app.include_router(identity_review_router)" in source
    assert 'identity-review.js' in source


def test_identity_confirmation_normalises_explicit_language() -> None:
    request = IdentityConfirmRequest(
        items=[
            IdentityReviewSelection(
                inventory_id="11111111-1111-1111-1111-111111111111",
                version=1,
            )
        ],
        language=" jp ",
    )
    assert request.language == "Japanese"


def test_identity_confirmation_language_is_audited_and_fail_closed_on_mismatch() -> None:
    source = API.read_text()
    frontend = FRONTEND.read_text()
    assert "catalogue_language = clean_language" in source
    assert "requested_language = clean_language(payload.language)" in source
    assert "Selected language does not match the canonical card" in source
    assert "Language must be physically verified before identity" in source
    assert "conflicts with the canonical card." in source
    assert "language=coalesce($2,language,$3)" in source
    assert 'id="identity-language"' in frontend
    assert '<option value="English">English (EN)</option>' in frontend
    assert '<option value="Japanese">Japanese (JP)</option>' in frontend
    assert 'language: byId("identity-language").value || null' in frontend
    assert '"Language not verified"' in frontend


def test_identity_review_queue_reports_language_completeness() -> None:
    source = API.read_text()
    frontend = FRONTEND.read_text()
    assert "count(*) filter(where i.language is not null)::int as language_copies" in source
    assert "group.language_copies" in frontend
    assert "language ·" in frontend
