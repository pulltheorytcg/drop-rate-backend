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


def test_pdp_uses_current_drop_rate_visual_palette() -> None:
    source = (THEME / "snippets" / "drop-rate-global-styles.liquid").read_text()

    assert ".dr-pdp-heading" in source
    assert ".dr-pdp-summary" in source
    assert "border: 1px solid #e2e8f0;" in source
    assert "background: #ffffff;" in source
    assert "color: #1f7bf2;" in source
    assert "#f5f1e8" not in source
    assert "#fffdf8" not in source
    assert "#fff1c9" not in source


def test_grouped_copy_selected_state_remains_visually_explicit() -> None:
    source = (THEME / "snippets" / "drop-rate-global-styles.liquid").read_text()

    assert ".dr-copy-option--current" in source
    assert "border-color: #1f7bf2;" in source
    assert "background: #eef5ff;" in source
    assert ".dr-copy-option__action" in source


def test_pdp_primary_add_to_cart_uses_current_blue_cta_without_changing_buy_block() -> None:
    product = _json_with_comment(THEME / "templates" / "product.json")

    details = product["sections"]["main"]["blocks"]["product-details"]["blocks"]
    buy = details["buy_buttons_eYQEYi"]
    add = buy["blocks"]["add-to-cart"]["settings"]

    assert add["style_class"] == "button"
    assert add["custom_button_background"] == "#1F7BF2"
    assert add["custom_button_text"] == "#FFFFFF"
    assert add["custom_button_border"] == "#1F7BF2"
    assert "accelerated-checkout" in buy["blocks"]
    assert "drop_rate_copy_selector" in details
