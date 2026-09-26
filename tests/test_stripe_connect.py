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
MIGRATION_SOURCE = ROOT / "migrations" / "008_stripe_connect_payout_phase1.sql"
FINANCE_UI = ROOT / "backend" / "app" / "static" / "founder-finance.js"


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


def test_connect_client_requests_only_transfers_capability() -> None:
    source = CLIENT_SOURCE.read_text()
    assert '"capabilities[transfers][requested]": True' in source
    assert "card_payments" not in source
    assert '"type": "express"' in source
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
    assert "await request.body()" in source
    assert "payload_hash = hashlib.sha256(raw).hexdigest()" in source


def test_stripe_payout_execution_identity_is_immutable() -> None:
    migration = MIGRATION_SOURCE.read_text()
    assert "protect_stripe_payout_execution_identity" in migration
    assert "Stripe payout execution identity is immutable" in migration
    assert "idempotency_key text not null unique" in migration


def test_founder_hq_surfaces_connect_readiness_and_approval_queue() -> None:
    source = FINANCE_UI.read_text()
    assert "Stripe Connect" in source
    assert "Payout account" in source
    assert "Approval queue" in source
    assert "/api/v1/stripe/connect/status" in source
    assert "/api/v1/stripe/payouts/queue" in source
    assert "Founder approval and Stripe readiness are required" in source
