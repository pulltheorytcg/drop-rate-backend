from pathlib import Path

import base64
import hashlib
import hmac
from datetime import datetime, timezone

import pytest

from app.owner_onboarding import (
    ONBOARDING_ACK_VERSION,
    OwnerInviteCreate,
    OwnerInviteRedeem,
    _mask_email,
    _token_hash,
)
from app.resend_email import (
    ResendWebhookVerificationError,
    build_seller_invite_email,
    verify_resend_webhook,
)


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
        acknowledged=True,
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
    assert "Invited email:" in source
    assert "Drop Rate commission:" in source


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


EMAIL_MIGRATION = ROOT / "database" / "migrations" / "20260928172500_owner_invite_email_delivery.sql"
SELLER_INVITES_JS = ROOT / "backend" / "app" / "static" / "seller-invites.js"
SETTINGS = ROOT / "backend" / "app" / "settings.py"


def test_owner_invite_redeem_requires_explicit_acknowledgement() -> None:
    payload = OwnerInviteRedeem(
        token="x" * 32,
        display_name="Seller One",
        acknowledged=True,
    )
    assert payload.acknowledged is True
    assert payload.acknowledgement_version == ONBOARDING_ACK_VERSION

    with pytest.raises(Exception):
        OwnerInviteRedeem(
            token="x" * 32,
            display_name="Seller One",
            acknowledged=True,
            acknowledgement_version=2,
        )


def test_public_owner_invite_masks_email_address() -> None:
    assert _mask_email("seller@example.com").startswith("se")
    assert _mask_email("seller@example.com").endswith("@example.com")
    assert "seller@example.com" != _mask_email("seller@example.com")


def test_branded_seller_invite_email_has_secure_cta_and_terms_summary() -> None:
    email = build_seller_invite_email(
        invited_name="<Seller>",
        invite_url="https://drop.example/owner/join?invite=secret",
        commission_bps=1000,
        expires_at=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
        logo_url="https://drop.example/assets/brand-assets/drop-rate-logo.png",
    )
    assert email.subject == "You're invited to sell with Drop Rate"
    assert "Start seller onboarding" in email.html
    assert "10%" in email.html
    assert "private and owner-scoped" in email.html
    assert "&lt;Seller&gt;" in email.html
    assert "https://drop.example/owner/join?invite=secret" in email.text
    assert "Set up Stripe payouts" in email.html


def test_resend_email_adapter_uses_idempotency_and_never_logs_token() -> None:
    source = (ROOT / "backend" / "app" / "resend_email.py").read_text()
    assert "https://api.resend.com/emails" in source
    assert '"Idempotency-Key": idempotency_key' in source
    assert '"Authorization": f"Bearer {self._api_key}"' in source
    assert "logger" not in source.casefold()
    assert "print(" not in source


def test_seller_invite_email_delivery_is_audited_and_retryable() -> None:
    sql = EMAIL_MIGRATION.read_text()
    lower = sql.lower()

    assert "email_status" in lower
    assert "email_attempt_count" in lower
    assert "prepare_owner_invite_resend" in lower
    assert "record_owner_invite_email_result" in lower
    assert "owner_invite_email_sent" in lower
    assert "owner_invite_email_failed" in lower
    assert "owner_invite_resend_prepared" in lower
    assert "onboarding_ack_version" in lower
    assert "onboarding_acknowledged_at" in lower
    assert "security definer" in lower
    assert "grant execute on function tcg.list_owner_invites" in lower
    assert "grant execute on function tcg.prepare_owner_invite_resend" in lower


def test_seller_invite_backend_sends_email_but_keeps_link_fallback() -> None:
    source = (ROOT / "backend" / "app" / "owner_onboarding.py").read_text()
    assert "_send_invite_email(" in source
    assert "ResendEmailClient" in source
    assert '"invite_url": invite_url' in source
    assert '"email_delivery": delivery' in source
    assert '@router.post("/api/v1/owner-invites/{invite_id}/resend")' in source
    assert '@router.get("/api/v1/owner-invites")' in source
    assert "prepare_owner_invite_resend" in source
    assert "record_owner_invite_email_result" in source


def test_owner_invite_token_is_not_persisted_in_email_delivery_schema() -> None:
    sql = EMAIL_MIGRATION.read_text().lower()
    assert "raw_token" not in sql
    assert "invite_url" not in sql
    assert "token_hash" in sql


def test_owner_join_flow_is_guided_and_acknowledged_before_redeem() -> None:
    html = JOIN_HTML.read_text()
    source = JOIN_JS.read_text()

    assert "Seller onboarding" in html
    assert "What your owner account includes" in html
    assert 'id="owner-join-ack"' in html
    assert 'id="owner-existing-ack"' in html
    assert "acknowledged: true" in source
    assert "acknowledgement_version: state.acknowledgementVersion" in source
    assert 'PENDING_OWNER_ACK_KEY' in source
    assert 'window.location.replace("/owner?welcome=1")' in source
    assert "invited_email_masked" in source


def test_founder_hq_tracks_invite_email_and_acceptance_state() -> None:
    main = MAIN.read_text()
    ui = SELLER_INVITES_JS.read_text()

    assert '<script src="/assets/seller-invites.js" defer></script>' in main
    assert "/api/v1/owner-invites?limit=25" in ui
    assert "/resend" in ui
    assert "Email sent" in ui
    assert "Email failed" in ui
    assert "Accepted" in ui
    assert "Resend" in ui
    assert "Revoke" in ui


def test_seller_invite_email_settings_are_explicit_and_secret() -> None:
    source = SETTINGS.read_text()
    assert 'TCG_PUBLIC_APP_URL' in source
    assert 'TCG_RESEND_API_KEY' in source
    assert 'TCG_SELLER_INVITE_FROM_EMAIL' in source
    assert 'TCG_SELLER_INVITE_REPLY_TO' in source
    public_config = (ROOT / "backend" / "app" / "main.py").read_text()
    assert "resend_api_key" not in public_config[
        public_config.index('@app.get("/api/v1/public-config"'):
        public_config.index('@app.get("/health/live"')
    ]


def _svix_signature(secret_bytes: bytes, event_id: str, timestamp: int, body: bytes) -> str:
    signed = (
        event_id.encode("utf-8")
        + b"."
        + str(timestamp).encode("ascii")
        + b"."
        + body
    )
    digest = base64.b64encode(
        hmac.new(secret_bytes, signed, hashlib.sha256).digest()
    ).decode("ascii")
    return f"v1,{digest}"


def test_resend_webhook_verification_uses_raw_body_and_tolerance() -> None:
    secret_bytes = b"drop-rate-test-webhook-secret"
    encoded = base64.b64encode(secret_bytes).decode("ascii")
    secret = f"whsec_{encoded}"
    body = b'{"type":"email.delivered","data":{"email_id":"email_123"}}'
    timestamp = 1_800_000_000
    event_id = "msg_test_123"
    signature = _svix_signature(secret_bytes, event_id, timestamp, body)

    verify_resend_webhook(
        raw_body=body,
        webhook_secret=secret,
        svix_id=event_id,
        svix_timestamp=str(timestamp),
        svix_signature=signature,
        now=timestamp + 10,
    )

    with pytest.raises(ResendWebhookVerificationError):
        verify_resend_webhook(
            raw_body=body + b" ",
            webhook_secret=secret,
            svix_id=event_id,
            svix_timestamp=str(timestamp),
            svix_signature=signature,
            now=timestamp + 10,
        )

    with pytest.raises(ResendWebhookVerificationError):
        verify_resend_webhook(
            raw_body=body,
            webhook_secret=secret,
            svix_id=event_id,
            svix_timestamp=str(timestamp),
            svix_signature=signature,
            now=timestamp + 301,
        )


def test_resend_webhook_delivery_ledger_is_idempotent_and_pii_minimised() -> None:
    sql = EMAIL_MIGRATION.read_text().lower()

    assert "create table if not exists tcg.owner_invite_email_events" in sql
    assert "unique(provider,webhook_event_id)" in sql
    assert "payload_sha256" in sql
    assert "record_owner_invite_email_webhook" in sql
    assert "'email.delivered'" in sql
    assert "'email.bounced'" in sql
    assert "'email.failed'" in sql
    assert "owner_invite_email_event" in sql
    assert "payload jsonb" not in sql


def test_resend_webhook_route_verifies_before_parsing_and_updates_status() -> None:
    source = (ROOT / "backend" / "app" / "owner_onboarding.py").read_text()
    start = source.index('@router.post("/api/v1/webhooks/resend")')
    end = source.index('@router.delete("/api/v1/owner-invites/{invite_id}")', start)
    block = source[start:end]

    assert "raw_body = await request.body()" in block
    assert "verify_resend_webhook(" in block
    assert block.index("verify_resend_webhook(") < block.index("json.loads(raw_body)")
    assert 'request.headers.get("svix-id"' in block
    assert 'request.headers.get("svix-timestamp"' in block
    assert 'request.headers.get("svix-signature"' in block
    assert "record_owner_invite_email_webhook" in block
    assert "hashlib.sha256(raw_body).hexdigest()" in block


def test_resend_webhook_secret_is_not_exposed_publicly() -> None:
    settings = SETTINGS.read_text()
    assert "TCG_RESEND_WEBHOOK_SECRET" in settings
    main = MAIN.read_text()
    public = main[
        main.index('@app.get("/api/v1/public-config"'):
        main.index('@app.get("/health/live"')
    ]
    assert "resend_webhook_secret" not in public
