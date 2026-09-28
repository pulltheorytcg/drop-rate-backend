from pathlib import Path

from app.owner_onboarding import OwnerInviteCreate, OwnerInviteRedeem, _token_hash


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "database" / "migrations" / "20260926221500_owner_invite_onboarding.sql"
JOIN_HTML = ROOT / "backend" / "app" / "static" / "owner-join.html"
JOIN_JS = ROOT / "backend" / "app" / "static" / "owner-join.js"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_owner_invite_payload_normalises_email_and_defaults_commission() -> None:
    payload = OwnerInviteCreate(
        invited_name="  Seller One  ",
        invited_email=" SELLER@example.com ",
    )
    assert payload.invited_name == "Seller One"
    assert payload.invited_email == "seller@example.com"
    assert payload.commission_bps == 1000


def test_owner_invite_redeem_payload_has_no_client_supplied_email() -> None:
    payload = OwnerInviteRedeem(
        token="x" * 32,
        display_name="Seller One",
    )
    assert payload.display_name == "Seller One"
    assert not hasattr(payload, "email")


def test_owner_invite_token_hash_is_one_way_and_deterministic() -> None:
    token = "this-is-a-long-owner-invite-token"
    assert _token_hash(token) == _token_hash(token)
    assert _token_hash(token) != token


def test_owner_invite_migration_can_only_create_restricted_consignor_owner() -> None:
    sql = MIGRATION.read_text()

    assert "create table if not exists tcg.owner_invites" in sql
    assert "force row level security" in sql
    assert "m.role='PLATFORM_ADMIN'" in sql
    assert "'CONSIGNOR'" in sql
    assert "'OWNER'" in sql
    assert "'PLATFORM_ADMIN'::text" not in sql
    assert "commission_bps integer not null default 1000" in sql
    assert "OWNER_INVITE_REDEEMED" in sql
    assert "OWNER_INVITE_REVOKED" in sql
    assert "Invite email does not match this authenticated account" in sql


def test_owner_invite_table_has_no_direct_application_access() -> None:
    sql = MIGRATION.read_text().lower()

    for role in ("public", "anon", "authenticated", "service_role", "tcg_api"):
        assert f"revoke all on tcg.owner_invites from {role}" in sql

    assert "grant execute on function tcg.create_owner_invite" in sql
    assert "grant execute on function tcg.preview_owner_invite" in sql
    assert "grant execute on function tcg.redeem_owner_invite" in sql


def test_owner_join_flow_uses_verified_session_and_owner_redeem_endpoint() -> None:
    source = JOIN_JS.read_text()

    assert "/signup?redirect_to=" in source
    assert "/token?grant_type=password" in source
    assert "/api/v1/owner-invites/redeem" in source
    assert "drop_rate_pending_owner_invite" in source
    assert "authenticatedUser(session)" in source
    assert "email," not in source[source.index('body: JSON.stringify({\n      token: state.token'):source.index('}),', source.index('body: JSON.stringify({\n      token: state.token'))]


def test_owner_join_route_and_router_are_wired() -> None:
    main = MAIN.read_text()
    html = JOIN_HTML.read_text()

    assert '@app.get("/owner/join", include_in_schema=False)' in main
    assert "app.include_router(owner_onboarding_router)" in main
    assert '<script src="/assets/owner-join.js" defer></script>' in html


def test_owner_invite_ui_discloses_commission_before_signup() -> None:
    source = JOIN_JS.read_text()

    assert "commission_bps" in source
    assert "Drop Rate commission:" in source
    assert "restricted consignor account" in source


def test_founder_redeem_is_bound_to_verified_jwt_email_too() -> None:
    source = (ROOT / "backend" / "app" / "founder_onboarding.py").read_text()

    assert "if not user.email:" in source
    assert "payload.email," not in source
    assert "user.email," in source

def test_founder_hq_settings_can_create_and_revoke_restricted_owner_invites() -> None:
    source = (ROOT / "backend" / "app" / "static" / "dashboard-shell.js").read_text()

    assert "Invite seller / consignor" in source
    assert 'id="owner-invite-commission"' in source
    assert 'value="10"' in source
    assert 'apiRequest("/api/v1/owner-invites"' in source
    assert 'method: "POST"' in source
    assert 'method: "DELETE"' in source
    assert "commission_bps: Math.round(commissionPercent * 100)" in source
    assert "This can never grant Founder HQ access." in source



def test_owner_invite_create_fix_qualifies_output_column_collision() -> None:
    migration = (ROOT / "database" / "migrations" / "20260928061929_fix_owner_invite_ambiguous_email_column.sql").read_text()
    lower = migration.lower()

    assert "update tcg.owner_invites i" in lower
    assert "lower(i.invited_email)=v_email" in lower
    assert "security definer" in lower
    assert "set search_path = pg_catalog, tcg" in lower
    assert "grant execute on function tcg.create_owner_invite" in lower
