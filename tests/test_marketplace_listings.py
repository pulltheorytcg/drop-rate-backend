from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.marketplace_listings import listing_shape


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "backend" / "app" / "marketplace_listings.py"
MIGRATION = ROOT / "migrations" / "007_listing_reservation_engine.sql"
API = ROOT / "backend" / "app" / "api.py"
STORAGE = ROOT / "backend" / "app" / "storage_locations.py"
IDENTITY = ROOT / "backend" / "app" / "identity_review.py"
SHOPIFY = ROOT / "backend" / "app" / "shopify_pipeline.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def _raw_item(*, inventory_id=None, language="English", condition="Near Mint") -> dict:
    return {
        "id": inventory_id or uuid4(),
        "catalogue_id": uuid4(),
        "product_type": "CARD",
        "language": language,
        "catalogue_language": None,
        "condition": condition,
        "grading_company": None,
        "grade": None,
        "seal_status": None,
    }


def test_equivalent_raw_cards_share_fingerprint() -> None:
    catalogue_id = uuid4()
    first = _raw_item(inventory_id=uuid4())
    second = _raw_item(inventory_id=uuid4())
    first["catalogue_id"] = catalogue_id
    second["catalogue_id"] = catalogue_id

    a = listing_shape(first)
    b = listing_shape(second)

    assert a["pooling_mode"] == "POOLED"
    assert b["pooling_mode"] == "POOLED"
    assert a["fingerprint"] == b["fingerprint"]


def test_raw_card_pooling_is_case_and_whitespace_normalised() -> None:
    catalogue_id = uuid4()
    first = _raw_item(language=" English ", condition="Near   Mint")
    second = _raw_item(language="english", condition="near mint")
    first["catalogue_id"] = catalogue_id
    second["catalogue_id"] = catalogue_id

    assert listing_shape(first)["fingerprint"] == listing_shape(second)["fingerprint"]


def test_raw_card_without_language_fails_closed() -> None:
    item = _raw_item(language=None)
    with pytest.raises(HTTPException) as exc:
        listing_shape(item)
    assert exc.value.status_code == 422
    assert "language" in str(exc.value.detail).casefold()


def test_raw_card_can_be_forced_unique_for_high_value_or_copy_specific_stock() -> None:
    item = _raw_item()
    pooled = listing_shape(item)
    unique = listing_shape(item, force_unique=True)
    assert pooled["pooling_mode"] == "POOLED"
    assert unique["pooling_mode"] == "UNIQUE"
    assert pooled["fingerprint"] != unique["fingerprint"]


def test_graded_cards_are_never_auto_pooled() -> None:
    catalogue_id = uuid4()
    base = {
        "catalogue_id": catalogue_id,
        "product_type": "CARD",
        "language": "English",
        "catalogue_language": None,
        "condition": None,
        "grading_company": "PSA",
        "grade": "10",
        "seal_status": None,
    }
    first = {**base, "id": uuid4()}
    second = {**base, "id": uuid4()}

    a = listing_shape(first)
    b = listing_shape(second)

    assert a["pooling_mode"] == "UNIQUE"
    assert b["pooling_mode"] == "UNIQUE"
    assert a["fingerprint"] != b["fingerprint"]


def test_reservation_selection_is_deterministic_and_concurrency_safe() -> None:
    source = MODULE.read_text()
    assert "order by allocation_priority,eligible_since,inventory_id" in source
    assert "for update skip locked" in source
    assert "minimum_sale_price_minor <= $2" in source
    assert "status='APPROVED'" in source
    assert "identity_confirmed" in source
    assert "storage_location_id" in source


def test_reservation_snapshots_owner_cost_price_floor_and_inventory_version() -> None:
    source = MODULE.read_text()
    for field in (
        "sale_price_minor_snapshot",
        "acquisition_cost_minor_snapshot",
        "minimum_sale_price_minor_snapshot",
        "allocation_priority_snapshot",
        "inventory_version_snapshot",
    ):
        assert field in source


def test_reservation_request_is_semantically_idempotent() -> None:
    source = MODULE.read_text()
    sql = MIGRATION.read_text().casefold()
    assert "reservation idempotency key already exists with different parameters" in source.casefold()
    assert "unique(source,source_reference,source_line_reference,allocation_index)" in sql
    assert "inventory_reservations_one_active_per_item_idx" in sql


def test_reserved_inventory_has_database_level_state_guard() -> None:
    sql = MIGRATION.read_text()
    assert "'RESERVED'::text" in sql
    assert "protect_reserved_inventory" in sql
    assert "tcg.allow_reserved_transition" in sql
    assert "old.status = 'APPROVED'" in sql
    assert "new.status in ('APPROVED','SOLD')" in sql
    assert "inventory_reserved_guard" in sql


def test_reserved_inventory_is_blocked_from_generic_mutation_paths() -> None:
    assert 'current_item["status"] == "RESERVED"' in API.read_text()
    assert 'row["status"] in {"SOLD", "RESERVED"}' in API.read_text()
    storage = STORAGE.read_text()
    assert 'row["status"] == "SOLD"' in storage
    assert 'row["status"] == "RESERVED"' in storage
    assert '{"SOLD","WITHDRAWN","RESERVED"}' in IDENTITY.read_text()


def test_price_floor_controls_eligibility_without_changing_owner_cost() -> None:
    source = MODULE.read_text()
    assert 'int(member["minimum_sale_price_minor"]) > sale_price_minor' in source
    assert "price_floor_blocked_quantity" in source
    assert "acquisition_cost_minor" in source
    assert "minimum_sale_price_minor" in source


def test_single_item_shopify_path_and_pooled_listing_path_cannot_overlap() -> None:
    marketplace = MODULE.read_text()
    shopify = SHOPIFY.read_text()
    assert "active single-item Shopify link" in marketplace
    assert "listing_inventory_members lim" in shopify
    assert "marketplace listing/reservation system" in shopify


def test_removed_listing_membership_is_history_not_hard_delete() -> None:
    sql = MIGRATION.read_text().casefold()
    source = MODULE.read_text()
    assert "state in ('active','paused','removed')" in sql
    assert "where state <> 'removed'" in sql
    assert "removed_membership" in source
    assert "eligible_since=clock_timestamp()" in source


def test_listing_and_reservation_tables_use_forced_rls_and_no_delete_grant() -> None:
    sql = MIGRATION.read_text().casefold()
    for table in (
        "tcg.sellable_listings",
        "tcg.listing_inventory_members",
        "tcg.inventory_reservations",
    ):
        assert f"alter table {table} force row level security" in sql
        assert f"revoke all on table {table} from anon, authenticated" in sql
    assert "grant select,insert,update on table tcg.sellable_listings to tcg_api" in sql
    assert "grant select,insert,update on table tcg.listing_inventory_members to tcg_api" in sql
    assert "grant select,insert,update on table tcg.inventory_reservations to tcg_api" in sql
    assert "grant delete" not in sql


def test_test_reservations_can_expire_release_or_consume() -> None:
    source = MODULE.read_text()
    assert 'target: Literal["RELEASED", "CONSUMED", "EXPIRED"]' in source
    assert '@router.post("/reservations/expire-due")' in source
    assert 'next_inventory_status = "SOLD" if target == "CONSUMED" else "APPROVED"' in source


def test_marketplace_router_is_wired() -> None:
    main = MAIN.read_text()
    assert "from .marketplace_listings import router as marketplace_listings_router" in main
    assert "app.include_router(marketplace_listings_router, dependencies=[Depends(require_platform_admin_request)])" in main


def test_dashboard_exposes_reserved_and_sold_status_without_editing_them() -> None:
    html = (ROOT / "backend" / "app" / "static" / "index.html").read_text()
    js = (ROOT / "backend" / "app" / "static" / "app.js").read_text()
    assert '<option value="RESERVED">Reserved</option>' in html
    assert '<option value="SOLD">Sold</option>' in html
    assert '["RESERVED", "SOLD"].includes(item.status)' in js
    assert "Reserved for order" in js


def test_marketplace_audit_ledger_is_immutable_and_owner_scoped() -> None:
    sql = MIGRATION.read_text().casefold()
    source = MODULE.read_text()
    assert "create table if not exists tcg.marketplace_audit_events" in sql
    assert "force row level security" in sql
    assert "grant select,insert on table tcg.marketplace_audit_events to tcg_api" in sql
    assert "grant update" not in sql.split("tcg.marketplace_audit_events", 1)[1].split("create policy", 1)[0]
    assert "grant delete" not in sql
    assert "actor_user_id = tcg.current_user_id()" in sql
    assert "async def _audit_marketplace" in source
    for action in (
        "LISTING_CREATED",
        "MEMBERSHIP_JOINED",
        "LISTING_UPDATED",
        "MEMBERSHIP_UPDATED",
        "RESERVATION_CREATED",
    ):
        assert action in source


def test_reservation_transition_flag_is_reset_after_workflow() -> None:
    source = MODULE.read_text()
    assert source.count("set_config('tcg.allow_reserved_transition','off',true)") >= 2


def test_inactive_listing_reports_zero_eligible_stock() -> None:
    source = MODULE.read_text()
    assert 'listing_active = listing_status == "ACTIVE"' in source
    assert "if not listing_active:" in source
    assert "eligible = []" in source


def test_removed_unique_membership_can_be_reactivated_but_not_shared() -> None:
    source = MODULE.read_text()
    assert "removed_membership = None" in source
    assert 'listing["pooling_mode"] == "UNIQUE" and removed_membership is None' in source
    assert '"REACTIVATED"' in source


def test_language_is_required_before_approval_and_pooling() -> None:
    api = API.read_text()
    app = (ROOT / "backend" / "app" / "static" / "app.js").read_text()
    schemas = (ROOT / "backend" / "app" / "schemas.py").read_text()
    assert "i.language is not null and btrim(i.language) <> ''" in api
    assert 'missing.append("language")' in api
    assert '"missing_language"' in schemas
    assert 'missing_language: "Missing language"' in app


def test_reserved_stock_is_visible_but_excluded_from_work_queues() -> None:
    api = API.read_text()
    identity = IDENTITY.read_text()
    html = (ROOT / "backend" / "app" / "static" / "index.html").read_text()
    assert 'ACTIVE_INVENTORY_SQL = "i.status in (\'DRAFT\', \'INSPECTION\', \'APPROVED\')"' in api
    assert 'ACTIVE_SQL = "i.status in (\'DRAFT\', \'INSPECTION\', \'APPROVED\')"' in identity
    assert '<option value="RESERVED">Reserved</option>' in html
