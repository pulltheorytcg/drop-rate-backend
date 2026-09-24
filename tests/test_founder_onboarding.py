from pathlib import Path

from app.founder_onboarding import FounderInviteCreate, FounderInviteRedeem, _token_hash


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "database" / "migrations" / "202609240003_founder_invites.sql"
JOIN_JS = ROOT / "backend" / "app" / "static" / "join.js"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_invite_hash_is_deterministic_and_does_not_return_raw_token() -> None:
    token = "this-is-a-long-founder-invite-token"
    assert _token_hash(token) == _token_hash(token)
    assert _token_hash(token) != token


def test_founder_invite_payload_normalises_name_and_email() -> None:
    payload = FounderInviteCreate(
        invited_name="  Riaz  ",
        invited_email="  RIAZ@example.com ",
        founder_slot=2,
    )
    assert payload.invited_name == "Riaz"
    assert payload.invited_email == "riaz@example.com"
    assert payload.founder_slot == 2


def test_redeem_payload_normalises_email() -> None:
    payload = FounderInviteRedeem(
        token="x" * 32,
        display_name="Riaz",
        email=" RIAZ@example.com ",
    )
    assert payload.email == "riaz@example.com"


def test_founder_invite_migration_is_one_time_and_security_definer() -> None:
    sql = MIGRATION.read_text()
    assert "token_hash text not null unique" in sql
    assert "security definer" in sql.casefold()
    assert "redeemed_at" in sql
    assert "revoked_at" in sql
    assert "founder_invites_open_slot_key" in sql
    assert "FOUNDER_INVITE_REDEEMED" in sql


def test_join_flow_uses_supabase_auth_then_redeems_membership() -> None:
    source = JOIN_JS.read_text()
    assert "/signup?redirect_to=" in source
    assert "/token?grant_type=password" in source
    assert "/api/v1/founder-invites/redeem" in source
    assert "drop_rate_pending_founder_invite" in source


def test_join_route_and_onboarding_router_are_wired() -> None:
    main = MAIN.read_text()
    assert '@app.get("/join"' in main
    assert "app.include_router(founder_onboarding_router)" in main


def test_main_auth_callback_preserves_pending_founder_invite() -> None:
    app_js = (ROOT / "backend" / "app" / "static" / "app.js").read_text()
    assert "redirectPendingFounderInviteCallback" in app_js
    assert 'localStorage.getItem("drop_rate_pending_founder_invite")' in app_js
    assert 'params.get("type") === "recovery"' in app_js
    assert "/join?invite=" in app_js
