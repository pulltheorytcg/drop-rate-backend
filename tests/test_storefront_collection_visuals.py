from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "storefront" / "theme"


def test_collection_hero_uses_current_drop_rate_navy_cyan_palette() -> None:
    source = (THEME / "sections" / "dr-brand-collection.liquid").read_text()

    assert "#061733" in source
    assert "#08234d" in source
    assert "#28d7eb" in source
    assert "#55dfea" in source
    assert "#8ef0fa" in source
    assert "#fffdf8" not in source
    assert "#f5f1e8" not in source


def test_collection_browse_keeps_empty_sealed_lane_hidden() -> None:
    source = (THEME / "sections" / "drop-rate-collection-routes.liquid").read_text()

    assert "assign all_sealed = collections['sealed']" in source
    assert "all_sealed.all_products_count > 0" in source
    assert "dr_brand.browse.sealed" in source


def test_collection_cards_and_facets_use_app_aligned_surfaces() -> None:
    source = (THEME / "snippets" / "drop-rate-global-styles.liquid").read_text()

    assert ".product-grid .product-card" in source
    assert "background: #ffffff;" in source
    assert "border-color: #e2e8f0;" in source
    assert ".dr-card-copy__game" in source
    assert "color: #1f7bf2;" in source
    assert "div.facets-block-wrapper--vertical" in source
    assert "color: #071b3f;" in source
