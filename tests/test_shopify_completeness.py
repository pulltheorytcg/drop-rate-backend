from __future__ import annotations

from app.shopify_completeness import (
    CARD_CATEGORY_GID,
    build_shopify_product_plan,
    media_completeness,
    product_completeness,
    product_create_input,
    shipping_profile_key,
    verify_remote_product,
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
    assert plan["shippingProfileKey"] == "RAW_CARD"
    assert plan["requiredCollections"] == ["Trading Cards", "Pokémon"]
    assert "Language:English" in plan["tags"]
    assert "Condition:Near Mint" in plan["tags"]


def test_sealed_product_plan_uses_sealed_storefront_contract() -> None:
    sealed = _card(
        inventory_code="INV-SEALED-1",
        catalogue_id="60d5b80e-39b9-4311-aa28-599a1d0de9b2",
        product_type="COLLECTION",
        game="One Piece",
        name="Premium Card Collection -6 assort vol.1-",
        set_name="One Piece Promotion Cards",
        card_number=None,
        language="Japanese",
        catalogue_language=None,
        condition=None,
        grading_company=None,
        grade=None,
        rarity=None,
        seal_status="SEALED",
    )

    plan = build_shopify_product_plan(sealed)

    assert plan["category"] == CARD_CATEGORY_GID
    assert plan["categoryName"] == "Non-Sports Trading Cards"
    assert plan["vendor"] == "One Piece"
    assert plan["productType"] == "Sealed TCG Product"
    assert plan["shippingProfileKey"] == "SEALED_60D5B80E39B94311AA28599A1D0DE9B2"
    assert plan["requiredCollections"] == ["Sealed", "One Piece"]
    assert plan["title"] == "Premium Card Collection -6 assort vol.1- · JP"
    assert "Sealed Product" in plan["tags"]
    assert "Variant:Normal" not in plan["tags"]
    sealed_fields = {row["key"]: row["value"] for row in plan["metafields"]}
    assert sealed_fields["language"] == "Japanese"
    assert sealed_fields["set_name"] == "One Piece Promotion Cards"
    assert sealed_fields["seal_status"] == "SEALED"
    assert "variant" not in sealed_fields
    assert "Raw Card" not in plan["tags"]
    assert "Graded Card" not in plan["tags"]
    assert "Trading Card" not in plan["tags"]
    assert "sealed TCG product" in plan["descriptionHtml"]
    assert "physical trading card" not in plan["descriptionHtml"]
    assert "sealed TCG product" in plan["seo"]["description"]
    assert shipping_profile_key(sealed) == "SEALED_60D5B80E39B94311AA28599A1D0DE9B2"


def test_sealed_shipping_profile_is_canonical_product_specific() -> None:
    premium = _card(
        catalogue_id="60d5b80e-39b9-4311-aa28-599a1d0de9b2",
        product_type="COLLECTION",
    )
    tin = _card(
        catalogue_id="ae2e4ec7-1cd4-42ec-9f36-5a65cad04bef",
        product_type="COLLECTION",
    )

    assert (
        shipping_profile_key(premium)
        == "SEALED_60D5B80E39B94311AA28599A1D0DE9B2"
    )
    assert (
        shipping_profile_key(tin)
        == "SEALED_AE2E4EC71CD442EC9F365A65CAD04BEF"
    )
    assert shipping_profile_key(premium) != shipping_profile_key(tin)


def test_sealed_shipping_profile_fails_closed_without_canonical_id() -> None:
    sealed = _card(product_type="COLLECTION", catalogue_id=None)
    assert shipping_profile_key(sealed) == "UNSUPPORTED_SEALED_PRODUCT_ID"


def test_sealed_product_fails_closed_without_real_shipping_profile() -> None:
    sealed = _card(
        inventory_code="INV-SEALED-1",
        catalogue_id="60d5b80e-39b9-4311-aa28-599a1d0de9b2",
        product_type="COLLECTION",
        game="One Piece",
        name="Premium Card Collection -6 assort vol.1-",
        set_name="One Piece Promotion Cards",
        card_number=None,
        language="Japanese",
        catalogue_language=None,
        condition=None,
        rarity=None,
    )
    plan = build_shopify_product_plan(sealed)

    result = product_completeness(
        plan,
        store_price_minor=11108,
        inventory_code="INV-SEALED-1",
        approved_media_count=1,
        existing_collection_titles={"Sealed", "One Piece"},
        publication_configured=True,
        location_configured=True,
        shipping_profile=None,
    )

    assert result["complete"] is False
    assert (
        "shipping profile: SEALED_60D5B80E39B94311AA28599A1D0DE9B2"
        in result["blockers"]
    )
    assert result["shippingProfileKey"] == "SEALED_60D5B80E39B94311AA28599A1D0DE9B2"
    assert result["shippingSpec"] is None


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


def test_description_explains_governed_item_specific_media_policy() -> None:
    plan = build_shopify_product_plan(_card())
    assert "item-specific media policy" in plan["descriptionHtml"]
    assert "Images may be representative" not in plan["descriptionHtml"]


def test_pre_release_description_discloses_reference_image_difference() -> None:
    plan = build_shopify_product_plan(
        _card(
            game="Dragon Ball Super",
            set_name="Dawn of the Z-Legends Pre-Release Cards",
            card_number="BT18-004",
            name="Omega Shenron, Merciless Negativity",
        )
    )
    assert "physical item is the Pre-Release printing" in plan["descriptionHtml"]
    assert "markings may differ from the reference image" in plan["descriptionHtml"]


def test_one_piece_promo_description_discloses_reference_image_difference() -> None:
    plan = build_shopify_product_plan(
        _card(
            game="One Piece",
            set_name="One Piece Promotion Cards",
            card_number="P-003",
            name='Eustass"Captain"Kid (Online Regional 2024 Vol. 2) [Participant]',
        )
    )
    assert "promotional/event printing" in plan["descriptionHtml"]
    assert "event markings may differ from the reference image" in plan["descriptionHtml"]


def _ready_asset(
    *,
    scope="CANONICAL_CARD",
    side="FRONT",
    file_id="gid://shopify/MediaImage/1",
    capture_context=None,
):
    if capture_context is None and scope == "INVENTORY_ITEM":
        capture_context = "GRADED_SLAB"
    return {
        "scope": scope,
        "side": side,
        "capture_context": capture_context,
        "media_kind": "IMAGE",
        "approval_status": "APPROVED",
        "rights_status": "VERIFIED",
        "rights_tier": (
            "FIRST_PARTY_CAPTURE"
            if scope == "INVENTORY_ITEM"
            else "STOREFRONT_ALLOWED"
        ),
        "source_status": "ACTIVE",
        "revoked_at": None,
        "shopify_file_status": "READY",
        "shopify_file_gid": file_id,
    }


def test_raw_card_media_can_use_approved_canonical_front() -> None:
    result = media_completeness(
        "CANONICAL_STOREFRONT_ALLOWED",
        [_ready_asset()],
    )
    assert result["complete"] is True
    assert result["blockers"] == []
    assert result["shopifyFileIds"] == ["gid://shopify/MediaImage/1"]


def test_graded_card_media_requires_item_specific_front_and_back() -> None:
    canonical_front = _ready_asset()
    missing_back = media_completeness(
        "PHYSICAL_ITEM_REQUIRED",
        [
            canonical_front,
            _ready_asset(
                scope="INVENTORY_ITEM",
                side="FRONT",
                file_id="gid://shopify/MediaImage/2",
            ),
        ],
    )
    assert missing_back["complete"] is False
    assert missing_back["blockers"] == ["approved first-party physical back image"]

    complete = media_completeness(
        "PHYSICAL_ITEM_REQUIRED",
        [
            _ready_asset(
                scope="INVENTORY_ITEM",
                side="FRONT",
                file_id="gid://shopify/MediaImage/2",
            ),
            _ready_asset(
                scope="INVENTORY_ITEM",
                side="BACK",
                file_id="gid://shopify/MediaImage/3",
            ),
        ],
    )
    assert complete["complete"] is True
    assert complete["shopifyFileIds"] == [
        "gid://shopify/MediaImage/2",
        "gid://shopify/MediaImage/3",
    ]


def test_graded_cards_require_item_specific_physical_media() -> None:
    plan = build_shopify_product_plan(
        _card(condition=None, grading_company="PSA", grade="10")
    )
    assert plan["mediaPolicy"] == "PHYSICAL_ITEM_REQUIRED"
    assert plan["shippingProfileKey"] == "GRADED_CARD"
    assert shipping_profile_key(
        _card(condition=None, grading_company="PSA", grade="10")
    ) == "GRADED_CARD"
    assert "PSA 10" in plan["title"]


def test_launch_completeness_fails_closed_for_media_and_collections() -> None:
    plan = build_shopify_product_plan(_card())
    result = product_completeness(
        plan,
        store_price_minor=499,
        inventory_code="INV-PKM-TEST-001",
        approved_media_count=0,
        existing_collection_titles={"Home page"},
        publication_configured=True,
        location_configured=True,
        shipping_profile={
            "profile_key": "RAW_CARD",
            "label": "Raw trading card",
            "weight_value": 25,
            "weight_unit": "GRAMS",
            "shipping_package_gid": None,
            "active": True,
        },
    )
    assert result["complete"] is False
    assert "approved media" in result["blockers"]
    assert "collection: Trading Cards" in result["blockers"]
    assert "collection: Pokémon" in result["blockers"]


def test_launch_completeness_fails_closed_without_shipping_profile() -> None:
    plan = build_shopify_product_plan(_card())
    result = product_completeness(
        plan,
        store_price_minor=499,
        inventory_code="INV-PKM-TEST-001",
        approved_media_count=1,
        existing_collection_titles={"Trading Cards", "Pokémon"},
        publication_configured=True,
        location_configured=True,
        shipping_profile=None,
    )
    assert result["complete"] is False
    assert "shipping profile: RAW_CARD" in result["blockers"]
    assert result["shippingProfileKey"] == "RAW_CARD"
    assert result["shippingSpec"] is None


def test_launch_completeness_passes_when_every_required_surface_is_ready() -> None:
    plan = build_shopify_product_plan(_card())
    result = product_completeness(
        plan,
        store_price_minor=499,
        inventory_code="INV-PKM-TEST-001",
        approved_media_count=1,
        existing_collection_titles={"Home page", "Trading Cards", "Pokémon"},
        publication_configured=True,
        location_configured=True,
        shipping_profile={
            "profile_key": "RAW_CARD",
            "label": "Raw trading card",
            "weight_value": 25,
            "weight_unit": "GRAMS",
            "shipping_package_gid": None,
            "active": True,
        },
    )
    assert result["complete"] is True
    assert result["blockers"] == []


def test_remote_product_verification_checks_every_launch_surface() -> None:
    plan = build_shopify_product_plan(_card())
    expected_metafields = {
        row["key"]: row["value"]
        for row in plan["metafields"]
    }
    snapshot = {
        "title": plan["title"],
        "descriptionHtml": plan["descriptionHtml"],
        "status": "ACTIVE",
        "vendor": plan["vendor"],
        "productType": plan["productType"],
        "tags": plan["tags"],
        "templateSuffix": None,
        "seo": plan["seo"],
        "category": {"id": plan["category"]},
        "metafields": {
            "nodes": [
                {
                    "key": key,
                    "value": value,
                    "type": "single_line_text_field",
                }
                for key, value in expected_metafields.items()
            ]
        },
        "collections": {
            "nodes": [
                {"id": "gid://shopify/Collection/1", "title": "Trading Cards"},
                {"id": "gid://shopify/Collection/2", "title": "Pokémon"},
            ]
        },
        "media": {
            "nodes": [{"id": "gid://shopify/MediaImage/1"}]
        },
        "variants": {
            "nodes": [{
                "id": "gid://shopify/ProductVariant/1",
                "price": "4.99",
                "inventoryPolicy": "DENY",
                "inventoryQuantity": 1,
                "inventoryItem": {
                    "id": "gid://shopify/InventoryItem/1",
                    "sku": "INV-PKM-TEST-001",
                    "tracked": True,
                    "requiresShipping": True,
                    "measurement": {
                        "weight": {"value": 25.0, "unit": "GRAMS"}
                    },
                },
            }]
        },
    }
    result = verify_remote_product(
        plan,
        snapshot,
        expected_price="4.99",
        expected_sku="INV-PKM-TEST-001",
        expected_collection_titles={"Trading Cards", "Pokémon"},
        expected_media_file_ids={"gid://shopify/MediaImage/1"},
        expected_quantity=1,
        expected_status="ACTIVE",
        expected_shipping_spec={
            "weight": {"value": 25.0, "unit": "GRAMS"},
        },
    )
    assert result == {"complete": True, "blockers": []}

    snapshot["variants"]["nodes"][0]["inventoryQuantity"] = 0
    broken = verify_remote_product(
        plan,
        snapshot,
        expected_price="4.99",
        expected_sku="INV-PKM-TEST-001",
        expected_collection_titles={"Trading Cards", "Pokémon"},
        expected_media_file_ids={"gid://shopify/MediaImage/1"},
        expected_quantity=1,
        expected_status="ACTIVE",
        expected_shipping_spec={
            "weight": {"value": 25.0, "unit": "GRAMS"},
        },
    )
    assert broken["complete"] is False
    assert "remote inventory quantity" in broken["blockers"]


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
