from pathlib import Path

import pytest

from app.shopify_pipeline import (
    ShopifyProcessingError,
    _handle,
    _minor,
    _money,
    _product_gid_matches,
    _variant_gid,
)


ROOT = Path(__file__).parents[1]
PIPELINE = ROOT / "backend" / "app" / "shopify_pipeline.py"
SHOPIFY = ROOT / "backend" / "app" / "shopify.py"
CLIENT = ROOT / "backend" / "app" / "shopify_client.py"
MAIN = ROOT / "backend" / "app" / "main.py"
MIGRATION = ROOT / "migrations" / "006_shopify_inventory_links.sql"


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


def test_single_item_sync_requires_all_local_sellability_gates() -> None:
    source = PIPELINE.read_text()
    assert "if not settings.shopify_test_publish_enabled" in source
    assert "if settings.shopify_publish_enabled" in source
    assert 'item["status"] != "APPROVED"' in source
    assert 'not item["identity_confirmed"]' in source
    assert 'item["acquisition_cost_minor"] is None' in source
    assert 'item["store_price_minor"] is None' in source
    assert 'item["storage_location_id"] is None' in source
    assert '"single-item-test"' in source


def test_remote_retry_identity_is_inventory_id_not_title_similarity() -> None:
    source = PIPELINE.read_text()
    assert '"namespace": "drop_rate"' in source
    assert '"key": "inventory_id"' in source
    assert "remote_inventory_id != str(inventory_id)" in source
    assert "deterministic Shopify handle belongs to a different inventory item" in source


def test_paid_order_allocation_is_exact_and_fail_closed() -> None:
    source = PIPELINE.read_text()
    assert "where sil.owner_id=$1" in source
    assert "and sil.shopify_variant_gid=$2" in source
    assert "and sil.sync_state='PUBLISHED'" in source
    assert "order by sil.allocation_priority, sil.linked_at, sil.inventory_id" in source
    assert "for update of sil, i" in source
    assert "INSUFFICIENT_LINKED_STOCK" in source
    assert "INVENTORY_NOT_APPROVED" in source
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
    assert "where id=$1 and owner_id=$2 and status='APPROVED'" in source
    assert "set sync_state='SOLD'" in source
    assert "shopify_order_item_links" in source


def test_sale_ledger_stays_pending_until_shopify_fees_are_known() -> None:
    source = PIPELINE.read_text()
    assert "'SALE_REVENUE'" in source
    assert "'SHIPPING_REVENUE'" in source
    assert "'PENDING'" in source
    assert "platform/payment fees are not yet settled" in source


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
