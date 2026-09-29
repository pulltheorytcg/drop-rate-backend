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


def test_active_theme_settings_use_current_drop_rate_palette_and_logo() -> None:
    data = _json_with_comment(THEME / "config" / "settings_data.json")
    current = data["current"]

    assert current["logo"] == "shopify://shop_images/drop-rate-brand-logo.png"
    assert current["logo_height"] == 70
    assert current["logo_height_mobile"] == 52
    assert current["badge_sold_out_background_color"] == "#F4F7FB"
    assert current["palette_primary_button_background"] == "#071B3F"
    assert current["palette_primary_button_border"] == "#071B3F"
    assert current["palette_primary_button_text"] == "#FFFFFF"
    assert current["palette_input_text"] == "#13223B"
    assert current["palette_selected_variant_background"] == "#071B3F"
    assert current["color_palette"] == {
        "background": "#FFFFFF",
        "foreground": "#13223B",
        "color1": "#1F7BF2",
        "color2": "#E2E8F0",
    }


def test_header_brand_alignment_preserves_navigation_and_announcement_copy() -> None:
    data = _json_with_comment(THEME / "sections" / "header-group.json")
    announcement = data["sections"]["header_announcements_9jGBFp"]
    header = data["sections"]["header_section"]

    assert announcement["settings"]["background_color"] == "#071B3F"
    assert announcement["settings"]["divider_color"] == "#071B3F"
    assert (
        announcement["blocks"]["announcement_BxgCk9"]["settings"]["text"]
        == "UK stock · Pokémon & One Piece · Find your next great drop"
    )
    assert header["blocks"]["header-menu"]["settings"]["menu"] == "main-menu"
    assert header["settings"]["logo_position"] == "left"
    assert header["settings"]["show_search"] is True


def test_footer_uses_current_drop_rate_surfaces_without_changing_copy() -> None:
    data = _json_with_comment(THEME / "sections" / "footer-group.json")
    footer = data["sections"]["footer_m9NzUG"]
    utilities = data["sections"]["footer_utilities_jLGE8U"]

    assert footer["settings"]["background_color"] == "#F4F7FB"
    assert footer["blocks"]["email_signup_crihX7"]["settings"]["input_background_color"] == "#FFFFFF"
    assert footer["blocks"]["email_signup_crihX7"]["settings"]["input_text_color"] == "#13223B"
    assert footer["blocks"]["email_signup_crihX7"]["settings"]["input_border_color"] == "#E2E8F0"
    assert utilities["settings"]["divider_color"] == "#E2E8F0"
    assert utilities["settings"]["background_color"] == "#F4F7FB"
    assert (
        footer["blocks"]["group_H6VpwJ"]["blocks"]["text_LWt8Pz"]["settings"]["text"]
        == "<h2>Stay close to the next drop</h2>"
    )
