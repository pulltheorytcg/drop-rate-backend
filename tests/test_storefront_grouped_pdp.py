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


def test_product_template_places_copy_selector_before_purchase() -> None:
    template = _json_with_comment(THEME / "templates" / "product.json")
    details = template["sections"]["main"]["blocks"]["product-details"]
    order = details["block_order"]

    assert details["blocks"]["drop_rate_copy_selector"]["type"] == "dr-copy-selector"
    assert order.index("drop_rate_copy_selector") < order.index("buy_buttons_eYQEYi")


def test_copy_selector_filters_unavailable_products_and_never_exposes_owner_data() -> None:
    source = (THEME / "blocks" / "dr-copy-selector.liquid").read_text()

    assert "metafields.drop_rate.copy_handles.value" in source
    assert "all_products[copy_handle]" in source
    assert "copy_product.available" in source
    assert "aria-current" in source
    assert "copy_product.price | money" in source
    assert "acquisition" not in source.casefold()
    assert "owner_id" not in source.casefold()
    assert "consignor" not in source.casefold()


def test_copy_selector_translation_keys_exist() -> None:
    locale = _json_with_comment(THEME / "locales" / "en.default.json")
    product = locale["dr_brand"]["product"]

    for key in (
        "choose_copy",
        "copies_available",
        "from_price",
        "selected_copy",
        "view_copy",
        "more_copies_note",
    ):
        assert product[key]


def test_copy_selector_has_mobile_styles() -> None:
    styles = (THEME / "snippets" / "drop-rate-global-styles.liquid").read_text()

    assert "/* .dr-copy-selector-marker */" in styles
    assert ".dr-copy-option--current" in styles
    assert "@media screen and (max-width: 749px)" in styles
