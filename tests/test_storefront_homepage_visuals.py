from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "storefront" / "theme" / "sections"


def _read(name: str) -> str:
    return (THEME / name).read_text()


def test_homepage_custom_sections_are_source_controlled() -> None:
    for name in (
        "dr-brand-hero.liquid",
        "dr-brand-discovery.liquid",
        "dr-brand-editorial.liquid",
        "dr-brand-sets.liquid",
    ):
        assert (THEME / name).exists()


def test_homepage_uses_current_drop_rate_visual_palette() -> None:
    source = "\n".join(
        _read(name)
        for name in (
            "dr-brand-hero.liquid",
            "dr-brand-discovery.liquid",
            "dr-brand-editorial.liquid",
            "dr-brand-sets.liquid",
        )
    ).casefold()

    for stale in ("#ffd044", "#ffdc70", "#007c89", "#e6ac1d"):
        assert stale not in source

    for current in ("#1f7bf2", "#28d7eb", "#071b3f", "#f4f7fb"):
        assert current in source


def test_homepage_discovery_search_remains_shopify_native() -> None:
    source = _read("dr-brand-discovery.liquid")

    assert 'action="{{ routes.search_url }}"' in source
    assert 'method="get"' in source
    assert 'name="q"' in source
    assert 'name="type" value="product"' in source
    assert 'name="options[prefix]" value="last"' in source
    assert "/api/v1/" not in source
    assert "supabase" not in source.casefold()


def test_homepage_merchandising_links_and_settings_are_preserved() -> None:
    hero = _read("dr-brand-hero.liquid")
    discovery = _read("dr-brand-discovery.liquid")
    editorial = _read("dr-brand-editorial.liquid")
    sets = _read("dr-brand-sets.liquid")

    assert "section.settings.featured_product" in hero
    assert "section.settings.left_product" in hero
    assert "section.settings.right_product" in hero
    assert "collections['graded-cards'].url" in hero

    assert "block.settings.collection" in discovery
    assert "block.settings.product" in discovery
    assert 'href="{{ c.url }}"' in discovery

    assert "section.settings.product" in editorial
    assert 'href="{{ section.settings.link }}"' in editorial
    assert "featured.url" in editorial

    assert "block.settings.collection" in sets
    assert 'href="{{ c.url }}"' in sets
    assert "pages['contact'].url" in sets
