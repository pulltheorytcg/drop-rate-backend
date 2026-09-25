from __future__ import annotations

from app.shopify_completeness import (
    CARD_CATEGORY_GID,
    build_shopify_product_plan,
    product_completeness,
    product_create_input,
)


def _card(**overrides):
    item = {
        "inventory_code": "INV-PKM-TEST-001",
        "product_type": "CARD",
        "game": "Pokemon",
        "name": "Seel",
        "set_name": "Phantasmal Flames",
        "card_number": "021/094",
        "variant": "Normal",
        "rarity": "Common",
        "language": "English",
        "catalogue_language": "English",
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
    }
    item.update(overrides)
    return item


def test_card_product_plan_fills_customer_and_merchant_fields() -> None:
    plan = build_shopify_product_plan(_card())
    assert plan["title"] == "Seel · EN · 021/094 · Phantasmal Flames · Normal · Near Mint"
    assert plan["category"] == CARD_CATEGORY_GID
    assert plan["categoryName"] == "Non-Sports Trading Cards"
    assert plan["vendor"] == "Pokémon"
    assert plan["productType"] == "Trading Card"
    assert plan["seo"]["title"]
    assert plan["seo"]["description"]
    assert len(plan["seo"]["title"]) <= 70
    assert len(plan["seo"]["description"]) <= 320
    assert plan["template"] == "default"
    assert plan["requiresShipping"] is True
    assert plan["inventoryTracked"] is True
    assert plan["inventoryPolicy"] == "DENY"
    assert plan["requiredCollections"] == ["Trading Cards", "Pokémon"]
    assert "Language:English" in plan["tags"]
    assert "Condition:Near Mint" in plan["tags"]


def test_product_metafields_are_listing_facts_not_private_finance_or_owner_data() -> None:
    plan = build_shopify_product_plan(_card())
    fields = {row["key"]: row["value"] for row in plan["metafields"]}
    assert fields["inventory_id"] == "INV-PKM-TEST-001"
    assert fields["language"] == "English"
    assert fields["condition"] == "Near Mint"
    assert fields["set_name"] == "Phantasmal Flames"
    assert "owner" not in fields
    assert "owner_id" not in fields
    assert "acquisition_cost" not in fields
    assert "cost" not in fields


def test_description_does_not_claim_item_specific_media() -> None:
    plan = build_shopify_product_plan(_card())
    assert "Images may be representative" in plan["descriptionHtml"]
    assert "exact card pictured" not in plan["descriptionHtml"].casefold()


def test_graded_cards_require_item_specific_physical_media() -> None:
    plan = build_shopify_product_plan(
        _card(condition=None, grading_company="PSA", grade="10")
    )
    assert plan["mediaPolicy"] == "PHYSICAL_ITEM_REQUIRED"
    assert "PSA 10" in plan["title"]


def test_launch_completeness_fails_closed_for_media_and_collections() -> None:
    plan = build_shopify_product_plan(_card())
    result = product_completeness(
        plan,
        store_price_minor=499,
        inventory_code="INV-PKM-TEST-001",
        media_readiness={
            "complete": False,
            "blockers": ["approved front media"],
            "approvedMediaCount": 0,
        },
        existing_collection_titles={"Home page"},
        publication_configured=True,
        location_configured=True,
    )
    assert result["complete"] is False
    assert "approved front media" in result["blockers"]
    assert "collection: Trading Cards" in result["blockers"]
    assert "collection: Pokémon" in result["blockers"]


def test_launch_completeness_passes_when_every_required_surface_is_ready() -> None:
    plan = build_shopify_product_plan(_card())
    result = product_completeness(
        plan,
        store_price_minor=499,
        inventory_code="INV-PKM-TEST-001",
        media_readiness={
            "complete": True,
            "blockers": [],
            "approvedMediaCount": 1,
        },
        existing_collection_titles={"Home page", "Trading Cards", "Pokémon"},
        publication_configured=True,
        location_configured=True,
    )
    assert result["complete"] is True
    assert result["blockers"] == []


def test_product_create_input_contains_complete_deterministic_shopify_fields() -> None:
    plan = build_shopify_product_plan(_card())
    payload = product_create_input(plan, handle="drop-rate-inv-pkm-test-001")
    assert payload["title"] == plan["title"]
    assert payload["descriptionHtml"] == plan["descriptionHtml"]
    assert payload["category"] == CARD_CATEGORY_GID
    assert payload["seo"] == plan["seo"]
    assert payload["vendor"] == "Pokémon"
    assert payload["productType"] == "Trading Card"
    assert payload["tags"] == plan["tags"]
    assert payload["metafields"] == plan["metafields"]
    assert payload["status"] == "DRAFT"
    # Shopify's default template is represented by omitting templateSuffix.
    assert "templateSuffix" not in payload
