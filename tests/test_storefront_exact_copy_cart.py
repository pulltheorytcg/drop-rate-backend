from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "storefront" / "theme"


def _json_with_comment(path: Path) -> dict:
    text = path.read_text()
    end = text.find("*/")
    start = text.find("{", end + 2 if end >= 0 else 0)
    return json.loads(text[start:])


def test_drop_rate_cart_locks_physical_copy_quantity() -> None:
    source = (THEME / "snippets" / "cart-products.liquid").read_text()

    assert "metafields.drop_rate.inventory_id.value" in source
    assert "assign can_update_quantity = false" in source
    assert "wrapper_class: dr_quantity_wrapper" in source
    assert "dr-cart-fixed-quantity" in source
    assert "dr_brand.cart.one_physical_copy" in source


def test_drop_rate_cart_keeps_remove_control_and_native_cart_form() -> None:
    source = (THEME / "snippets" / "cart-products.liquid").read_text()

    assert 'action="{{ routes.cart_url }}"' in source
    assert "on:click="/onLineItemRemove/" in source
    assert "render 'quantity-selector'" in source
    assert "updates[]" not in source  # quantity field remains encapsulated in Shopify snippet


def test_drop_rate_cart_shows_customer_safe_copy_metadata_only() -> None:
    source = (THEME / "snippets" / "cart-products.liquid").read_text().casefold()

    assert "drop_rate.card_number" in source
    assert "drop_rate.set_name" in source
    assert "drop_rate.language" in source
    assert "drop_rate.condition" in source
    assert "drop_rate.grading_company" in source
    assert "drop_rate.grade" in source
    assert "acquisition_cost" not in source
    assert "owner_id" not in source
    assert "consignor" not in source


def test_exact_copy_cart_translation_exists() -> None:
    locale = _json_with_comment(THEME / "locales" / "en.default.json")
    assert locale["dr_brand"]["cart"]["one_physical_copy"] == "1 physical copy"
