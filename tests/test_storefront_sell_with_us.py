from pathlib import Path

from app.owner_onboarding import ONBOARDING_ACK_VERSION, OwnerSelfRegister


ROOT = Path(__file__).parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260930201500_public_owner_self_registration.sql"
)
ONBOARDING = ROOT / "backend" / "app" / "owner_onboarding.py"
JOIN_HTML = ROOT / "backend" / "app" / "static" / "owner-join.html"
JOIN_JS = ROOT / "backend" / "app" / "static" / "owner-join.js"
HEADER = ROOT / "storefront" / "theme" / "snippets" / "header-actions.liquid"
HEADER_GROUP = ROOT / "storefront" / "theme" / "sections" / "header-group.json"
FOOTER_GROUP = ROOT / "storefront" / "theme" / "sections" / "footer-group.json"
MOBILE_FOOTER = ROOT / "storefront" / "theme" / "sections" / "dr-mobile-sell-with-us.liquid"
GLOBAL_STYLES = ROOT / "storefront" / "theme" / "snippets" / "drop-rate-global-styles.liquid"


def test_self_registration_payload_requires_acknowledgement_version_one() -> None:
    payload = OwnerSelfRegister(
        display_name="  Seller One  ",
        acknowledged=True,
    )
    assert payload.display_name == "Seller One"
    assert payload.acknowledged is True
    assert payload.acknowledgement_version == ONBOARDING_ACK_VERSION


def test_self_registration_is_verified_owner_only_and_idempotent() -> None:
    sql = MIGRATION.read_text()
    lower = sql.lower()

    assert "security definer" in lower
    assert "auth.users" in lower
    assert "email_confirmed_at" in lower
    assert "is_anonymous" in lower
    assert "'CONSIGNOR'" in sql
    assert "'OWNER'" in sql
    assert "'PLATFORM_ADMIN'" not in sql
    assert "commission_bps" in lower
    assert "1000" in sql
    assert "OWNER_SELF_REGISTERED" in sql
    assert "if v_membership.active and v_membership.role = 'OWNER'" in sql
    assert "different Drop Rate access role" in sql
    assert "pg_advisory_xact_lock" in lower


def test_self_registration_function_is_not_directly_public() -> None:
    lower = MIGRATION.read_text().lower()

    assert (
        "revoke all on function tcg.self_register_owner(text, integer) from public"
        in lower
    )
    assert (
        "grant execute on function tcg.self_register_owner(text, integer) to tcg_api"
        in lower
    )


def test_public_registration_api_uses_authenticated_server_contract() -> None:
    source = ONBOARDING.read_text()

    assert '@router.post("/api/v1/owner-self-register")' in source
    assert "Depends(require_user)" in source
    assert "if not user.email:" in source
    assert "tcg.self_register_owner($1,$2)" in source
    assert '"next": "/owner?welcome=1"' in source


def test_join_page_supports_public_and_invite_modes() -> None:
    html = JOIN_HTML.read_text()
    source = JOIN_JS.read_text()

    assert "<title>Drop Rate — Sell With Us</title>" in html
    assert "Verified accounts" in html
    assert "Create Seller Hub account" in html

    assert '"/api/v1/owner-self-register"' in source
    assert '"/api/v1/owner-invites/redeem"' in source
    assert "const inviteMode = Boolean(state.token)" in source
    assert "if (state.token)" in source
    assert '"commission_bps: 1000"' not in source
    assert "commission_bps: 1000" in source
    assert 'window.location.replace("/owner?welcome=1")' in source


def test_clean_public_join_ignores_stale_invite_storage() -> None:
    html = JOIN_HTML.read_text()
    source = JOIN_JS.read_text()

    assert 'src="/assets/owner-join.js?v=public-join-2"' in html
    assert 'const explicitToken = params.get("invite");' in source
    assert "if (explicitToken) return explicitToken;" in source
    assert 'const callback = new URLSearchParams(window.location.hash.slice(1));' in source
    assert 'if (callback.get("access_token")) {' in source
    assert "return localStorage.getItem(PENDING_OWNER_INVITE_KEY);" in source
    assert 'return params.get("invite") || localStorage.getItem(PENDING_OWNER_INVITE_KEY);' not in source


def test_storefront_keeps_header_sell_cta_desktop_only() -> None:
    source = HEADER.read_text()

    assert "Sell With Us" in source
    assert "drop-rate-api-live-production.up.railway.app/owner/join" in source
    assert 'class="dr-sell-with-us"' in source
    assert ".dr-sell-with-us__mobile" not in source
    assert ">Sell<" not in source
    assert "@media screen and (max-width: 749px)" in source
    assert ".dr-sell-with-us {\n      display: none;" in source


def test_brand_redesign_uses_mobile_sell_menu_without_changing_default_menu() -> None:
    header_group = HEADER_GROUP.read_text()
    styles = GLOBAL_STYLES.read_text()

    assert '"menu": "brand-redesign-main-menu"' in header_group
    assert "Brand Redesign keeps Sell With Us in the mobile drawer only." in styles
    assert 'header-menu .menu-list__list-item:has(a[href="https://drop-rate-api-live-production.up.railway.app/owner/join"])' in styles
    assert "@media screen and (min-width: 750px)" in styles


def test_mobile_footer_has_sell_with_us_link() -> None:
    footer = MOBILE_FOOTER.read_text()
    footer_group = FOOTER_GROUP.read_text()

    assert "Sell With Us" in footer
    assert "drop-rate-api-live-production.up.railway.app/owner/join" in footer
    assert ".dr-mobile-sell-footer {\n    display: none;" in footer
    assert "@media screen and (max-width: 749px)" in footer
    assert '"type": "dr-mobile-sell-with-us"' in footer_group
