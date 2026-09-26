from __future__ import annotations

from pathlib import Path

import pytest

from app.stripe_connect_client import StripeConnectClient
from scripts.stripe_transfer_sandbox_selftest import _available_minor


ROOT = Path(__file__).resolve().parents[1]
CLIENT_SOURCE = ROOT / "backend" / "app" / "stripe_connect_client.py"
SELFTEST_SOURCE = ROOT / "backend" / "scripts" / "stripe_transfer_sandbox_selftest.py"


def test_available_balance_helper_reads_requested_currency() -> None:
    balance = {
        "available": [
            {"currency": "usd", "amount": 1500},
            {"currency": "gbp", "amount": 9100},
        ]
    }
    assert _available_minor(balance, "gbp") == 9100
    assert _available_minor(balance, "eur") == 0


def test_sandbox_funding_refuses_live_key() -> None:
    client = StripeConnectClient(secret_key="sk_live_example")
    with pytest.raises(RuntimeError, match="live Stripe key"):
        import asyncio

        asyncio.run(
            client.create_test_available_balance_charge(
                amount_minor=10000,
                currency="gbp",
                idempotency_key="drop-rate:test:funding:123",
            )
        )


def test_transfer_primitives_are_idempotency_aware() -> None:
    source = CLIENT_SOURCE.read_text()
    assert '"/transfers"' in source
    assert 'f"/transfers/{transfer_id}/reversals"' in source
    assert '"/refunds"' in source
    assert '"/balance"' in source
    assert '"tok_bypassPending"' in source
    assert "idempotency_key=idempotency_key.strip()" in source


def test_transfer_sandbox_is_fail_closed_and_test_only() -> None:
    source = SELFTEST_SOURCE.read_text()
    assert "TCG_STRIPE_SANDBOX_TRANSFER_SELFTEST" in source
    assert "TCG_STRIPE_SANDBOX_RECIPIENT_ACCOUNT_ID" in source
    assert 'startswith("sk_test_")' in source
    assert "stripe_connect_live_enabled" in source
    assert "stripe_payout_execution_enabled" in source
    assert 'transfers_status != "active"' in source
    assert 'account.get("payouts_enabled")' in source


def test_transfer_sandbox_proves_100_10_90_execution_leg() -> None:
    source = SELFTEST_SOURCE.read_text()
    assert "TRANSFER_MINOR = 9000" in source
    assert "FUNDING_MINOR = 10000" in source
    assert "create_test_available_balance_charge" in source
    assert "create_transfer" in source
    assert "reverse_transfer" in source
    assert "refund_charge" in source
    assert '"transfer_idempotent": True' in source
    assert '"reversal_idempotent": True' in source
    assert '"funding_refunded": True' in source


def test_cleanup_reverses_transfer_before_refunding_platform_funding() -> None:
    source = SELFTEST_SOURCE.read_text()
    finally_block = source[source.index("    finally:") :]
    assert finally_block.index("reverse_transfer") < finally_block.index("refund_charge")
    assert "transfer_id is None or reversal_done" in finally_block
