from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "storefront" / "theme" / "snippets" / "dr-brand-system.liquid"


def test_active_brand_system_uses_current_drop_rate_tokens() -> None:
    source = BRAND.read_text().casefold()

    for value in ("#071b3f", "#13223b", "#1f7bf2", "#28d7eb", "#f4f7fb", "#e2e8f0"):
        assert value in source

    for stale in ("#ffd044", "#007c89", "#fffdf8", "#f5f1e8", "#f2b940"):
        assert stale not in source


def test_brand_system_does_not_override_component_specific_new_styles() -> None:
    source = BRAND.read_text()

    # These are owned by drop-rate-global-styles and must not be flattened here.
    assert ".dr-pdp-summary" not in source
    assert ".dr-pdp-facts" not in source
    assert ".dr-purchase-note" not in source
    assert ".dr-copy-selector" not in source
    assert "div.facets-block-wrapper--vertical" not in source
    assert ".product-grid .product-card" not in source


def test_brand_system_keeps_one_copy_product_card_controls_simple() -> None:
    source = BRAND.read_text()

    assert ".product-card quantity-selector-component" in source
    assert "display: none;" in source
    assert ".product-card .add-to-cart-button" in source
    assert "background: var(--dr-blue);" in source
