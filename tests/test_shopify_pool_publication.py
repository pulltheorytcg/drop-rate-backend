from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.shopify_completeness import required_collection_titles
from app.shopify_pool_publication import _evaluate_pool, _remote_blockers


ROOT = Path(__file__).parents[1]
PUBLICATION = ROOT / "backend" / "app" / "shopify_pool_publication.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def _row(
    *,
    inventory_id=None,
    owner_id=None,
    priority=1,
    product_gid="gid://shopify/Product/1",
    variant_gid="gid://shopify/ProductVariant/2",
    inventory_item_gid="gid://shopify/InventoryItem/3",
    quantity_price=500,
):
    return {
        "inventory_id": inventory_id or uuid4(),
        "catalogue_id": uuid4(),
        "owner_id": owner_id or uuid4(),
        "inventory_code": f"INV-{uuid4().hex[:12].upper()}",
        "status": "APPROVED",
        "sale_intent": "FOR_SALE",
        "identity_confirmed": True,
        "language": "English",
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
        "store_price_minor": quantity_price,
        "storage_location_id": uuid4(),
        "product_type": "CARD",
        "game": "Pokemon",
        "set_name": "Test Set",
        "name": "Test Card",
        "card_number": "001/100",
        "variant": "Normal",
        "rarity": "Common",
        "catalogue_language": "English",
        "link_id": uuid4(),
        "listing_key": "shopify-pool:abc",
        "allocation_priority": priority,
        "shop_domain": "example.myshopify.com",
        "shopify_product_gid": product_gid,
        "shopify_variant_gid": variant_gid,
        "shopify_inventory_item_gid": inventory_item_gid,
        "shopify_location_gid": "gid://shopify/Location/4",
        "shopify_publication_gid": "gid://shopify/Publication/5",
        "sku": "DRP-ABC",
        "sync_state": "DRAFT",
        "synced_price_minor": quantity_price,
        "reserved_order_reference": None,
        "reserved_line_reference": None,
        "link_version": 1,
        "has_active_reservation": False,
    }


def test_two_physical_members_form_one_publishable_pool() -> None:
    catalogue_id = uuid4()
    owner_a = uuid4()
    owner_b = uuid4()
    first = _row(owner_id=owner_a, priority=1)
    second = _row(owner_id=owner_b, priority=2)
    first["catalogue_id"] = catalogue_id
    second["catalogue_id"] = catalogue_id

    group = _evaluate_pool([first, second])

    assert group["ready"] is True
    assert group["quantity"] == 2
    assert group["price_minor"] == 500
    assert group["product_gid"] == "gid://shopify/Product/1"
    assert [row["owner_id"] for row in group["rows"]] == [owner_a, owner_b]


def test_pool_fails_closed_on_shared_identity_or_reservation_drift() -> None:
    first = _row(priority=1)
    second = _row(priority=2)
    second["catalogue_id"] = first["catalogue_id"]
    second["shopify_variant_gid"] = "gid://shopify/ProductVariant/999"
    second["reserved_order_reference"] = "order-123"

    group = _evaluate_pool([first, second])

    assert group["ready"] is False
    assert "pooled links disagree on shopify_variant_gid" in group["blockers"]
    assert "Shopify link reserved" in group["blockers"]


def test_pool_fails_closed_on_price_or_priority_drift() -> None:
    first = _row(priority=1, quantity_price=500)
    second = _row(priority=3, quantity_price=650)
    second["catalogue_id"] = first["catalogue_id"]

    group = _evaluate_pool([first, second])

    assert group["ready"] is False
    assert "pool members have different store prices" in group["blockers"]
    assert "allocation priority is not contiguous" in group["blockers"]


def _snapshot(group, *, quantity=None, status="DRAFT", media=True):
    row = group["rows"][0]
    collections = [
        {"title": title}
        for title in required_collection_titles(row)
    ]
    return {
        "id": group["product_gid"],
        "status": status,
        "collections": {"nodes": collections},
        "media": {"nodes": [{"id": "gid://shopify/MediaImage/1"}] if media else []},
        "variants": {
            "nodes": [{
                "id": group["variant_gid"],
                "price": "5.00",
                "inventoryPolicy": "DENY",
                "inventoryQuantity": group["quantity"] if quantity is None else quantity,
                "inventoryItem": {
                    "id": group["inventory_item_gid"],
                    "sku": group["sku"],
                    "tracked": True,
                },
            }]
        },
    }


def test_remote_pool_verification_accepts_exact_draft_projection() -> None:
    first = _row(priority=1)
    second = _row(priority=2)
    second["catalogue_id"] = first["catalogue_id"]
    group = _evaluate_pool([first, second])

    assert _remote_blockers(group, _snapshot(group)) == []


def test_remote_pool_verification_rejects_quantity_or_media_drift() -> None:
    first = _row(priority=1)
    second = _row(priority=2)
    second["catalogue_id"] = first["catalogue_id"]
    group = _evaluate_pool([first, second])

    blockers = _remote_blockers(group, _snapshot(group, quantity=1, media=False))

    assert "remote pooled quantity mismatch" in blockers
    assert "remote image missing" in blockers


def test_publication_order_is_remote_first_db_second_with_compensation() -> None:
    source = PUBLICATION.read_text()
    start = source.index("async def _publish_one_pool(")
    end = source.index("@router.get", start)
    block = source[start:end]

    activate = block.index('status="ACTIVE"')
    publish = block.index("await client.publish_product(")
    verify_publication = block.index("await client.product_published_on_publication(")
    db_commit = block.index("await _mark_pool_published(")
    compensation = block.index('status="DRAFT"', db_commit)

    assert activate < publish < verify_publication < db_commit < compensation


def test_pooled_publication_router_is_platform_admin_wired() -> None:
    source = MAIN.read_text()
    assert "shopify_pool_publication_router" in source
    assert (
        "app.include_router(shopify_pool_publication_router, "
        "dependencies=[Depends(require_platform_admin_request)])"
    ) in source
