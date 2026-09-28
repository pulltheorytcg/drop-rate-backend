from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    StorageLocationAssignment,
    StorageLocationAssignmentItem,
    StorageLocationCreate,
    StorageLocationPatch,
)


ROOT = Path(__file__).parents[1]
BACKEND = ROOT / "backend" / "app"
STATIC = BACKEND / "static"
MIGRATION = ROOT / "database" / "migrations" / "202609230004_storage_locations.sql"


def test_storage_location_create_normalises_code_and_text() -> None:
    payload = StorageLocationCreate(
        code=" binder-01/page-04 ",
        label=" Pokémon Binder Page 4 ",
        location_type="BINDER",
        notes="  top row  ",
    )
    assert payload.code == "BINDER-01/PAGE-04"
    assert payload.label == "Pokémon Binder Page 4"
    assert payload.notes == "top row"


def test_storage_location_patch_requires_a_change() -> None:
    with pytest.raises(ValidationError, match="At least one"):
        StorageLocationPatch(version=1)


def test_storage_location_assignment_rejects_duplicate_inventory() -> None:
    inventory_id = uuid4()
    with pytest.raises(ValidationError, match="only once"):
        StorageLocationAssignment(
            items=[
                StorageLocationAssignmentItem(inventory_id=inventory_id, version=1),
                StorageLocationAssignmentItem(inventory_id=inventory_id, version=1),
            ]
        )


def test_storage_location_migration_has_owner_scope_audit_and_sync() -> None:
    sql = MIGRATION.read_text()
    assert "create table tcg.storage_locations" in sql
    assert "add column storage_location_id" in sql
    assert "enable row level security" in sql
    assert "unique (owner_id, code)" in sql
    assert "Storage location code is immutable once created" in sql
    assert "Storage location is missing, inactive, or belongs to another owner" in sql
    assert "new.location := location_code" in sql
    assert "storage_locations_audit" in sql


def test_api_blocks_free_text_location_and_stocked_deactivation() -> None:
    api_source = (BACKEND / "api.py").read_text()
    location_source = (BACKEND / "storage_locations.py").read_text()
    assert "Physical location must be changed using a registered storage location" in api_source
    assert "Move inventory out of this location before deactivating it" in location_source
    assert "Cannot assign inventory to an inactive location" in location_source
    assert "One or more inventory items changed" in location_source


def test_approval_and_readiness_use_registered_storage_location() -> None:
    api_source = (BACKEND / "api.py").read_text()
    assert "and i.storage_location_id is not null" in api_source
    assert '"missing_location": f"({WORK_INVENTORY_SQL}) and i.storage_location_id is null"' in api_source
    assert 'item["storage_location_id"] is None' in api_source
    assert 'missing.append("registered storage location")' in api_source


def test_inventory_supports_location_filters() -> None:
    api_source = (BACKEND / "api.py").read_text()
    assert "storage_location_id: UUID | None" in api_source
    assert "unlocated: bool" in api_source
    assert "i.storage_location_id is null" in api_source
    assert "sl.code as storage_location_code" in api_source


def test_storage_location_dashboard_asset_is_loaded() -> None:
    html = (STATIC / "index.html").read_text()
    js = (STATIC / "storage-locations.js").read_text()
    assert '/assets/storage-locations.js' in html
    assert "Storage Locations" in js
    assert "Unlocated inventory" in js
    assert "assignSelectedLocation" in js
    assert "edit-storage-location" in js


def test_assign_all_unlocated_is_owner_scoped_idempotent_and_visible() -> None:
    api_source = (BACKEND / "storage_locations.py").read_text()
    js_source = (STATIC / "storage-locations.js").read_text()
    assert '"/storage-locations/{location_id}/assign-unlocated"' in api_source
    assert "where id = $1 and owner_id = $2" in api_source
    assert "and storage_location_id is null" in api_source
    assert "status in ('DRAFT', 'INSPECTION', 'APPROVED', 'WITHDRAWN')" in api_source
    assert "version = version + 1" in api_source
    assert "assignAllUnlocated" in js_source
    assert "Assign unlocated" in js_source
