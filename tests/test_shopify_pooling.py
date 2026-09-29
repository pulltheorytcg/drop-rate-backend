from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.shopify_client import ShopifyAdminClient
from app.shopify_pooling import _evaluate_group, raw_pool_identity


ROOT = Path(__file__).parents[1]
POOLING = ROOT / "backend" / "app" / "shopify_pooling.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def _row(**overrides):
    row = {
        "inventory_id": uuid4(),
        "catalogue_id": uuid4(),
        "owner_id": uuid4(),
        "inventory_code": f"INV-{uuid4().hex.upper()}",
        "status": "APPROVED",
        "sale_intent": "FOR_SALE",
        "identity_confirmed": True,
        "language": "English",
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
        "acquisition_cost_minor": 187,
        "storage_location_id": uuid4(),
        "store_price_minor": 500,
        "inventory_version": 1,
        "product_type": "CARD",
        "catalogue_language": None,
        "link_id": uuid4(),
        "created_by_user_id": uuid4(),
        "listing_key": f"catalogue:{uuid4()}",
        "allocation_priority": 1,
        "shop_domain": "example.myshopify.com",
        "shopify_product_gid": f"gid://shopify/Product/{uuid4().int % 10**12}",
        "shopify_variant_gid": f"gid://shopify/ProductVariant/{uuid4().int % 10**12}",
        "shopify_inventory_item_gid": f"gid://shopify/InventoryItem/{uuid4().int % 10**12}",
        "shopify_location_gid": "gid://shopify/Location/1",
        "shopify_publication_gid": "gid://shopify/Publication/1",
        "sku": f"INV-{uuid4().hex.upper()}",
        "sync_state": "DRAFT",
        "test_mode": False,
        "synced_price_minor": 500,
        "linked_at": "2026-09-29T00:00:00+00:00",
        "reserved_order_reference": None,
        "reserved_line_reference": None,
        "link_version": 1,
        "has_listing_membership": False,
        "has_active_reservation": False,
    }
    row.update(overrides)
    return row


def _pair(**overrides):
    catalogue_id = overrides.pop("catalogue_id", uuid4())
    first = _row(catalogue_id=catalogue_id, **overrides)
    second = _row(
        catalogue_id=catalogue_id,
        linked_at="2026-09-29T00:00:01+00:00",
        **overrides,
    )
    return first, second


def test_raw_pool_identity_is_case_and_whitespace_normalised() -> None:
    catalogue_id = uuid4()
    first = _row(
        catalogue_id=catalogue_id,
        language=" English ",
        condition="Near   Mint",
    )
    second = _row(
        catalogue_id=catalogue_id,
        language="english",
        condition="near mint",
    )
    assert raw_pool_identity(first)["listing_key"] == raw_pool_identity(second)["listing_key"]
    assert raw_pool_identity(first)["sku"] == raw_pool_identity(second)["sku"]
    assert raw_pool_identity(first)["sku"].startswith("DRP-")


def test_offer_language_or_condition_changes_pool_identity() -> None:
    catalogue_id = uuid4()
    en = _row(catalogue_id=catalogue_id, language="English", condition="Near Mint")
    jp = _row(catalogue_id=catalogue_id, language="Japanese", condition="Near Mint")
    lp = _row(catalogue_id=catalogue_id, language="English", condition="Lightly Played")
    assert raw_pool_identity(en)["listing_key"] != raw_pool_identity(jp)["listing_key"]
    assert raw_pool_identity(en)["listing_key"] != raw_pool_identity(lp)["listing_key"]


def test_ready_raw_duplicate_group_can_pool() -> None:
    first, second = _pair()
    result = _evaluate_group([first, second])
    assert result["ready"] is True
    assert result["blockers"] == []
    assert result["quantity"] == 2
    assert result["price_minor"] == 500
    assert result["primary_inventory_id"] == str(first["inventory_id"])


@pytest.mark.parametrize(
    ("change", "blocker"),
    [
        ({"status": "DRAFT"}, "inventory not APPROVED"),
        ({"identity_confirmed": False}, "identity not confirmed"),
        ({"language": None, "catalogue_language": None}, "missing language"),
        ({"condition": None}, "missing condition"),
        ({"acquisition_cost_minor": None}, "missing acquisition cost"),
        ({"storage_location_id": None}, "missing storage location"),
        ({"grading_company": "PSA", "grade": "10"}, "graded inventory cannot auto-pool"),
        ({"reserved_order_reference": "123", "reserved_line_reference": "456"}, "Shopify link reserved by order"),
        ({"has_listing_membership": True}, "inventory already belongs to marketplace listing"),
        ({"has_active_reservation": True}, "inventory actively reserved"),
    ],
)
def test_raw_pool_fails_closed_on_member_readiness(change, blocker) -> None:
    first, second = _pair()
    second.update(change)
    result = _evaluate_group([first, second])
    assert result["ready"] is False
    assert blocker in result["blockers"]


def test_raw_pool_rejects_price_mismatch() -> None:
    first, second = _pair()
    second["store_price_minor"] = 600
    result = _evaluate_group([first, second])
    assert result["ready"] is False
    assert "pool members have different store prices" in result["blockers"]


def test_raw_pooling_is_draft_only_and_concurrency_locked() -> None:
    source = POOLING.read_text()
    assert "sil.sync_state='DRAFT'" in source
    assert "pg_try_advisory_lock" in source
    assert "pg_advisory_unlock" in source
    assert 'status="ARCHIVED"' in source
    assert "quantity=len(members)" in source
    assert "record_shopify_raw_pool_audit" in source


def test_raw_pool_uses_privileged_audit_writer_not_direct_table_insert() -> None:
    source = POOLING.read_text().lower()
    assert "record_shopify_raw_pool_audit" in source
    assert "insert into tcg.audit_events" not in source


def test_raw_pool_commit_points_every_member_at_primary_variant() -> None:
    source = POOLING.read_text()
    assert "shopify_product_gid=$4" in source
    assert "shopify_variant_gid=$5" in source
    assert "shopify_inventory_item_gid=$6" in source
    assert "allocation_priority=$3" in source
    assert "version=version+1" in source
    assert "sync_state='DRAFT'" in source


def test_pooling_router_is_platform_admin_wired() -> None:
    main = MAIN.read_text()
    assert "from .shopify_pooling import router as shopify_pooling_router" in main
    assert (
        "app.include_router(shopify_pooling_router, "
        "dependencies=[Depends(require_platform_admin_request)])"
    ) in main


@pytest.mark.asyncio
async def test_pool_identity_update_does_not_touch_cost_or_shipping() -> None:
    client = ShopifyAdminClient(
        shop_domain="example.myshopify.com",
        client_id="client",
        client_secret="secret",
        api_version="2026-07",
    )
    captured = {}

    async def fake_graphql(*, query, variables=None):
        captured["query"] = query
        captured["variables"] = variables
        return {
            "productVariantsBulkUpdate": {
                "productVariants": [{
                    "id": "gid://shopify/ProductVariant/1",
                    "price": "5.00",
                    "inventoryPolicy": "DENY",
                    "inventoryItem": {
                        "id": "gid://shopify/InventoryItem/1",
                        "sku": "DRP-ABC",
                        "tracked": True,
                    },
                }],
                "userErrors": [],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    result = await client.update_variant_pool_identity(
        product_id="gid://shopify/Product/1",
        variant_id="gid://shopify/ProductVariant/1",
        price="5.00",
        sku="DRP-ABC",
    )

    variant_input = captured["variables"]["variants"][0]
    assert variant_input["inventoryPolicy"] == "DENY"
    assert variant_input["inventoryItem"] == {"sku": "DRP-ABC", "tracked": True}
    assert "cost" not in json.dumps(variant_input).casefold()
    assert "measurement" not in json.dumps(variant_input).casefold()
    assert result["inventoryItem"]["sku"] == "DRP-ABC"
