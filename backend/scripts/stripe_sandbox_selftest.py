from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

from app.settings import get_settings
from app.stripe_connect_client import StripeApiError, StripeConnectClient


def _enabled() -> bool:
    return os.getenv("TCG_STRIPE_SANDBOX_SELFTEST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def _run() -> None:
    if not _enabled():
        print(json.dumps({"stripe_sandbox_selftest": "SKIPPED"}))
        return

    settings = get_settings()
    if not settings.stripe_secret_key:
        raise RuntimeError("Stripe sandbox self-test requires TCG_STRIPE_SECRET_KEY")

    client = StripeConnectClient(secret_key=settings.stripe_secret_key)
    if client.key_livemode:
        raise RuntimeError("Stripe sandbox self-test refuses to run with a live secret key")

    if not settings.stripe_connect_refresh_url or not settings.stripe_connect_return_url:
        raise RuntimeError("Stripe Connect refresh/return URLs are required for sandbox self-test")

    # A successful authenticated platform-account response verifies the key.
    # Key mode is enforced from the sk_test_ prefix above; the platform account
    # response does not consistently expose a livemode field.
    platform = await client.retrieve_platform_account()
    platform_id = str(platform.get("id") or "").strip()
    if not platform_id.startswith("acct_"):
        raise RuntimeError("Stripe platform account response is invalid")

    account_id: str | None = None
    cleanup_ok = False
    try:
        owner_marker = f"sandbox-selftest-{uuid4()}"
        created = await client.create_express_account(
            country=settings.stripe_connect_country,
            owner_id=owner_marker,
            display_name="Drop Rate Sandbox Consignor",
            contact_email="sandbox-consignor@example.com",
        )
        account_id = str(created.get("id") or "").strip()
        if not account_id.startswith("acct_"):
            raise RuntimeError("Stripe did not return a valid connected account ID")
        if created.get("livemode") is not False:
            raise RuntimeError("Created Stripe connected account is not in test mode")
        applied = created.get("applied_configurations")
        if not isinstance(applied, list) or "recipient" not in applied:
            raise RuntimeError("Stripe Accounts v2 recipient configuration was not applied")
        recipient = created.get("configuration")
        if not isinstance(recipient, dict) or not isinstance(recipient.get("recipient"), dict):
            raise RuntimeError("Stripe Accounts v2 recipient details were not returned")

        retrieved = await client.retrieve_account(account_id)
        if str(retrieved.get("id") or "") != account_id:
            raise RuntimeError("Stripe connected-account readback did not match")
        if retrieved.get("livemode") is not False:
            raise RuntimeError("Stripe connected-account readback is not in test mode")

        link = await client.create_account_link(
            account_id=account_id,
            refresh_url=settings.stripe_connect_refresh_url,
            return_url=settings.stripe_connect_return_url,
        )
        link_url = str(link.get("url") or "").strip()
        if not link_url.startswith("https://"):
            raise RuntimeError("Stripe did not return a secure onboarding URL")

        capabilities = retrieved.get("capabilities")
        transfers_status = None
        if isinstance(capabilities, dict):
            transfers_status = capabilities.get("transfers")

        requirements = retrieved.get("requirements")
        currently_due_count = 0
        eventually_due_count = 0
        if isinstance(requirements, dict):
            currently_due = requirements.get("currently_due")
            eventually_due = requirements.get("eventually_due")
            if isinstance(currently_due, list):
                currently_due_count = len(currently_due)
            if isinstance(eventually_due, list):
                eventually_due_count = len(eventually_due)

        print(
            json.dumps(
                {
                    "stripe_sandbox_selftest": "PASS",
                    "platform_auth_ok": True,
                    "platform_test_key": True,
                    "platform_country": str(platform.get("country") or ""),
                    "connected_account_created": True,
                    "connected_account_livemode": bool(retrieved.get("livemode")),
                    "recipient_configuration_applied": True,
                    "transfers_capability": transfers_status,
                    "currently_due_count": currently_due_count,
                    "eventually_due_count": eventually_due_count,
                    "onboarding_link_created": True,
                },
                sort_keys=True,
            )
        )
    finally:
        if account_id:
            closed = await client.close_recipient_account(account_id)
            cleanup_ok = str(closed.get("id") or "").strip() == account_id
            if not cleanup_ok:
                raise RuntimeError("Stripe sandbox account cleanup did not confirm closure")
        print(
            json.dumps(
                {
                    "stripe_sandbox_cleanup": "PASS" if cleanup_ok else "SKIPPED",
                },
                sort_keys=True,
            )
        )


def main() -> None:
    try:
        asyncio.run(_run())
    except StripeApiError as exc:
        raise SystemExit(
            f"Stripe sandbox self-test failed: status={exc.status_code} code={exc.code} detail={exc.detail}"
        ) from exc


if __name__ == "__main__":
    main()
