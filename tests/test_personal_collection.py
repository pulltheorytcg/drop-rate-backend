from pathlib import Path

from app.schemas import InventorySaleIntentChange


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20260928164500_personal_collection_sale_intent.sql"
WORKFLOW = ROOT / "backend" / "app" / "inventory_sale_intent.py"
API = ROOT / "backend" / "app" / "api.py"
STATE = ROOT / "backend" / "app" / "inventory_state.py"
SHOPIFY = ROOT / "backend" / "app" / "shopify_pipeline.py"
SHOPIFY_READINESS = ROOT / "backend" / "app" / "shopify_readiness.py"
EBAY = ROOT / "backend" / "app" / "ebay_sales.py"
MARKETPLACE = ROOT / "backend" / "app" / "marketplace_listings.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_sale_intent_schema_accepts_only_supported_intents() -> None:
    assert InventorySaleIntentChange(version=1, sale_intent="FOR_SALE").sale_intent == "FOR_SALE"
    assert (
        InventorySaleIntentChange(
            version=1, sale_intent="PERSONAL_COLLECTION"
        ).sale_intent
        == "PERSONAL_COLLECTION"
    )


def test_personal_collection_is_separate_from_inventory_lifecycle() -> None:
    sql = MIGRATION.read_text()
    assert "add column if not exists sale_intent" in sql
    assert "default 'FOR_SALE'" in sql
    assert "sale_intent in ('FOR_SALE', 'PERSONAL_COLLECTION')" in sql
    assert "status not in ('RESERVED', 'SOLD')" in sql
    assert "grant update(sale_intent)" in sql
    assert "inventory_items_status_check" not in sql


def test_sale_intent_changes_are_database_audited() -> None:
    sql = MIGRATION.read_text()
    assert "audit_inventory_sale_intent_change" in sql
    assert "'SALE_INTENT_CHANGED'" in sql
    assert "tcg.audit_events" in sql
    assert "current_setting('tcg.user_id'" in sql
    assert "current_setting('tcg.request_id'" in sql


def test_personal_collection_transition_is_owner_scoped_and_versioned() -> None:
    source = WORKFLOW.read_text()
    assert '@router.post("/inventory/{inventory_id}/sale-intent")' in source
    assert "where id=$1 and owner_id=$2" in source
    assert 'item["status"] == "SOLD"' in source
    assert 'item["status"] == "RESERVED"' in source
    assert 'int(item["version"]) != payload.version' in source
    assert "version=version+1" in source
    assert "PERSONAL_COLLECTION" in source


def test_personal_collection_pauses_existing_pool_membership() -> None:
    source = WORKFLOW.read_text()
    assert "state='ACTIVE'" in source
    assert "set state='PAUSED'" in source
    assert "MEMBERSHIP_PAUSED_PERSONAL_COLLECTION" in source
    assert "marketplace_audit_events" in source


def test_personal_collection_withdraws_channels_but_for_sale_does_not_relist() -> None:
    source = WORKFLOW.read_text()
    assert "withdraw_ebay_for_inventory" in source
    assert "withdraw_shopify_for_inventory" in source
    assert 'reason="PERSONAL_COLLECTION"' in source
    assert '"requires_listing": True' in source
    assert "No marketplace listing was reactivated automatically." in source


def test_failed_channel_withdrawal_keeps_local_personal_protection() -> None:
    source = WORKFLOW.read_text()
    assert '"sale_intent": "PERSONAL_COLLECTION"' in source
    assert '"action_required": bool(withdrawal_errors)' in source
    assert "more channel withdrawals need to be retried" in source
    assert "current_version" in source


def test_shopify_never_allocates_or_syncs_personal_collection_stock() -> None:
    source = SHOPIFY.read_text()
    assert 'missing.append("FOR_SALE intent")' in source
    assert "and i.sale_intent='FOR_SALE'" in source
    assert 'link["sale_intent"] == "FOR_SALE"' in source
    assert "and sale_intent='FOR_SALE'" in source
    assert "withdraw_shopify_for_inventory" in source
    assert "sync_state='ARCHIVED'" in source
    assert 'status="DRAFT"' in source
    assert "quantity=0" in source


def test_ebay_never_publishes_or_sells_personal_collection_stock() -> None:
    source = EBAY.read_text()
    assert 'blockers.append("inventory is in PERSONAL_COLLECTION")' in source
    assert 'current["sale_intent"] != "FOR_SALE"' in source
    assert 'link["sale_intent"] != "FOR_SALE"' in source
    assert "status='APPROVED' and sale_intent='FOR_SALE'" in source


def test_pooled_marketplace_never_reserves_personal_collection_stock() -> None:
    source = MARKETPLACE.read_text()
    assert 'item["sale_intent"] != "FOR_SALE"' in source
    assert "and sale_intent='FOR_SALE' and version=$3" in source
    assert 'missing.append("FOR_SALE intent")' in source


def test_personal_collection_is_not_a_shopify_readiness_work_item() -> None:
    readiness = SHOPIFY_READINESS.read_text()
    shopify = SHOPIFY.read_text()
    assert "and i.sale_intent='FOR_SALE'" in readiness
    assert "and i.sale_intent='FOR_SALE'" in shopify


def test_inventory_api_exposes_and_filters_sale_intent() -> None:
    api = API.read_text()
    state = STATE.read_text()
    assert "sale_intent_filter: SaleIntent" in api
    assert 'alias="sale_intent"' in api
    assert "i.sale_intent =" in api
    assert "i.sale_intent, i.notes" in api
    assert "i.sale_intent" in state
    assert "personal_collection" in api


def test_sale_intent_router_is_wired_without_platform_admin_dependency() -> None:
    main = MAIN.read_text()
    assert "inventory_sale_intent_router" in main
    assert "app.include_router(inventory_sale_intent_router)" in main
    assert (
        "app.include_router(inventory_sale_intent_router, "
        "dependencies=[Depends(require_platform_admin_request)])"
        not in main
    )


def test_shopify_relisting_is_explicit_and_reuses_existing_link() -> None:
    source = SHOPIFY.read_text()
    start = source.index("async def sync_one_test_item(")
    end = source.index("def _parse_order_lines(", start)
    sync = source[start:end]
    assert 'existing["sync_state"] == "SOLD"' in sync
    assert 'existing["sync_state"] == "PUBLISHED"' in sync
    assert '"ARCHIVED"' in sync
    assert '"ERROR"' in sync
    assert "Existing Shopify link has no matching remote product" in sync
    assert "Existing Shopify link points to a different remote product" in sync
    assert "Existing Shopify link points to a different variant" in sync
    assert "Existing Shopify link points to a different inventory item" in sync
    assert "set sync_state='DRAFT'" in sync
    assert "set sync_state='PUBLISHED'" in sync
