from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.media import MediaAssetCreate, media_readiness_for_item


ROOT = Path(__file__).parents[1]
MEDIA = ROOT / "backend" / "app" / "media.py"
MAIN = ROOT / "backend" / "app" / "main.py"
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260925152522_media_registry_v1.sql"
)


INVENTORY_ID = UUID("00000000-0000-4000-8000-000000000101")
CATALOGUE_ID = UUID("00000000-0000-4000-8000-000000000102")


def _item(**overrides):
    item = {
        "id": INVENTORY_ID,
        "catalogue_id": CATALOGUE_ID,
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
    }
    item.update(overrides)
    return item


def _asset(
    *,
    scope: str,
    role: str,
    suffix: str,
    inventory_id: UUID | None = None,
):
    return {
        "id": UUID(f"00000000-0000-4000-8000-0000000002{suffix}"),
        "scope": scope,
        "catalogue_id": CATALOGUE_ID,
        "inventory_id": inventory_id,
        "asset_role": role,
        "asset_url": f"https://media.example.test/{suffix}.jpg",
        "alt_text": "Card image",
        "approval_status": "APPROVED",
        "is_primary": True,
        "display_order": 0,
        "rights_basis": "OWNED_PHOTOGRAPH",
        "source_kind": "FOUNDER_UPLOAD",
        "source_provider": None,
        "rights_checked_at": None,
        "rights_expires_at": None,
        "version": 1,
    }


def test_raw_card_can_use_approved_canonical_front_media() -> None:
    readiness = media_readiness_for_item(
        _item(),
        [_asset(scope="CATALOGUE", role="FRONT", suffix="01")],
    )
    assert readiness["complete"] is True
    assert readiness["policy"] == "CANONICAL_CARD_ALLOWED"
    assert readiness["requiredRoles"] == ["FRONT"]
    assert readiness["approvedMediaCount"] == 1
    assert readiness["selectedAssets"][0]["scope"] == "CATALOGUE"


def test_raw_card_prefers_item_specific_front_over_canonical_front() -> None:
    readiness = media_readiness_for_item(
        _item(),
        [
            _asset(scope="CATALOGUE", role="FRONT", suffix="01"),
            _asset(
                scope="INVENTORY",
                role="FRONT",
                suffix="02",
                inventory_id=INVENTORY_ID,
            ),
        ],
    )
    assert readiness["complete"] is True
    assert readiness["selectedAssets"][0]["scope"] == "INVENTORY"


def test_graded_card_requires_physical_front_and_back() -> None:
    graded = _item(condition=None, grading_company="PSA", grade="10")
    canonical_front = _asset(scope="CATALOGUE", role="FRONT", suffix="01")
    physical_front = _asset(
        scope="INVENTORY",
        role="FRONT",
        suffix="02",
        inventory_id=INVENTORY_ID,
    )

    incomplete = media_readiness_for_item(
        graded,
        [canonical_front, physical_front],
    )
    assert incomplete["complete"] is False
    assert incomplete["policy"] == "PHYSICAL_ITEM_REQUIRED"
    assert incomplete["missingRoles"] == ["BACK"]
    assert incomplete["blockers"] == ["approved physical back media"]

    complete = media_readiness_for_item(
        graded,
        [
            canonical_front,
            physical_front,
            _asset(
                scope="INVENTORY",
                role="BACK",
                suffix="03",
                inventory_id=INVENTORY_ID,
            ),
        ],
    )
    assert complete["complete"] is True
    assert complete["approvedMediaCount"] == 2
    assert all(
        asset["scope"] == "INVENTORY"
        for asset in complete["selectedAssets"]
    )


def test_media_create_requires_https_and_explicit_rights() -> None:
    with pytest.raises(ValidationError):
        MediaAssetCreate(
            scope="CATALOGUE",
            catalogue_id=CATALOGUE_ID,
            asset_role="FRONT",
            asset_url="http://example.test/card.jpg",
            source_kind="FOUNDER_UPLOAD",
            rights_basis="OWNED_PHOTOGRAPH",
            rights_reference="Founder capture",
        )

    with pytest.raises(ValidationError):
        MediaAssetCreate(
            scope="CATALOGUE",
            catalogue_id=CATALOGUE_ID,
            asset_role="FRONT",
            asset_url="https://example.test/card.jpg",
            source_kind="LICENSED_PROVIDER",
            rights_basis="LICENSED_PROVIDER",
            rights_reference="Provider terms",
        )


def test_inventory_media_catalogue_is_never_client_supplied() -> None:
    with pytest.raises(ValidationError):
        MediaAssetCreate(
            scope="INVENTORY",
            catalogue_id=CATALOGUE_ID,
            inventory_id=INVENTORY_ID,
            asset_role="FRONT",
            asset_url="https://example.test/card.jpg",
            source_kind="FOUNDER_UPLOAD",
            rights_basis="OWNED_PHOTOGRAPH",
            rights_reference="Founder capture",
        )


def test_media_registry_schema_is_rls_hardened_audited_and_owner_checked() -> None:
    sql = MIGRATION.read_text().casefold()
    assert "create table tcg.media_assets" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "revoke all on table tcg.media_assets from public, anon, authenticated" in sql
    assert "media_read" in sql
    assert "media_insert" in sql
    assert "media_update" in sql
    assert "m.role='founder'" in sql
    assert "inventory media owner does not match physical inventory" in sql
    assert "inventory media catalogue does not match physical inventory" in sql
    assert "audit_media_asset_change" in sql
    assert "revoke delete on tcg.media_assets from tcg_api" in sql


def test_media_provenance_is_immutable_in_database() -> None:
    sql = MIGRATION.read_text().casefold()
    assert "protect_media_asset_provenance" in sql
    assert "media provenance is immutable" in sql
    for field in (
        "asset_url",
        "source_kind",
        "source_provider",
        "source_reference",
        "rights_basis",
        "rights_reference",
        "checksum_sha256",
        "catalogue_id",
        "inventory_id",
        "owner_id",
    ):
        assert f"new.{field} is distinct from old.{field}" in sql


def test_expired_rights_are_excluded_from_media_readiness_query() -> None:
    source = MEDIA.read_text()
    assert "rights_expires_at is null or rights_expires_at > clock_timestamp()" in source
    assert "approval_status='APPROVED'" in source


def test_media_routes_are_founder_gated_and_version_protected() -> None:
    source = MEDIA.read_text()
    assert "Only a founder can manage approved marketplace media" in source
    assert '@router.post("/assets", status_code=201)' in source
    assert '@router.post("/assets/{asset_id}/decision")' in source
    assert 'row["version"] != payload.version' in source
    assert "approval_status=$2" in source


def test_media_router_is_registered_in_application() -> None:
    source = MAIN.read_text()
    assert "from .media import router as media_router" in source
    assert "app.include_router(media_router)" in source
