from app.shopify_catalogue_bootstrap import (
    _handle,
    _media_filename,
    build_catalogue_product_input,
)


def _item(**overrides):
    item = {
        "inventory_code": "INV-ABC123",
        "acquisition_cost_minor": 187,
        "store_price_minor": 499,
        "product_type": "CARD",
        "game": "Pokemon",
        "name": "Pikachu",
        "set_name": "Test Set",
        "card_number": "001/100",
        "variant": "Holofoil",
        "rarity": "Rare",
        "language": "English",
        "catalogue_language": "English",
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
        "shopify_file_gid": None,
        "shopify_file_status": "NOT_UPLOADED",
        "public_source_url": "https://example.test/cards/pikachu.webp?cache=1",
        "alt_text": "Pikachu reference image",
    }
    item.update(overrides)
    return item


def test_bootstrap_product_input_is_draft_and_inventory_tracked():
    payload = build_catalogue_product_input(
        _item(),
        location_id="gid://shopify/Location/1",
        physical_photo_threshold_minor=5_000,
    )

    assert payload["status"] == "DRAFT"
    assert payload["handle"] == "drop-rate-inv-abc123"
    assert payload["files"][0]["originalSource"].startswith("https://example.test/")
    assert payload["files"][0]["filename"] == "INV-ABC123.webp"

    variant = payload["variants"][0]
    assert variant["price"] == "4.99"
    assert variant["inventoryPolicy"] == "DENY"
    assert variant["inventoryItem"]["tracked"] is True
    assert variant["inventoryItem"]["cost"] == "1.87"
    assert variant["inventoryQuantities"] == [{
        "locationId": "gid://shopify/Location/1",
        "name": "on_hand",
        "quantity": 1,
    }]


def test_bootstrap_product_input_marks_missing_price_action_required():
    payload = build_catalogue_product_input(
        _item(store_price_minor=None),
        location_id="gid://shopify/Location/1",
        physical_photo_threshold_minor=5_000,
    )

    assert payload["variants"][0]["price"] == "0.00"
    assert "Action Required:Pricing" in payload["tags"]
    assert payload["status"] == "DRAFT"


def test_bootstrap_reuses_ready_shopify_file():
    payload = build_catalogue_product_input(
        _item(
            shopify_file_gid="gid://shopify/MediaImage/123",
            shopify_file_status="READY",
        ),
        location_id="gid://shopify/Location/1",
        physical_photo_threshold_minor=5_000,
    )

    assert payload["files"] == [{"id": "gid://shopify/MediaImage/123"}]


def test_bootstrap_helpers_are_deterministic():
    assert _handle("INV-ABC_123") == "drop-rate-inv-abc-123"
    assert _media_filename(_item()) == "INV-ABC123.webp"
