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


def test_cart_keeps_drop_rate_physical_copy_quantity_locked() -> None:
    source = (THEME / "snippets" / "cart-products.liquid").read_text()

    assert "metafields.drop_rate.inventory_id.value" in source
    assert "{% if dr_inventory != blank %}" in source
    assert "{% assign can_update_quantity = false %}" in source
    assert "variant: item.variant" in source
    assert "in_cart_quantity: item.quantity" in source
    assert "dr_brand.cart.one_physical_copy" in source


def test_cart_uses_native_shopify_form_and_checkout() -> None:
    products = (THEME / "snippets" / "cart-products.liquid").read_text()
    summary = (THEME / "snippets" / "cart-summary.liquid").read_text()

    assert 'action="{{ routes.cart_url }}"' in products
    assert 'method="post"' in products
    assert 'id="cart-form"' in products

    assert 'type="submit"' in summary
    assert 'name="checkout"' in summary
    assert 'form="cart-form"' in summary
    assert "{{ content_for_additional_checkout_buttons }}" in summary

    # Cart/checkout must stay Shopify-native: never post ownership or settlement data
    # from Liquid and never route checkout through a custom Drop Rate endpoint.
    forbidden = (
        "owner_id",
        "consignor_id",
        "acquisition_cost",
        "/api/v1/orders",
        "/api/v1/settlements",
    )
    combined = (products + summary).casefold()
    for value in forbidden:
        assert value.casefold() not in combined


def test_cart_surfaces_exact_copy_customer_metadata() -> None:
    source = (THEME / "snippets" / "cart-products.liquid").read_text()

    for key in (
        "card_number",
        "set_name",
        "language",
        "condition",
        "grading_company",
        "grade",
    ):
        assert f"metafields.drop_rate.{key}.value" in source

    assert "item.url" in source
    assert "item.image" in source


def test_cart_drawer_reuses_same_exact_copy_contract() -> None:
    source = (THEME / "snippets" / "cart-drawer.liquid").read_text()

    assert "{% render 'cart-products', context: 'drawer' %}" in source
    assert "{% render 'cart-summary', section_id: 'cart-drawer-section' %}" in source


def test_cart_template_is_shopify_native_main_cart() -> None:
    template = _json_with_comment(THEME / "templates" / "cart.json")

    cart = template["sections"]["cart-section"]
    assert cart["type"] == "main-cart"
    assert cart["blocks"]["cart-page-items"]["type"] == "_cart-products"
    assert cart["blocks"]["cart-page-summary"]["type"] == "_cart-summary"
