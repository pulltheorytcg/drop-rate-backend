from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.shopify_published_pooling import evaluate_published_group


CATALOGUE_ID = uuid4()
OWNER_ID = uuid4()
ACTOR_ID = uuid4()
LOCATION = "gid://shopify/Location/1"
PUBLICATION = "gid://shopify/Publication/1"


def _row(
    *,
    code: str,
    product: str,
    variant: str,
    inventory_item: str,
    listing_key: str | None = None,
    sku: str | None = None,
    price: int = 100,
    priority: int = 1,
    grading_company: str | None = None,
    grade: str | None = None,
) -> dict:
    return {
        "inventory_id": uuid4(),
        "catalogue_id": CATALOGUE_ID,
        "owner_id": OWNER_ID,
        "inventory_code": code,
        "status": "APPROVED",
        "sale_intent": "FOR_SALE",
        "identity_confirmed": True,
        "language": "English",
        "condition": "Near Mint",
        "grading_company": grading_company,
        "grade": grade,
        "acquisition_cost_minor": 187,
        "storage_location_id": uuid4(),
        "store_price_minor": price,
        "product_type": "CARD",
        "catalogue_language": "English",
        "link_id": uuid4(),
        "created_by_user_id": ACTOR_ID,
        "listing_key": listing_key or f"inventory:{code}",
        "allocation_priority": priority,
        "shop_domain": "example.myshopify.com",
        "shopify_product_gid": product,
        "shopify_variant_gid": variant,
        "shopify_inventory_item_gid": inventory_item,
        "shopify_location_gid": LOCATION,
        "shopify_publication_gid": PUBLICATION,
        "sku": sku or code,
        "sync_state": "PUBLISHED",
        "test_mode": False,
        "synced_price_minor": price,
        "linked_at": datetime(2026, 9, 29, priority, tzinfo=timezone.utc),
        "reserved_order_reference": None,
        "reserved_line_reference": None,
        "link_version": 1,
        "has_listing_membership": False,
        "has_active_reservation": False,
    }


def test_existing_pool_is_preferred_as_published_anchor() -> None:
    pooled_product = "gid://shopify/Product/10"
    rows = [
        _row(
            code="INV-A",
            product=pooled_product,
            variant="gid://shopify/ProductVariant/10",
            inventory_item="gid://shopify/InventoryItem/10",
            listing_key="shopify-pool:existing",
            sku="DRP-EXISTING",
            priority=1,
        ),
        _row(
            code="INV-B",
            product=pooled_product,
            variant="gid://shopify/ProductVariant/10",
            inventory_item="gid://shopify/InventoryItem/10",
            listing_key="shopify-pool:existing",
            sku="DRP-EXISTING",
            priority=2,
        ),
        _row(
            code="INV-C",
            product="gid://shopify/Product/20",
            variant="gid://shopify/ProductVariant/20",
            inventory_item="gid://shopify/InventoryItem/20",
            priority=3,
        ),
    ]

    group = evaluate_published_group(rows)

    assert group["ready"] is True
    assert group["quantity"] == 3
    assert group["anchor_product_gid"] == pooled_product
    assert group["retire_product_gids"] == ["gid://shopify/Product/20"]


def test_mixed_prices_fail_closed() -> None:
    rows = [
        _row(
            code="INV-A",
            product="gid://shopify/Product/10",
            variant="gid://shopify/ProductVariant/10",
            inventory_item="gid://shopify/InventoryItem/10",
            price=100,
        ),
        _row(
            code="INV-B",
            product="gid://shopify/Product/20",
            variant="gid://shopify/ProductVariant/20",
            inventory_item="gid://shopify/InventoryItem/20",
            price=200,
            priority=2,
        ),
    ]

    group = evaluate_published_group(rows)

    assert group["ready"] is False
    assert "pool members have different store prices" in group["blockers"]
    assert "Shopify synced price mismatch" in group["blockers"]


def test_graded_inventory_never_enters_published_raw_pool() -> None:
    rows = [
        _row(
            code="INV-A",
            product="gid://shopify/Product/10",
            variant="gid://shopify/ProductVariant/10",
            inventory_item="gid://shopify/InventoryItem/10",
            grading_company="PSA",
            grade="10",
        ),
        _row(
            code="INV-B",
            product="gid://shopify/Product/20",
            variant="gid://shopify/ProductVariant/20",
            inventory_item="gid://shopify/InventoryItem/20",
            grading_company="PSA",
            grade="10",
            priority=2,
        ),
    ]

    group = evaluate_published_group(rows)

    assert group["ready"] is False
    assert "graded inventory cannot auto-pool" in group["blockers"]


def test_group_already_on_one_product_is_not_a_phase_b_candidate() -> None:
    product = "gid://shopify/Product/10"
    rows = [
        _row(
            code="INV-A",
            product=product,
            variant="gid://shopify/ProductVariant/10",
            inventory_item="gid://shopify/InventoryItem/10",
        ),
        _row(
            code="INV-B",
            product=product,
            variant="gid://shopify/ProductVariant/10",
            inventory_item="gid://shopify/InventoryItem/10",
            priority=2,
        ),
    ]

    group = evaluate_published_group(rows)

    assert group["ready"] is False
    assert "already on one Shopify product" in group["blockers"]
