from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930124000_shopify_price_reconciliation.sql"
)
PIPELINE = ROOT / "backend" / "app" / "shopify_pipeline.py"
COMMANDS = ROOT / "backend" / "app" / "automation_commands.py"


def test_dr02_price_candidates_are_narrow_and_private() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "shopify_price_sync_candidates" in lower
    assert "sil.sync_state='published'" in lower
    assert "coalesce(sil.test_mode,false)=false" in lower
    assert "sil.listing_key not like 'shopify-pool:%'" in lower
    assert "sil.reserved_order_reference is null" in lower
    assert "sil.reserved_line_reference is null" in lower
    assert "i.status='approved'" in lower
    assert "i.sale_intent='for_sale'" in lower
    assert "i.store_price_minor <> sil.synced_price_minor" in lower
    assert "security definer" in lower
    assert "grant execute on function tcg.shopify_price_sync_candidates" in lower
    assert "grant select on tcg.shopify_inventory_links" not in lower


def test_dr02_finalize_revalidates_exact_versions_and_audits() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "finalize_shopify_price_sync" in lower
    assert "v_current.link_version <> p_expected_link_version" in lower
    assert "v_current.inventory_version <> p_expected_inventory_version" in lower
    assert "v_current.store_price_minor <> p_target_price_minor" in lower
    assert "'retry_required'" in lower
    assert "'shopify_price_synced'" in lower
    assert "'automation:shopify-product-updates'" in lower
    assert "update tcg.inventory_items" not in lower


def test_dr02_fastapi_service_keeps_shopify_io_outside_database_transactions() -> None:
    source = PIPELINE.read_text()
    start = source.index("async def reconcile_shopify_product_prices(")
    end = source.index('@router.post("/price-sync")', start)
    block = source[start:end]

    assert "shopify_price_sync_candidates" in block
    assert "shopify.update_variant_price(" in block
    assert "finalize_shopify_price_sync(" in block
    assert "remote_price_minor != target_price" in block
    assert "connection.transaction()" not in block


def test_dr02_signed_command_fails_batch_when_any_item_needs_attention() -> None:
    source = COMMANDS.read_text()
    start = source.index('@router.post("/shopify/product-updates")')
    end = source.index('@router.post("/shopify/inventory-approved")', start)
    block = source[start:end]

    assert "ShopifyProductUpdatesCommand.model_validate_json" in block
    assert "if not settings.shopify_publish_enabled" in block
    assert "reconcile_shopify_product_prices(" in block
    assert 'result.get("failed_count")' in block
    assert 'result.get("retry_required_count")' in block
    assert "status_code=502" in block
    assert "status_code=409" in block
