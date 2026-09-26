from pathlib import Path


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "backend" / "app" / "static"
INDEX = STATIC / "index.html"
SHELL = STATIC / "dashboard-shell.js"
STYLES = STATIC / "styles.css"


def test_drop_rate_brand_shell_uses_real_visual_identity_not_generic_dr_tile() -> None:
    html = INDEX.read_text()

    assert "brand-lockup-logo" in html
    assert "dr-logo" in html
    assert "dr-wordmark" in html
    assert "<svg" in html
    assert "FOUNDER HQ" in html
    assert "styles.css?v=anime-founder-v2" in html
    assert '<span class="brand-mark">DR</span>' not in html


def test_founder_dashboard_has_new_command_centre_and_simplified_inventory_flow() -> None:
    js = SHELL.read_text()

    assert "function buildFounderHero()" in js
    assert "Drop Rate command centre" in js
    assert "Chase the next hit." in js
    assert "dashboard-overview-grid" in js
    assert "function utilityDrawer(" in js
    assert 'utilityDrawer("Storage locations"' in js
    assert 'utilityDrawer("Purchase lots"' in js
    assert "inventory.append(inventoryPanel)" in js


def test_navigation_has_gaming_icons_without_changing_route_keys() -> None:
    js = SHELL.read_text()

    for key in ("dashboard", "inventory", "verification", "media", "sales", "reports", "balance", "settings"):
        assert f'["{key}",' in js
    assert "seller-nav-icon" in js
    assert "data-hero-view" in js


def test_anime_tcg_visual_system_is_brand_coloured_and_responsive() -> None:
    css = STYLES.read_text()

    assert "DROP RATE FOUNDER UI — Anime / TCG visual system v2" in css
    for token in (
        "--dr-navy:#071b3f",
        "--dr-cyan:#22dff2",
        "--dr-gold:#ffc83d",
        "--dr-orange:#ff8a2b",
        "--dr-red:#ef4a35",
        "--dr-cream:#f8f4e8",
    ):
        assert token in css
    assert ".founder-hero{" in css
    assert ".hero-card{" in css
    assert ".utility-drawer{" in css
    assert "@media(max-width:700px)" in css
    assert "@media(prefers-reduced-motion:reduce)" in css


def test_redesign_does_not_add_external_font_or_script_dependencies() -> None:
    html = INDEX.read_text().casefold()

    assert "fonts.googleapis.com" not in html
    assert "cdnjs" not in html
    assert "unpkg" not in html
    assert "jsdelivr" not in html
