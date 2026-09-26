from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import uuid4

from app.settings import get_settings
from app.stripe_connect_client import StripeApiError, StripeConnectClient


TRANSFER_MINOR = 9000
FUNDING_MINOR = 10000
CURRENCY = "gbp"


def _enabled() -> bool:
    return os.getenv("TCG_STRIPE_SANDBOX_TRANSFER_SELFTEST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _recipient_account_id() -> str:
    return os.getenv("TCG_STRIPE_SANDBOX_RECIPIENT_ACCOUNT_ID", "").strip()


def _available_minor(balance: dict[str, Any], currency: str) -> int:
    available = balance.get("available")
    if not isinstance(available, list):
        return 0
    for item in available:
        if not isinstance(item, dict):
            continue
        if str(item.get("currency") or "").lower() == currency.lower():
            return int(item.get("amount") or 0)
    return 0


async def _run() -> None:
    if not _enabled():
        print(json.dumps({"stripe_transfer_sandbox_selftest": "SKIPPED"}))
        return

    settings = get_settings()
    secret_key = (settings.stripe_secret_key or "").strip()
    if not secret_key.startswith("sk_test_"):
        raise RuntimeError(
            "Stripe transfer sandbox self-test refuses to run without a Stripe test key"
        )
    if settings.stripe_connect_live_enabled:
        raise RuntimeError("Stripe live Connect must stay disabled during sandbox transfer test")
    if settings.stripe_payout_execution_enabled:
        raise RuntimeError(
            "Production payout execution must stay disabled during sandbox transfer test"
        )

    account_id = _recipient_account_id()
    if not account_id.startswith("acct_"):
        raise RuntimeError(
            "TCG_STRIPE_SANDBOX_RECIPIENT_ACCOUNT_ID must reference an onboarded test recipient"
        )

    client = StripeConnectClient(secret_key=secret_key)
    account = await client.retrieve_account(account_id)
    capabilities = account.get("capabilities")
    transfers_status = ""
    if isinstance(capabilities, dict):
        transfers_status = str(capabilities.get("transfers") or "").lower()
    if transfers_status != "active":
        requirements = account.get("requirements")
        due: list[str] = []
        if isinstance(requirements, dict):
            raw_due = requirements.get("currently_due")
            if isinstance(raw_due, list):
                due = [str(value) for value in raw_due]
        raise RuntimeError(
            "Stripe sandbox recipient is not transfer-ready: "
            f"transfers={transfers_status or 'unknown'} currently_due={due}"
        )
    if not bool(account.get("payouts_enabled")):
        raise RuntimeError("Stripe sandbox recipient does not have payouts enabled")

    marker = uuid4().hex
    funding_key = f"drop-rate:sandbox-funding:{marker}"
    transfer_key = f"drop-rate:sandbox-transfer:{marker}"
    reversal_key = f"drop-rate:sandbox-reversal:{marker}"
    refund_key = f"drop-rate:sandbox-refund:{marker}"
    transfer_group = f"DR_SANDBOX_{marker[:20].upper()}"

    charge_id: str | None = None
    transfer_id: str | None = None
    reversal_done = False
    refund_done = False

    before = await client.retrieve_balance()
    before_available = _available_minor(before, CURRENCY)

    try:
        charge = await client.create_test_available_balance_charge(
            amount_minor=FUNDING_MINOR,
            currency=CURRENCY,
            idempotency_key=funding_key,
        )
        charge_id = str(charge.get("id") or "").strip()
        if not charge_id.startswith("ch_"):
            raise RuntimeError("Stripe sandbox funding did not return a valid charge")

        funded = await client.retrieve_balance()
        funded_available = _available_minor(funded, CURRENCY)
        if funded_available < before_available + TRANSFER_MINOR:
            raise RuntimeError(
                "Stripe sandbox funding did not make enough GBP available "
                f"before={before_available} after={funded_available}"
            )

        transfer = await client.create_transfer(
            account_id=account_id,
            amount_minor=TRANSFER_MINOR,
            currency=CURRENCY,
            transfer_group=transfer_group,
            idempotency_key=transfer_key,
        )
        transfer_id = str(transfer.get("id") or "").strip()
        if not transfer_id.startswith("tr_"):
            raise RuntimeError("Stripe transfer did not return a valid transfer ID")
        if int(transfer.get("amount") or 0) != TRANSFER_MINOR:
            raise RuntimeError("Stripe transfer amount did not match £90")
        if bool(transfer.get("livemode")):
            raise RuntimeError("Stripe transfer unexpectedly ran in live mode")

        replay = await client.create_transfer(
            account_id=account_id,
            amount_minor=TRANSFER_MINOR,
            currency=CURRENCY,
            transfer_group=transfer_group,
            idempotency_key=transfer_key,
        )
        if str(replay.get("id") or "") != transfer_id:
            raise RuntimeError("Stripe transfer idempotency replay created a different transfer")

        reversal = await client.reverse_transfer(
            transfer_id=transfer_id,
            amount_minor=TRANSFER_MINOR,
            idempotency_key=reversal_key,
        )
        reversal_id = str(reversal.get("id") or "").strip()
        if not reversal_id.startswith("trr_"):
            raise RuntimeError("Stripe transfer reversal did not return a valid reversal ID")
        if int(reversal.get("amount") or 0) != TRANSFER_MINOR:
            raise RuntimeError("Stripe transfer reversal amount did not match £90")
        reversal_done = True

        reversal_replay = await client.reverse_transfer(
            transfer_id=transfer_id,
            amount_minor=TRANSFER_MINOR,
            idempotency_key=reversal_key,
        )
        if str(reversal_replay.get("id") or "") != reversal_id:
            raise RuntimeError(
                "Stripe transfer reversal idempotency replay returned a different reversal"
            )

        refund = await client.refund_charge(
            charge_id=charge_id,
            idempotency_key=refund_key,
        )
        if str(refund.get("charge") or "") != charge_id:
            raise RuntimeError("Stripe sandbox funding refund did not match the funding charge")
        refund_done = True

        print(
            json.dumps(
                {
                    "stripe_transfer_sandbox_selftest": "PASS",
                    "currency": CURRENCY.upper(),
                    "funding_minor": FUNDING_MINOR,
                    "transfer_minor": TRANSFER_MINOR,
                    "transfer_idempotent": True,
                    "reversal_minor": TRANSFER_MINOR,
                    "reversal_idempotent": True,
                    "funding_refunded": True,
                    "livemode": False,
                },
                sort_keys=True,
            )
        )
    finally:
        cleanup_errors: list[str] = []
        if transfer_id and not reversal_done:
            try:
                await client.reverse_transfer(
                    transfer_id=transfer_id,
                    amount_minor=TRANSFER_MINOR,
                    idempotency_key=f"{reversal_key}:cleanup",
                )
                reversal_done = True
            except Exception as exc:  # cleanup must preserve funding if reversal cannot be proven
                cleanup_errors.append(f"transfer_reversal:{type(exc).__name__}")

        if charge_id and not refund_done and (transfer_id is None or reversal_done):
            try:
                await client.refund_charge(
                    charge_id=charge_id,
                    idempotency_key=f"{refund_key}:cleanup",
                )
                refund_done = True
            except Exception as exc:
                cleanup_errors.append(f"funding_refund:{type(exc).__name__}")

        if cleanup_errors:
            raise RuntimeError(
                "Stripe sandbox transfer cleanup was incomplete: "
                + ",".join(cleanup_errors)
            )


def main() -> None:
    try:
        asyncio.run(_run())
    except StripeApiError as exc:
        raise SystemExit(
            f"Stripe transfer sandbox self-test failed: "
            f"status={exc.status_code} code={exc.code} detail={exc.detail}"
        ) from exc


if __name__ == "__main__":
    main()
