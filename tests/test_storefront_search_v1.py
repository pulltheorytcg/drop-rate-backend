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


def test_search_v1_is_product_only_and_partial_match_friendly() -> None:
    source = (THEME / "blocks" / "_search-input.liquid").read_text()

    assert 'name="type"' in source
    assert 'value="product"' in source
    assert 'name="options[prefix]"' in source
    assert 'value="last"' in source
    assert 'name="options[unavailable_products]"' in source


def test_search_v1_uses_tcg_specific_copy() -> None:
    source = (THEME / "blocks" / "_search-input.liquid").read_text()
    locale = _json_with_comment(THEME / "locales" / "en.default.json")

    assert "dr_brand.search.placeholder" in source
    assert "dr_brand.search.help" in source
    assert locale["dr_brand"]["search"]["placeholder"] == "Search a card, set or collector number…"
    assert locale["dr_brand"]["search"]["help"] == "Search by card name or collector number."


def test_search_v1_has_no_custom_backend_dependency() -> None:
    source = (THEME / "blocks" / "_search-input.liquid").read_text().casefold()

    assert 'action="{{ routes.search_url }}"' in source
    assert "/api/v1/" not in source
    assert "fetch(" not in source
    assert "supabase" not in source
