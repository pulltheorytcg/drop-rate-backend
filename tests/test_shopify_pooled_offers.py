from __future__ import annotations

from uuid import uuid4

from app.shopify_pooled_offers import build_shopify_offer_plan


def _row(
    *,
    inventory_id=None,
    catalogue_id=None,
    inventory_code=None,
    product_type="CARD",
    language="English",
    catalogue_language=None,
    condition="Near Mint",
    grading_company=None,
    grade=None,
    seal_status=None,
    certificate_number=None,
    price=500,
    sync_state="DRAFT",
    linked_at="2026-09-29T10:00:00+00:00",
    product_gid=None,
    variant_gid=None,
    inventory_item_gid=None,
):
    inventory_id = inventory_id or uuid4()
    catalogue_id = catalogue_id or uuid4()
    suffix = str(inventory_id).replace("-", "")[:10]
    return {
        "inventory_id": inventory_id,
        "inventory_code": inventory_code or f"INV-{suffix.upper()}",
        "catalogue_id": catalogue_id,
        "product_type": product_type,
        "language": language,
        "catalogue_language": catalogue_language,
        "condition": condition,
        "grading_company": grading_company,
        "grade": grade,
        "seal_status": seal_status,
        "certificate_number": certificate_number,
        "store_price_minor": price,
        "owner_id": uuid4(),
        "shop_domain": "example.myshopify.com",
        "shopify_product_gid": product_gid or f"gid://shopify/Product/{int(suffix[:6], 16)}",
        "shopify_variant_gid": variant_gid or f"gid://shopify/ProductVariant/{int(suffix[:6], 16)}",
        "shopify_inventory_item_gid": inventory_item_gid or f"gid://shopify/InventoryItem/{int(suffix[:6], 16)}",
        "shopify_location_gid": "gid://shopify/Location/1",
        "sync_state": sync_state,
        "linked_at": linked_at,
        "allocation_priority": 1,
    }


def test_identical_raw_cards_become_one_quantity_offer() -> None:
    catalogue_id = uuid4()
    first = _row(catalogue_id=catalogue_id, inventory_code="INV-A", price=750)
    second = _row(
        catalogue_id=catalogue_id,
        inventory_code="INV-B",
        price=750,
        linked_at="2026-09-29T11:00:00+00:00",
    )

    plan = build_shopify_offer_plan([first, second])

    assert plan["offer_count"] == 1
    assert plan["pooled_offer_count"] == 1
    assert plan["ready_offer_count"] == 1
    offer = plan["offers"][0]
    assert offer["pooling_mode"] == "POOLED"
    assert offer["quantity"] == 2
    assert offer["store_price_minor"] == 750
    assert [m["allocation_priority"] for m in offer["members"]] == [1, 2]
    assert len(offer["retire_product_gids"]) == 1
    assert offer["sku"].startswith("DR-")


def test_raw_language_and_condition_split_into_distinct_offers() -> None:
    catalogue_id = uuid4()
    rows = [
        _row(catalogue_id=catalogue_id, language="English", condition="Near Mint"),
        _row(catalogue_id=catalogue_id, language="Japanese", condition="Near Mint"),
        _row(catalogue_id=catalogue_id, language="English", condition="Lightly Played"),
    ]

    plan = build_shopify_offer_plan(rows)

    assert plan["offer_count"] == 3
    labels = {
        (offer["language"], offer["condition"])
        for offer in plan["offers"]
    }
    assert labels == {
        ("English", "Near Mint"),
        ("Japanese", "Near Mint"),
        ("English", "Lightly Played"),
    }


def test_graded_cards_remain_exact_unique_offers() -> None:
    catalogue_id = uuid4()
    rows = [
        _row(
            catalogue_id=catalogue_id,
            grading_company="PSA",
            grade="10",
            certificate_number="111",
        ),
        _row(
            catalogue_id=catalogue_id,
            grading_company="PSA",
            grade="10",
            certificate_number="222",
        ),
    ]

    plan = build_shopify_offer_plan(rows)

    assert plan["offer_count"] == 2
    assert plan["unique_offer_count"] == 2
    assert all(offer["quantity"] == 1 for offer in plan["offers"])
    assert all(offer["pooling_mode"] == "UNIQUE" for offer in plan["offers"])


def test_missing_raw_language_fails_closed() -> None:
    row = _row(language=None, catalogue_language=None)

    plan = build_shopify_offer_plan([row])

    assert plan["offer_count"] == 0
    assert plan["preblocked_units"] == 1
    assert plan["preblocked"][0]["code"] == "INVALID_OFFER_SHAPE"
    assert "language" in plan["preblocked"][0]["detail"].casefold()


def test_mixed_prices_require_explicit_shared_price() -> None:
    catalogue_id = uuid4()
    rows = [
        _row(catalogue_id=catalogue_id, price=500),
        _row(catalogue_id=catalogue_id, price=650),
    ]

    plan = build_shopify_offer_plan(rows)

    offer = plan["offers"][0]
    assert offer["ready"] is False
    assert offer["store_price_minor"] is None
    assert {b["code"] for b in offer["blockers"]} == {"MIXED_MEMBER_PRICES"}


def test_existing_published_product_wins_anchor_over_older_draft() -> None:
    catalogue_id = uuid4()
    draft = _row(
        catalogue_id=catalogue_id,
        sync_state="DRAFT",
        linked_at="2026-09-20T10:00:00+00:00",
        product_gid="gid://shopify/Product/10",
        variant_gid="gid://shopify/ProductVariant/10",
        inventory_item_gid="gid://shopify/InventoryItem/10",
    )
    published = _row(
        catalogue_id=catalogue_id,
        sync_state="PUBLISHED",
        linked_at="2026-09-29T10:00:00+00:00",
        product_gid="gid://shopify/Product/20",
        variant_gid="gid://shopify/ProductVariant/20",
        inventory_item_gid="gid://shopify/InventoryItem/20",
    )

    plan = build_shopify_offer_plan([draft, published])

    offer = plan["offers"][0]
    assert offer["target"]["shopify_product_gid"] == "gid://shopify/Product/20"
    assert offer["target"]["shopify_variant_gid"] == "gid://shopify/ProductVariant/20"
    assert offer["retire_product_gids"] == ["gid://shopify/Product/10"]


def test_unique_offer_collision_is_blocked() -> None:
    inventory_id = uuid4()
    catalogue_id = uuid4()
    first = _row(
        inventory_id=inventory_id,
        catalogue_id=catalogue_id,
        grading_company="PSA",
        grade="10",
    )
    second = dict(first)
    second["inventory_code"] = "INV-DUPLICATE-LINK"
    second["shopify_product_gid"] = "gid://shopify/Product/999"

    plan = build_shopify_offer_plan([first, second])

    assert plan["blocked_offer_count"] == 1
    assert {
        blocker["code"]
        for blocker in plan["offers"][0]["blockers"]
    } == {"UNIQUE_OFFER_COLLISION"}
