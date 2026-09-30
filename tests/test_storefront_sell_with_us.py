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


def test_storefront_has_sell_with_us_cta_for_desktop_and_mobile() -> None:
    source = HEADER.read_text()

    assert "Sell With Us" in source
    assert ">Sell<" in source
    assert "drop-rate-api-live-production.up.railway.app/owner/join" in source
    assert 'class="dr-sell-with-us"' in source
    assert ".dr-sell-with-us__mobile" in source
