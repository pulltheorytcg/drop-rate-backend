from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.stripe_connect import (
    _account_snapshot,
    _readiness_blockers,
    verify_stripe_signature,
)


ROOT = Path(__file__).resolve().parents[1]
STRIPE_SOURCE = ROOT / "backend" / "app" / "stripe_connect.py"
CLIENT_SOURCE = ROOT / "backend" / "app" / "stripe_connect_client.py"
MIGRATION_SOURCE = ROOT / "database" / "migrations" / "20260926180043_stripe_connect_payout_phase1.sql"
HARDEN_MIGRATION = ROOT / "database" / "migrations" / "20260926181040_harden_stripe_payout_control.sql"
FINANCE_UI = ROOT / "backend" / "app" / "static" / "founder-finance.js"
SELFTEST_SOURCE = ROOT / "backend" / "scripts" / "stripe_sandbox_selftest.py"


def test_ready_account_requires_active_transfers_and_no_verification_blockers() -> None:
    snapshot = _account_snapshot({
        "id": "acct_test123",
        "livemode": False,
        "country": "GB",
        "details_submitted": True,
        "charges_enabled": False,
        "payouts_enabled": True,
        "capabilities": {"transfers": "active"},
        "requirements": {
            "currently_due": [],
            "eventually_due": [],
            "past_due": [],
            "disabled_reason": None,
        },
    })
    assert snapshot["status"] == "READY"
    assert snapshot["transfers_capability_status"] == "ACTIVE"
    assert snapshot["payouts_enabled"] is True
    assert _readiness_blockers(snapshot) == []


def test_incomplete_kyc_is_action_required() -> None:
    snapshot = _account_snapshot({
        "id": "acct_test123",
        "livemode": False,
        "details_submitted": True,
        "payouts_enabled": False,
        "capabilities": {"transfers": "pending"},
        "requirements": {
            "currently_due": ["individual.verification.document"],
            "past_due": [],
        },
    })
    blockers = _readiness_blockers(snapshot)
    assert snapshot["status"] == "RESTRICTED"
    assert "PAYOUTS_DISABLED" in blockers
    assert "TRANSFERS_NOT_ACTIVE" in blockers
    assert "VERIFICATION_CURRENTLY_DUE" in blockers


def test_stripe_signature_verification_accepts_valid_v1_signature() -> None:
    payload = b'{"id":"evt_test123","type":"account.updated"}'
    timestamp = 1_800_000_000
    secret = "whsec_test_secret"
    signed = str(timestamp).encode("ascii") + b"." + payload
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    verify_stripe_signature(
        payload,
        f"t={timestamp},v1={signature}",
        secret,
        now=timestamp,
    )


def test_stripe_signature_verification_rejects_stale_or_invalid_signatures() -> None:
    payload = b"{}"
    with pytest.raises(HTTPException):
        verify_stripe_signature(
            payload,
            "t=100,v1=deadbeef",
            "whsec_test_secret",
            now=1000,
        )


def test_connect_client_uses_accounts_v2_recipient_for_payout_only_accounts() -> None:
    source = CLIENT_SOURCE.read_text()
    assert 'STRIPE_API_V2_BASE = "https://api.stripe.com/v2/core"' in source
    assert 'STRIPE_API_V2_VERSION = "2026-07-29.dahlia"' in source
    assert '"recipient"' in source
    assert '"stripe_transfers"' in source
    assert '"requested": True' in source
    assert '"contact_email": safe_email' in source
    assert '"dashboard": "express"' in source
    assert '"fees_collector": "application"' in source
    assert '"losses_collector": "application"' in source
    assert "card_payments" not in source
    assert '"collection_options[fields]": "eventually_due"' in source


def test_payout_approval_is_preparation_only_and_idempotent() -> None:
    source = STRIPE_SOURCE.read_text()
    assert "'PREPARED'" in source
    assert 'f"drop-rate:payout:{payout[\'id\']}"' in source
    assert "stripe_payout_execution_enabled" not in source[source.index('@router.post("/payouts/{payout_id}/approve")'):source.index('@router.post("/payouts/{payout_id}/reject")')]
    assert "/transfers" not in source
    assert "/payouts" not in CLIENT_SOURCE.read_text()


def test_payout_approval_blocks_unreconciled_external_sales() -> None:
    source = STRIPE_SOURCE.read_text()
    assert "UNRECONCILED_EXTERNAL_SALES" in source
    assert "OWNER_BALANCE_SHORTFALL" in source
    assert "PAYOUTS_DISABLED" in source
    assert "TRANSFERS_NOT_ACTIVE" in source


def test_webhook_events_are_hash_only_and_idempotent() -> None:
    migration = MIGRATION_SOURCE.read_text()
    source = STRIPE_SOURCE.read_text()
    assert "payload_sha256" in migration
    assert "stripe_event_id text not null unique" in migration
    assert "on conflict (stripe_event_id) do nothing" in source
    assert "attempt_count=attempt_count+1" in source
    assert "replayed with a different payload" in source
    assert "await request.body()" in source
    assert "payload_hash = hashlib.sha256(raw).hexdigest()" in source


def test_stripe_payout_execution_identity_is_immutable() -> None:
    migration = MIGRATION_SOURCE.read_text()
    harden = HARDEN_MIGRATION.read_text()
    assert "protect_stripe_payout_execution_identity" in migration
    assert "Stripe payout execution identity is immutable" in migration
    assert "idempotency_key text not null unique" in migration
    assert "validate_stripe_payout_execution_consistency" in harden
    assert "does not match payout request owner or amount" in harden


def test_founder_hq_surfaces_connect_readiness_and_approval_queue() -> None:
    source = FINANCE_UI.read_text()
    assert "Stripe Connect" in source
    assert "Payout account" in source
    assert "Approval queue" in source
    assert "/api/v1/stripe/connect/status" in source
    assert "/api/v1/stripe/payouts/queue" in source
    assert "Founder approval and Stripe readiness are required" in source


def test_approved_payout_retry_is_idempotent_before_version_check() -> None:
    source = STRIPE_SOURCE.read_text()
    start = source.index('@router.post("/payouts/{payout_id}/approve")')
    block = source[start:source.index('@router.post("/payouts/{payout_id}/reject")')]
    assert block.index('payout["status"] == "APPROVED"') < block.index('payout["version"] != payload.version')


def test_stripe_client_supports_read_only_platform_probe_and_v2_cleanup() -> None:
    source = CLIENT_SOURCE.read_text()
    assert 'return await self._request("GET", "/account")' in source
    assert 'f"/accounts/{account_id}/close"' in source
    assert '{"applied_configurations": ["recipient"]}' in source


def test_stripe_sandbox_selftest_refuses_live_key_and_cleans_up() -> None:
    source = SELFTEST_SOURCE.read_text()
    assert "TCG_STRIPE_SANDBOX_SELFTEST" in source
    assert "client.key_livemode" in source
    assert "refuses to run with a live secret key" in source
    assert "create_express_account" in source
    assert "recipient_configuration_applied" in source
    assert "create_account_link" in source
    assert "retrieve_account" in source
    assert "close_recipient_account" in source
    assert '"stripe_sandbox_selftest": "PASS"' in source
    assert '"stripe_sandbox_cleanup": "PASS" if cleanup_ok else "SKIPPED"' in source
    assert "asyncpg" not in source


def test_new_connect_account_is_v2_created_then_v1_read_back_for_readiness() -> None:
    source = STRIPE_SOURCE.read_text()
    start = source.index("async def create_or_sync_stripe_account")
    end = source.index('@router.post("/connect/onboarding-link")', start)
    block = source[start:end]
    create = block.index("created_account = await client.create_express_account(")
    readback = block.index("account = await client.retrieve_account(account_id)")
    snapshot = block.index("snapshot = _account_snapshot(account)")
    assert create < readback < snapshot
    assert 'display_name=str(owner["display_name"])' in block
    assert "contact_email=user.email" in block
    assert "Authenticated account email is required for Stripe onboarding" in block


def test_sandbox_recipient_uses_nonproduction_contact_email() -> None:
    source = SELFTEST_SOURCE.read_text()
    assert 'contact_email="sandbox-consignor@example.com"' in source
