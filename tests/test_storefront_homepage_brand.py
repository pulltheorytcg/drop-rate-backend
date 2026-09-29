from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "storefront" / "theme"
SECTIONS = THEME / "sections"


def _json_with_comment(path: Path) -> dict:
    text = path.read_text()
    end = text.find("*/")
    start = text.find("{", end + 2 if end >= 0 else 0)
    return json.loads(text[start:])


def test_homepage_custom_sections_are_source_controlled() -> None:
    for name in (
        "dr-brand-hero.liquid",
        "dr-brand-discovery.liquid",
        "dr-brand-editorial.liquid",
        "dr-brand-sets.liquid",
    ):
        path = SECTIONS / name
        assert path.exists()
        source = path.read_text()
        assert "{% schema %}" in source
        assert "{% stylesheet %}" in source


def test_homepage_uses_current_drop_rate_palette_without_old_yellow_teal() -> None:
    source = "\n".join(
        (SECTIONS / name).read_text()
        for name in (
            "dr-brand-hero.liquid",
            "dr-brand-discovery.liquid",
            "dr-brand-editorial.liquid",
            "dr-brand-sets.liquid",
        )
    ).lower()

    for forbidden in (
        "#ffd044",
        "#ffdc70",
        "#007c89",
        "#e6ac1d",
        "#45dce0",
        "#f4f7f7",
    ):
        assert forbidden not in source

    assert "#071b3f" in source
    assert "#1f7bf2" in source
    assert "#28d7eb" in source
    assert "#f4f7fb" in source
    assert "#eafcff" in source


def test_homepage_template_still_uses_same_custom_section_contract() -> None:
    template = _json_with_comment(THEME / "templates" / "index.json")
    section_types = {section["type"] for section in template["sections"].values()}

    assert "dr-brand-hero" in section_types
    assert "dr-brand-discovery" in section_types
    assert "dr-brand-editorial" in section_types
    assert "dr-brand-sets" in section_types
