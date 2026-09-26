from pathlib import Path

import pytest

from app.shopify_pipeline import (
    ShopifyProcessingError,
    _build_media_intake_queue,
    _handle,
    _minor,
    _money,
    _parse_order_lines,
    _product_gid_matches,
    _refund_shipping_minor,
    _test_sync_missing,
    _title,
    _variant_gid,
)


ROOT = Path(__file__).parents[1]
PIPELINE = ROOT / "backend" / "app" / "shopify_pipeline.py"
SHOPIFY = ROOT / "backend" / "app" / "shopify.py"
CLIENT = ROOT / "backend" / "app" / "shopify_client.py"
MAIN = ROOT / "backend" / "app" / "main.py"
SHOPIFY_SETTINGS = ROOT / "backend" / "app" / "static" / "shopify-settings.js"
MEDIA_CONDITION = ROOT / "backend" / "app" / "static" / "media-condition.js"
MIGRATION = ROOT / "migrations" / "006_shopify_inventory_links.sql"
PENDING_MIGRATION = ROOT / "database" / "migrations" / "20260924230955_shopify_pending_order_reservations.sql"
FINAL_ORDER_MIGRATION = ROOT / "database" / "migrations" / "20260924232925_remove_pending_finance_order_status.sql"
SHIPPING_REFUND_MIGRATION = ROOT / "database" / "migrations" / "20260924235450_shopify_shipping_refunds.sql"
MEDIA_REGISTRY_MIGRATION = ROOT / "database" / "migrations" / "20260925154423_media_assets_registry.sql"
SHIPPING_PROFILE_MIGRATION = ROOT / "database" / "migrations" / "20260925162748_shopify_shipping_profiles.sql"
FULFILMENT_COST_MIGRATION = ROOT / "database" / "migrations" / "20260925172500_fulfilment_cost_components.sql"
FULFILMENT_ALLOCATION_MIGRATION = ROOT / "database" / "migrations" / "20260925182500_fulfilment_material_allocation.sql"


def test_money_helpers_are_penny_exact() -> None:
    assert _money(0) == "0.00"
    assert _money(187) == "1.87"
    assert _money(12345) == "123.45"
    assert _minor("1.87", field="price") == 187
    assert _minor("1.875", field="price") == 188
    with pytest.raises(ShopifyProcessingError, match="Negative"):
        _minor("-0.01", field="price")


def test_shopify_variant_ids_fail_closed() -> None:
    assert _variant_gid("123") == "gid://shopify/ProductVariant/123"
    gid = "gid://shopify/ProductVariant/456"
    assert _variant_gid(gid) == gid
    with pytest.raises(ShopifyProcessingError):
        _variant_gid("")
    with pytest.raises(ShopifyProcessingError):
        _variant_gid("not-a-variant")


def test_product_gid_matching_never_fuzzy_matches() -> None:
    gid = "gid://shopify/Product/123456"
    assert _product_gid_matches(gid, 123456)
    assert _product_gid_matches(gid, "123456")
    assert not _product_gid_matches(gid, "12345")
    assert not _product_gid_matches(gid, None)


def test_test_product_handle_is_inventory_specific_and_deterministic() -> None:
    assert _handle("INV-ABC-001") == "drop-rate-inv-abc-001"
    assert _handle("INV ABC 001") == "drop-rate-inv-abc-001"


def test_test_sync_gate_reports_exact_local_blockers() -> None:
    ready = {
        "status": "APPROVED",
        "identity_confirmed": True,
        "acquisition_cost_minor": 187,
        "product_type": "CARD",
        "grading_company": None,
        "grade": None,
        "condition": "Near Mint",
        "condition_review_status": "VERIFIED_NEAR_MINT",
        "seal_status": None,
        "language": "English",
        "catalogue_language": None,
        "store_price_minor": 499,
        "storage_location_id": "location-id",
        "registered_location_id": "location-id",
        "registered_location_active": True,
    }
    assert _test_sync_missing(ready) == []

    blocked = {
        **ready,
        "status": "DRAFT",
        "identity_confirmed": False,
        "store_price_minor": None,
        "storage_location_id": None,
        "registered_location_id": None,
        "registered_location_active": None,
    }
    assert _test_sync_missing(blocked) == [
        "APPROVED status",
        "identity confirmation",
        "store price",
        "registered storage location",
    ]


def test_shopify_test_status_exposes_same_gate_blockers_to_dashboard() -> None:
    source = PIPELINE.read_text()
    frontend = SHOPIFY_SETTINGS.read_text()
    assert "missing = _test_sync_missing(row)" in source
    assert "missing = _test_sync_missing(item)" in source
    assert '"readiness": {' in source
    assert '"blockers": blocker_counts' in source
    assert "Eligible inventory" in frontend
    assert "Closest item to ready" in frontend
    assert "Readiness ·" in frontend


def test_single_item_sync_requires_all_local_sellability_gates() -> None:
    source = PIPELINE.read_text()
    assert "if not settings.shopify_test_publish_enabled" in source
    assert "if settings.shopify_publish_enabled" in source
    assert 'item["status"] != "APPROVED"' in source
    assert 'not item["identity_confirmed"]' in source
    assert 'item["acquisition_cost_minor"] is None' in source
    assert 'item["product_type"] == "CARD"' in source
    assert 'missing.append("photo-backed Near Mint verification")' in source
    assert 'missing.append("graded slab verification")' in source
    assert 'missing.append("card language")' in source
    assert 'item["store_price_minor"] is None' in source
    assert 'item["storage_location_id"] is None' in source
    assert 'if not launch["complete"]:' in source
    assert "product_create_input(plan, handle=handle)" in source


def test_shopify_api_failures_return_safe_gateway_response() -> None:
    source = MAIN.read_text()
    assert "except ShopifyApiError as exc:" in source
    assert '"detail": "Shopify operation failed"' in source
    assert '"retryable": exc.retryable' in source
    assert "status_code=502" in source


def test_remote_retry_identity_is_inventory_id_not_title_similarity() -> None:
    source = PIPELINE.read_text()
    completeness = (
        ROOT / "backend" / "app" / "shopify_completeness.py"
    ).read_text()
    assert '"namespace": "drop_rate"' in completeness
    assert '"inventory_id"' in completeness
    assert 'remote_inventory_code != item["inventory_code"]' in source
    assert "deterministic Shopify handle belongs to a different inventory item" in source


def test_order_line_parser_requires_exact_ids_prices_and_gbp() -> None:
    payload = {
        "id": 1001,
        "currency": "GBP",
        "line_items": [{
            "id": 2001,
            "quantity": 1,
            "variant_id": 3001,
            "price": "0.49",
            "total_discount": "0.00",
            "sku": "INV-1",
            "product_id": 4001,
        }],
    }
    order_reference, specs, variants = _parse_order_lines(
        payload,
        event_label="created order",
    )
    assert order_reference == "1001"
    assert variants == ["gid://shopify/ProductVariant/3001"]
    assert specs[0]["line_reference"] == "2001"
    assert specs[0]["unit_price_minor"] == 49

    bad = {**payload, "currency": "USD"}
    with pytest.raises(ShopifyProcessingError, match="Only GBP"):
        _parse_order_lines(bad, event_label="created order")


def test_shipping_refund_parser_is_penny_exact_and_gbp_only() -> None:
    payload = {
        "refund_shipping_lines": [{
            "subtotal_amount_set": {
                "shop_money": {"amount": "4.99", "currency_code": "GBP"}
            }
        }]
    }
    assert _refund_shipping_minor(payload) == 499
    assert _refund_shipping_minor({"refund_shipping_lines": []}) == 0
    assert _refund_shipping_minor({}) == 0

    bad = {
        "refund_shipping_lines": [{
            "subtotal_amount_set": {
                "shop_money": {"amount": "4.99", "currency_code": "USD"}
            }
        }]
    }
    with pytest.raises(
        ShopifyProcessingError,
        match="shipping refund currency",
    ):
        _refund_shipping_minor(bad)


def test_shipping_refund_ledger_type_is_versioned() -> None:
    sql = SHIPPING_REFUND_MIGRATION.read_text().casefold()
    assert "financial_ledger_entries_entry_type_check" in sql
    assert "'shipping_refund'::text" in sql


def test_shopify_refund_reverses_shipping_and_caps_over_refunds() -> None:
    source = PIPELINE.read_text()
    start = source.index("async def _process_refund(")
    refund = source[start:]
    assert "shipping_refund_minor = _refund_shipping_minor(payload)" in refund
    assert "entry_type='SHIPPING_REFUND'" in refund
    assert "'SHIPPING_REFUND',$4" in refund
    assert "SHIPPING_REFUND_EXCEEDS_REVENUE" in refund
    assert "SHIPPING_REFUND_WITHOUT_REVENUE" in refund
    assert "SHIPPING_REFUND_ALLOCATION_EXCEEDED" in refund
    assert "allocate_minor(" in refund
    assert "for update" in refund
    assert "entry_type in ('SALE_REVENUE','SHIPPING_REVENUE')" in refund
    assert "entry_type in ('REFUND','SHIPPING_REFUND')" in refund
    assert "REFUND_EXCEEDS_GROSS_REVENUE" in refund
    assert '"shipping_refund_minor": shipping_refund_minor' in refund


def test_unpaid_shopify_orders_use_reservations_not_finance_order_state() -> None:
    reservation_sql = PENDING_MIGRATION.read_text().casefold()
    final_sql = FINAL_ORDER_MIGRATION.read_text().casefold()
    assert "reserved_order_reference text" in reservation_sql
    assert "reserved_line_reference text" in reservation_sql
    assert "reserved_at timestamptz" in reservation_sql
    assert "shopify_inventory_links_reservation_tuple_check" in reservation_sql
    assert "shopify_inventory_links_reserved_order_idx" in reservation_sql
    assert "where status='pending'" in final_sql
    assert "'paid'::text" in final_sql
    assert "'partially_refunded'::text" in final_sql
    assert "'refunded'::text" in final_sql
    assert "'cancelled'::text" in final_sql
    constraint_start = final_sql.index("add constraint orders_status_check")
    assert "'pending'::text" not in final_sql[constraint_start:]


def test_order_create_reserves_without_creating_financial_records() -> None:
    source = PIPELINE.read_text()
    start = source.index("async def _process_created_order(")
    end = source.index("async def _process_paid_order(", start)
    created = source[start:end]
    assert "set status='RESERVED'" in created
    assert "reserved_order_reference=$2" in created
    assert "shopify_webhook_events" in created
    assert "ORDER_ALREADY_CANCELLED" in created
    assert "insert into tcg.orders" not in created
    assert "financial_ledger_entries" not in created
    assert "order_items(" not in created


def test_paid_order_consumes_matching_reservation_or_falls_back_to_approved() -> None:
    source = PIPELINE.read_text()
    assert 'link["inventory_status"] == "APPROVED"' in source
    assert 'link["inventory_status"] == "RESERVED"' in source
    assert 'link["reserved_order_reference"] == order_reference' in source
    assert "INVENTORY_RESERVED_OTHER_ORDER" in source
    assert 'expected_status = link["inventory_status"]' in source
    assert "reserved_order_reference=null" in source
    assert "reserved_line_reference=null" in source
    assert "reserved_at=null" in source


def test_cancel_releases_reservation_without_writing_unpaid_finance_order() -> None:
    source = PIPELINE.read_text()
    created_start = source.index("async def _process_created_order(")
    paid_start = source.index("async def _process_paid_order(", created_start)
    created = source[created_start:paid_start]
    cancel_start = source.index("async def _process_cancelled_order(")
    refund_start = source.index("async def _process_refund(", cancel_start)
    cancelled = source[cancel_start:refund_start]
    assert "set status='APPROVED'" in cancelled
    assert "where sil.reserved_order_reference=$1" in cancelled
    assert "PENDING_ORDER_RELEASED" in cancelled
    assert "MANAGED_ORDER_CANCELLED_WITHOUT_RESERVATION" in cancelled
    assert "insert into tcg.orders" not in cancelled
    assert "shopify_webhook_events" in created
    assert "ORDER_ALREADY_CANCELLED" in created


def test_out_of_order_shopify_webhooks_resolve_owner_before_order_lookup() -> None:
    source = PIPELINE.read_text()
    scope_start = source.index("async def _resolve_order_owner_scope(")
    scope_end = source.index("async def _select_order_units(", scope_start)
    scope = source[scope_start:scope_end]
    assert "sync_state in ('PUBLISHED','SOLD')" in scope

    create_start = source.index("async def _process_created_order(")
    create_end = source.index("async def _process_paid_order(", create_start)
    created = source[create_start:create_end]
    assert created.index("_resolve_order_owner_scope(") < created.index(
        "select id,status from tcg.orders"
    )
    assert created.index("set_config('tcg.user_id'") < created.index(
        "select id,status from tcg.orders"
    )
    assert "ORDER_ALREADY_FINALIZED" in created

    paid_start = source.index("async def _process_paid_order(")
    paid_end = source.index("async def _process_cancelled_order(", paid_start)
    paid = source[paid_start:paid_end]
    assert paid.index("_resolve_order_owner_scope(") < paid.index(
        "select id,status from tcg.orders"
    )
    assert paid.index("set_config('tcg.user_id'") < paid.index(
        "select id,status from tcg.orders"
    )
    assert "ORDER_ALREADY_RECORDED" in paid


def test_failed_webhook_deliveries_remain_retryable() -> None:
    source = SHOPIFY.read_text()
    assert 'if event["status"] in {"PROCESSED", "IGNORED"}:' in source
    assert "FAILED" not in source[
        source.index('if event["status"] in {"PROCESSED", "IGNORED"}:'):
        source.index('if initial_status == "IGNORED":')
    ]


def test_shopify_test_sync_fails_before_remote_create_when_launch_incomplete() -> None:
    source = PIPELINE.read_text()
    start = source.index("async def sync_one_test_item(")
    end = source.index("def _parse_order_lines(", start)
    sync = source[start:end]
    completeness_pos = sync.index('if not launch["complete"]:')
    create_pos = sync.index("client.create_product(")
    assert completeness_pos < create_pos
    assert "No remote product was created or published." in sync
    assert "media_completeness(" in source
    assert "ACTIVE_FAIL_CLOSED" in source
    assert "approval_status='APPROVED'" in source
    assert "rights_status='VERIFIED'" in source
    assert "shopify_file_status='READY'" in source


def test_shopify_shipping_profile_registry_is_rls_protected_and_audited() -> None:
    sql = SHIPPING_PROFILE_MIGRATION.read_text().casefold()
    assert "create table tcg.shopify_shipping_profiles" in sql
    assert "enable row level security" in sql
    assert "create policy own_records" in sql
    assert "grant select, insert, update" in sql
    assert "revoke delete" in sql
    assert "weight_value" in sql
    assert "weight_unit" in sql
    assert "shopify_shipping_profiles_audit" in sql
    assert "shipping profile key is immutable once created" in sql
    assert "audit_shopify_shipping_profile_change" in sql
    assert "security definer" in sql
    assert (
        "revoke all on function tcg.audit_shopify_shipping_profile_change() "
        "from public"
    ) in sql


def test_fulfilment_cost_registry_is_owner_scoped_audited_and_penny_exact() -> None:
    sql = FULFILMENT_COST_MIGRATION.read_text().casefold()
    assert "create table tcg.fulfilment_cost_components" in sql
    assert "enable row level security" in sql
    assert "create policy own_records" in sql
    assert "revoke delete" in sql
    assert "native_unit_cost_minor" in sql
    assert "accounting_unit_cost_minor_gbp" in sql
    assert "fulfilment_cost_components_audit" in sql
    assert "fulfilment cost owner is immutable once created" in sql


def test_fulfilment_cost_api_is_versioned_owner_scoped_and_gbp_only() -> None:
    source = PIPELINE.read_text()
    assert (
        '@router.put(\n'
        '    "/shipping-profiles/{profile_id}/cost-components/{component_key}"\n'
        ')' in source
    )
    assert 'component_key not in {"PACKAGING", "TOPLOADER"}' in source
    assert "where id=$1 and owner_id=$2" in source
    assert "Fulfilment cost component changed" in source
    assert "native_currency='GBP'" in source
    assert "accounting_unit_cost_minor_gbp=$6" in source
    assert '"PER_ORDER" if component_key == "PACKAGING" else "PER_ITEM"' in source
    assert "allocation_basis=$7" in source
    allocation_sql = FULFILMENT_ALLOCATION_MIGRATION.read_text()
    assert "allocation_basis in (\'PER_ORDER\', \'PER_ITEM\')" in allocation_sql
    assert "package_length_mm" in source
    assert "empty_package_weight_grams" in source


def test_shopify_sync_requires_shipping_profile_before_remote_create() -> None:
    source = PIPELINE.read_text()
    start = source.index("async def sync_one_test_item(")
    end = source.index("def _parse_order_lines(", start)
    sync = source[start:end]
    assert "_shipping_profiles(" in source
    assert "shipping_profiles=shipping_profiles" in sync
    assert 'shipping_spec=launch["shippingSpec"]' in sync
    assert 'expected_shipping_spec=launch["shippingSpec"]' in sync
    assert sync.index('if not launch["complete"]:') < sync.index("client.create_product(")


def test_shopify_shipping_profile_api_is_versioned_and_owner_scoped() -> None:
    source = PIPELINE.read_text()
    assert '@router.get("/shipping-profiles")' in source
    assert '@router.post("/shipping-profiles", status_code=201)' in source
    assert '@router.patch("/shipping-profiles/{profile_id}")' in source
    assert "where id=$1 and owner_id=$2" in source
    assert "current_version" in source
    assert "RAW_CARD" in source
    assert "GRADED_CARD" in source


def test_media_registry_is_rls_protected_rights_gated_and_audited() -> None:
    sql = MEDIA_REGISTRY_MIGRATION.read_text().casefold()
    assert "create table tcg.media_assets" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "revoke all on table tcg.media_assets from anon, authenticated" in sql
    assert "create policy readable_assets" in sql
    assert "create policy own_asset_writes" in sql
    assert "grant select,insert,update" in sql
    assert "revoke delete" in sql
    assert "rights_status='verified'" in sql
    assert "approval_status='approved'" in sql
    assert "shopify_file_status='ready'" in sql
    assert "media_assets_audit" in sql
    assert "audit_media_asset_change" in sql
    assert "security definer" in sql
    assert "revoke all on function tcg.audit_media_asset_change() from public" in sql
    assert "'uploaded'" in sql


def test_shopify_sync_assigns_collections_media_and_verifies_remote_state() -> None:
    source = PIPELINE.read_text()
    start = source.index("async def sync_one_test_item(")
    end = source.index("def _parse_order_lines(", start)
    sync = source[start:end]
    assert "list_collections_by_title()" in sync
    assert "add_product_to_collection(" in sync
    assert "attach_file_to_product(" in sync
    assert "get_product_snapshot(" in sync
    assert "verify_remote_product(" in sync
    assert 'expected_status="DRAFT"' in sync
    assert 'expected_status="ACTIVE"' in sync
    assert "product_published_on_publication(" in sync
    assert "Product was forced back to DRAFT." in sync
    assert "set sync_state='PUBLISHED'" in sync
    assert sync.index("verify_remote_product(") < sync.index("set sync_state='PUBLISHED'")


def test_media_registry_has_explicit_human_approval_and_shopify_file_sync() -> None:
    source = PIPELINE.read_text()
    assert '@router.post("/media-assets/{asset_id}/approve")' in source
    assert "rights_status='VERIFIED'" in source
    assert "approval_status='APPROVED'" in source
    assert "approved_by_user_id" in source
    assert '@router.post("/media-assets/{asset_id}/sync")' in source
    assert "create_file_from_url(" in source
    assert "get_file(" in source
    assert "Media must be rights-verified and approved before Shopify sync" in source


def test_shopify_sync_uses_complete_product_plan_not_legacy_minimal_payload() -> None:
    source = PIPELINE.read_text()
    start = source.index("async def sync_one_test_item(")
    end = source.index("def _parse_order_lines(", start)
    sync = source[start:end]
    assert "build_shopify_product_plan" in source
    assert "product_create_input(plan, handle=handle)" in sync
    assert '"vendor": "Drop Rate"' not in sync
    assert '"single-item-test"' not in sync


def test_shopify_dashboard_surfaces_launch_completeness_and_preview() -> None:
    frontend = SHOPIFY_SETTINGS.read_text()
    assert "Preview Shopify page" in frontend
    assert "Launch completeness" in frontend
    assert "Launch ·" in frontend
    assert "approved media registry active — publishing remains fail-closed" in frontend
    assert "previewSelectedShopifyProduct" in frontend
    assert "/api/v1/shopify/product-preview/" in frontend
    assert "productPlan" in frontend
    assert "productCompleteness" in frontend
    assert "Shipping specifications" in frontend
    assert "/api/v1/shopify/shipping-profiles" in frontend
    assert "configureShopifyShippingProfile" in frontend
    assert "configureFulfilmentCosts" in frontend
    assert "shopifyFulfilmentSummary" in frontend
    assert "cost-components" in frontend
    assert "Package dimensions in millimetres" in frontend
    assert "Required profile:" in frontend


def test_shopify_dashboard_disables_sync_until_launch_ready() -> None:
    frontend = SHOPIFY_SETTINGS.read_text()
    start = frontend.index("function refreshShopifyTestButton()")
    end = frontend.index("async function previewSelectedShopifyProduct()", start)
    block = frontend[start:end]
    assert 'option?.dataset?.launchReady === "true"' in block
    assert "|| !launchReady" in block
    assert "previewButton.disabled = !select.value" in block


def test_shopify_product_preview_is_read_only_and_exposes_blockers() -> None:
    source = PIPELINE.read_text()
    start = source.index('@router.get("/product-preview/{inventory_id}")')
    end = source.index('@router.get("/test-sync")', start)
    preview = source[start:end]
    assert "productPlan" in preview
    assert "productCompleteness" in preview
    assert "operationalBlockers" in preview
    assert "launchReady" in preview
    assert "create_product(" not in preview
    assert "publish_product(" not in preview


def test_paid_order_allocation_is_exact_and_fail_closed() -> None:
    source = PIPELINE.read_text()
    assert "where sil.owner_id=$1" in source
    assert "and sil.shopify_variant_gid=$2" in source
    assert "and sil.sync_state='PUBLISHED'" in source
    assert "order by sil.allocation_priority, sil.linked_at, sil.inventory_id" in source
    assert "for update of sil, i" in source
    assert "INSUFFICIENT_LINKED_STOCK" in source
    assert "INVENTORY_RESERVED_OTHER_ORDER" in source
    assert "PRICE_DRIFT" in source
    assert "SKU_MISMATCH" in source
    assert "PRODUCT_MISMATCH" in source


def test_shopify_order_is_idempotent_at_order_and_line_allocation_layers() -> None:
    source = PIPELINE.read_text()
    sql = MIGRATION.read_text().casefold()
    assert "where source='shopify' and source_reference=$1" in source.casefold()
    assert "ORDER_ALREADY_RECORDED" in source
    assert "order_item_id uuid not null unique" in sql
    assert "unique(shopify_order_id, shopify_line_item_id, allocation_index)" in sql


def test_webhook_delivery_retry_is_payload_hash_safe() -> None:
    source = SHOPIFY.read_text()
    assert "event[\"payload_sha256\"] != payload_sha256" in source
    assert "Webhook ID was reused with a different payload" in source
    assert 'event["status"] in {"PROCESSED", "IGNORED"}' in source
    assert "process_shopify_webhook(" in source
    assert "status='FAILED'" in source


def test_sale_snapshots_cost_and_marks_exact_inventory_sold() -> None:
    source = PIPELINE.read_text()
    assert "cost_basis_minor" in source
    assert "link[\"acquisition_cost_minor\"]" in source
    assert "set status='SOLD'" in source
    assert "where id=$1 and owner_id=$2 and status=$3" in source
    assert "set sync_state='SOLD'" in source
    assert "shopify_order_item_links" in source


def test_sale_ledger_stays_pending_until_shopify_fees_are_known() -> None:
    source = PIPELINE.read_text()
    assert "'SALE_REVENUE'" in source
    assert "'SHIPPING_REVENUE'" in source
    assert "'PENDING'" in source
    assert "platform/payment fees are not yet settled" in source


def test_refund_invalidates_previous_shopify_fee_reconciliation() -> None:
    source = PIPELINE.read_text()
    start = source.index("async def _process_refund(")
    refund = source[start:]
    assert "update tcg.order_item_reconciliations" in refund
    assert "fees_reconciled_at=null" in refund
    assert "fees_source=null" in refund


def test_refund_restock_never_returns_directly_to_approved() -> None:
    source = PIPELINE.read_text()
    assert "PARTIAL_RESTOCK_REFUND" in source
    assert "set status='INSPECTION'" in source
    assert "set sync_state='ARCHIVED'" in source
    assert "set_inventory_quantity(" in source
    assert "quantity=0" in source


def test_shopify_link_tables_have_uniqueness_and_forced_rls() -> None:
    sql = MIGRATION.read_text().casefold()
    assert "inventory_id uuid not null unique" in sql
    assert "unique(listing_key, allocation_priority)" in sql
    assert "unique(shopify_order_id, shopify_line_item_id, allocation_index)" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "revoke all on table tcg.shopify_inventory_links from anon, authenticated" in sql
    assert "revoke all on table tcg.shopify_order_item_links from anon, authenticated" in sql
    assert "shopify_order_item_links_owner_idx" in sql


def test_shopify_pipeline_router_is_wired_separately_from_webhook_boundary() -> None:
    source = MAIN.read_text()
    assert "from .shopify_pipeline import router as shopify_pipeline_router" in source
    assert "app.include_router(shopify_pipeline_router)" in source


def test_shopify_client_has_only_explicit_mutation_primitives() -> None:
    source = CLIENT.read_text()
    for method in (
        "create_product",
        "update_variant",
        "activate_inventory",
        "set_inventory_quantity",
        "set_product_status",
        "publish_product",
    ):
        assert f"async def {method}" in source
    assert "inventoryPolicy" in source
    assert '"DENY"' in source


def test_shopify_titles_always_show_structured_card_language() -> None:
    item = {
        "name": "Eiscue ex",
        "language": "Japanese",
        "catalogue_language": None,
        "card_number": "178",
        "variant": "Foil",
        "grading_company": None,
        "grade": None,
        "condition": "Near Mint",
    }
    assert _title(item) == "Eiscue ex · JP · 178 · Foil · Near Mint"


def test_shopify_title_does_not_duplicate_existing_language_tag() -> None:
    item = {
        "name": "Eiscue ex (JP)",
        "language": "Japanese",
        "catalogue_language": None,
        "card_number": "178",
        "variant": "",
        "grading_company": "PSA",
        "grade": "10",
        "condition": None,
    }
    assert _title(item) == "Eiscue ex · JP · 178 · PSA 10"


def test_founder_media_upload_target_is_fail_closed_and_scope_gated() -> None:
    source = PIPELINE.read_text()
    client = CLIENT.read_text()
    assert 'class MediaUploadTargetRequest(BaseModel):' in source
    assert '@router.get("/media-assets/upload-capability")' in source
    assert '@router.post("/media-assets/upload-target")' in source
    assert '"write_files" not in scopes' in source
    assert '"Cache-Control"] = "no-store"' in source
    assert 'le=20 * 1024 * 1024' in source
    assert 'pattern=r"^image/(jpeg|png|webp)$"' in source
    assert 'async def access_scopes' in client
    assert 'currentAppInstallation' in client
    assert 'async def create_staged_image_upload' in client
    assert 'stagedUploadsCreate' in client
    assert '"resource": "IMAGE"' in client


def test_founder_media_intake_is_visible_and_requires_explicit_rights_confirmation() -> None:
    ui = MEDIA_CONDITION.read_text()
    helper = SHOPIFY_SETTINGS.read_text()
    assert 'id="shopify-media-file"' in ui
    assert 'id="shopify-media-rights"' in ui
    assert 'id="shopify-media-upload-button"' in ui
    assert 'I own or am authorised to use this photograph' in ui
    assert 'button.dataset.scopeReady !== "true"' in helper
    assert 'source_type: "FOUNDER_UPLOAD"' in helper
    assert 'Founder-owned original photograph; rights explicitly confirmed during upload' in helper
    assert 'new FormData()' in helper
    assert 'form.append("file", file)' in helper
    assert '/api/v1/shopify/media-assets/upload-target' in helper
    assert '/approve' in helper
    assert '/sync' in helper
    assert 'capture_context: captureContext || null' in helper



def test_media_intake_queue_requires_each_physical_card_front_and_back() -> None:
    raw_a = {
        "id": "00000000-0000-0000-0000-000000000001",
        "catalogue_id": "10000000-0000-0000-0000-000000000001",
        "inventory_code": "INV-RAW-1",
        "product_type": "CARD",
        "game": "Pokemon",
        "name": "Seel",
        "set_name": "Phantasmal Flames",
        "card_number": "021/094",
        "variant": "Normal",
        "language": "English",
        "catalogue_language": None,
        "grading_company": None,
        "grade": None,
    }
    raw_b = {
        **raw_a,
        "id": "00000000-0000-0000-0000-000000000002",
        "inventory_code": "INV-RAW-2",
    }
    graded = {
        **raw_a,
        "id": "00000000-0000-0000-0000-000000000003",
        "catalogue_id": "10000000-0000-0000-0000-000000000002",
        "inventory_code": "INV-PSA-1",
        "name": "Charizard",
        "card_number": "4/102",
        "grading_company": "PSA",
        "grade": "10",
    }

    result = _build_media_intake_queue([raw_a, raw_b, graded], [])

    assert result["queue_count"] == 3
    assert result["missing_side_count"] == 6
    assert result["physical_items_pending"] == 3
    assert result["raw_items_pending"] == 2
    assert result["raw_canonical_groups_pending"] == 0
    assert result["graded_items_pending"] == 1
    assert all(item["required_scope"] == "INVENTORY_ITEM" for item in result["items"])

    first = next(item for item in result["items"] if item["inventory_id"] == raw_a["id"])
    second = next(item for item in result["items"] if item["inventory_id"] == raw_b["id"])
    slab = next(item for item in result["items"] if item["inventory_id"] == graded["id"])
    assert first["inventory_codes"] == ["INV-RAW-1"]
    assert second["inventory_codes"] == ["INV-RAW-2"]
    assert first["missing_sides"] == ["FRONT", "BACK"]
    assert second["missing_sides"] == ["FRONT", "BACK"]
    assert first["capture_context_options"] == [
        "RAW_UNSLEEVED",
        "PENNY_SLEEVE",
        "TOP_LOADER",
    ]
    assert slab["capture_context_hint"] == "GRADED_SLAB"
    assert slab["missing_sides"] == ["FRONT", "BACK"]


def test_media_intake_queue_does_not_recapture_approved_processing_physical_media() -> None:
    raw = {
        "id": "00000000-0000-0000-0000-000000000001",
        "catalogue_id": "10000000-0000-0000-0000-000000000001",
        "inventory_code": "INV-RAW-1",
        "product_type": "CARD",
        "game": "Pokemon",
        "name": "Seel",
        "set_name": "Phantasmal Flames",
        "card_number": "021/094",
        "variant": "Normal",
        "language": "English",
        "catalogue_language": None,
        "grading_company": None,
        "grade": None,
    }
    assets = [
        {
            "scope": "INVENTORY_ITEM",
            "catalogue_id": raw["catalogue_id"],
            "inventory_id": raw["id"],
            "side": side,
            "approval_status": "APPROVED",
            "rights_status": "VERIFIED",
            "shopify_file_status": "PROCESSING",
        }
        for side in ("FRONT", "BACK")
    ]

    result = _build_media_intake_queue([raw], assets)

    assert result["queue_count"] == 0
    assert result["missing_side_count"] == 0


def test_canonical_media_never_satisfies_physical_card_capture() -> None:
    raw = {
        "id": "00000000-0000-0000-0000-000000000001",
        "catalogue_id": "10000000-0000-0000-0000-000000000001",
        "inventory_code": "INV-RAW-1",
        "product_type": "CARD",
        "game": "Pokemon",
        "name": "Seel",
        "set_name": "Phantasmal Flames",
        "card_number": "021/094",
        "variant": "Normal",
        "language": "English",
        "catalogue_language": None,
        "grading_company": None,
        "grade": None,
    }
    canonical = [{
        "scope": "CANONICAL_CARD",
        "catalogue_id": raw["catalogue_id"],
        "inventory_id": None,
        "side": "FRONT",
        "approval_status": "APPROVED",
        "rights_status": "VERIFIED",
        "shopify_file_status": "READY",
    }]

    result = _build_media_intake_queue([raw], canonical)

    assert result["queue_count"] == 1
    assert result["items"][0]["inventory_id"] == raw["id"]
    assert result["items"][0]["missing_sides"] == ["FRONT", "BACK"]


def test_failed_media_reenters_capture_queue() -> None:
    graded = {
        "id": "00000000-0000-0000-0000-000000000003",
        "catalogue_id": "10000000-0000-0000-0000-000000000002",
        "inventory_code": "INV-PSA-1",
        "product_type": "CARD",
        "game": "Pokemon",
        "name": "Charizard",
        "set_name": "Base Set",
        "card_number": "4/102",
        "variant": "Holofoil",
        "language": "English",
        "catalogue_language": None,
        "grading_company": "PSA",
        "grade": "10",
    }
    assets = [
        {
            "scope": "INVENTORY_ITEM",
            "catalogue_id": graded["catalogue_id"],
            "inventory_id": graded["id"],
            "side": "FRONT",
            "approval_status": "APPROVED",
            "rights_status": "VERIFIED",
            "shopify_file_status": "READY",
        },
        {
            "scope": "INVENTORY_ITEM",
            "catalogue_id": graded["catalogue_id"],
            "inventory_id": graded["id"],
            "side": "BACK",
            "approval_status": "APPROVED",
            "rights_status": "VERIFIED",
            "shopify_file_status": "FAILED",
        },
    ]

    result = _build_media_intake_queue([graded], assets)

    assert result["queue_count"] == 1
    assert result["items"][0]["missing_sides"] == ["BACK"]
    assert result["items"][0]["ready_sides"] == ["FRONT"]


def test_founder_media_ui_uses_dedicated_physical_capture_queue() -> None:
    helper = SHOPIFY_SETTINGS.read_text()
    ui = MEDIA_CONDITION.read_text()
    source = PIPELINE.read_text()

    assert '@router.get("/media-assets/intake-queue")' in source
    assert 'id="shopify-media-candidate"' in ui
    assert 'apiRequest("/api/v1/shopify/media-assets/intake-queue")' in ui
    assert 'byId("shopify-media-candidate")?.selectedOptions?.[0]' in helper
    assert 'dataset.mediaScope' in helper
    assert 'dataset.inventoryId' in helper
    assert 'shared canonical raw-card image' not in helper
    assert 'id="shopify-media-context"' in ui
    assert "PENNY_SLEEVE" in ui
    assert "TOP_LOADER" in ui
    assert "GRADED_SLAB" in ui

def test_shopify_price_sync_is_bounded_price_only_and_fail_closed() -> None:
    source = PIPELINE.read_text()
    start = source.index('@router.post("/price-sync")')
    end = source.index('@router.post("/test-sync/{inventory_id}")')
    block = source[start:end]

    assert "limit < 1 or limit > 100" in block
    assert "sil.sync_state in ('DRAFT','PUBLISHED')" in block
    assert "i.status='APPROVED'" in block
    assert "i.store_price_minor <> sil.synced_price_minor" in block
    assert "client.update_variant_price(" in block
    assert "Phase 2: Shopify I/O with no DB transaction open." in block
    assert "for update of sil,i" in block
    assert '"RETRY_REQUIRED"' in block
    assert "set synced_price_minor=$1" in block
    assert "publish_product" not in block
    assert "set_inventory_quantity" not in block
    assert "activate_inventory" not in block


def test_batch_founder_media_is_rights_gated_sequential_and_never_publishes() -> None:
    helper = SHOPIFY_SETTINGS.read_text()
    ui = MEDIA_CONDITION.read_text()
    start = helper.index("async function uploadFounderMediaBatch()")
    end = helper.index("async function syncFounderMedia(", start)
    block = helper[start:end]

    assert 'id="shopify-media-batch-files"' in ui
    assert 'type="file" multiple' in ui
    assert 'id="shopify-media-batch-rights"' in ui
    assert 'id="shopify-media-batch-context"' in ui
    assert "These are founder-owned original photographs" in ui
    assert "parseBatchMediaFilename" in helper
    assert "validateBatchMediaFiles" in helper
    assert "Duplicate card side in this batch" in helper
    assert "Inventory ID is not present in the current media capture queue" in helper
    assert "button.dataset.scopeReady" in helper
    assert "for (let index = 0; index < validation.work.length; index += 1)" in block
    assert "await uploadFounderMediaWork({...item, captureContext: item.captureContext})" in block
    assert "Promise.all" not in block
    assert "publish" not in block.casefold()
    assert "test-sync" not in block


def test_batch_media_maps_exact_inventory_id_and_never_shared_canonical_copy() -> None:
    helper = SHOPIFY_SETTINGS.read_text()
    assert "option.dataset.inventoryCodes" in helper
    assert "item.inventory_codes || [item.inventory_code || \"\"]" in helper
    assert ".split(\",\")" in helper
    assert "codes.forEach((code) => mapping.set(code, option))" in helper
    assert 'scope: option.dataset.mediaScope || "INVENTORY_ITEM"' in helper


def test_media_create_fails_closed_on_duplicate_live_side() -> None:
    source = PIPELINE.read_text()
    assert "An active media asset already exists for this physical item side" in source
    assert "An active media asset already exists for this canonical card side" in source
    assert "approval_status <> 'REJECTED'" in source
    assert "shopify_file_status <> 'FAILED'" in source


def test_media_live_side_uniqueness_is_database_enforced() -> None:
    migration = (
        ROOT
        / "database"
        / "migrations"
        / "20260926002000_media_live_side_uniqueness.sql"
    ).read_text()
    assert "media_assets_canonical_live_side_uidx" in migration
    assert "media_assets_inventory_live_side_uidx" in migration
    assert "create unique index" in migration.casefold()
    assert "approval_status <> 'REJECTED'" in migration
    assert "shopify_file_status <> 'FAILED'" in migration
