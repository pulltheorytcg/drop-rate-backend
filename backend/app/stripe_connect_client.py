from __future__ import annotations

from typing import Any

import httpx


STRIPE_API_BASE = "https://api.stripe.com/v1"
STRIPE_API_V2_BASE = "https://api.stripe.com/v2/core"
STRIPE_API_V2_VERSION = "2026-07-29.dahlia"


class StripeApiError(RuntimeError):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


class StripeConnectClient:
    """Small first-party Stripe client for Connect control-plane operations.

    Drop Rate intentionally keeps deterministic settlement logic outside Stripe.
    This client only handles connected-account onboarding/readiness in phase 1.
    """

    def __init__(self, *, secret_key: str, timeout_seconds: float = 20.0) -> None:
        key = secret_key.strip()
        if not key.startswith(("sk_test_", "sk_live_")):
            raise ValueError("Stripe secret key must be an sk_test_ or sk_live_ key")
        self._secret_key = key
        self._timeout = timeout_seconds

    @property
    def key_livemode(self) -> bool:
        return self._secret_key.startswith("sk_live_")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        encoded: dict[str, str] | None = None
        if data is not None:
            encoded = {}
            for key, value in data.items():
                if isinstance(value, bool):
                    encoded[key] = "true" if value else "false"
                elif value is not None:
                    encoded[key] = str(value)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    f"{STRIPE_API_BASE}{path}",
                    headers=headers,
                    data=encoded,
                )
        except httpx.HTTPError as exc:
            raise StripeApiError(
                "Stripe API request failed",
                retryable=True,
            ) from exc

        payload: dict[str, Any]
        try:
            parsed = response.json()
            payload = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            payload = {}

        if 200 <= response.status_code < 300:
            return payload

        error = payload.get("error")
        detail = "Stripe API rejected the request"
        code: str | None = None
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            if message:
                detail = message
            raw_code = error.get("code") or error.get("type")
            if raw_code:
                code = str(raw_code)
        raise StripeApiError(
            detail,
            status_code=response.status_code,
            code=code,
            retryable=response.status_code == 429 or response.status_code >= 500,
        )

    async def _request_v2(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
            "Stripe-Version": STRIPE_API_V2_VERSION,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    f"{STRIPE_API_V2_BASE}{path}",
                    headers=headers,
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise StripeApiError(
                "Stripe Accounts v2 API request failed",
                retryable=True,
            ) from exc

        payload: dict[str, Any]
        try:
            parsed = response.json()
            payload = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            payload = {}

        if 200 <= response.status_code < 300:
            return payload

        error = payload.get("error")
        detail = "Stripe Accounts v2 API rejected the request"
        code: str | None = None
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            if message:
                detail = message
            raw_code = error.get("code") or error.get("type")
            if raw_code:
                code = str(raw_code)
        raise StripeApiError(
            detail,
            status_code=response.status_code,
            code=code,
            retryable=response.status_code == 429 or response.status_code >= 500,
        )

    async def retrieve_platform_account(self) -> dict[str, Any]:
        return await self._request("GET", "/account")

    async def create_express_account(
        self,
        *,
        country: str,
        owner_id: str,
        display_name: str,
        contact_email: str,
    ) -> dict[str, Any]:
        """Create a payout-only Accounts v2 recipient with Express Dashboard access."""

        country_code = country.strip().lower()
        if len(country_code) != 2:
            raise ValueError("Stripe connected account country must be ISO-2")
        safe_name = display_name.strip()
        if not safe_name:
            raise ValueError("Stripe connected account display name is required")
        safe_email = contact_email.strip()
        if "@" not in safe_email or len(safe_email) > 320:
            raise ValueError("Stripe connected account contact email is invalid")

        return await self._request_v2(
            "POST",
            "/accounts",
            json_body={
                "contact_email": safe_email,
                "display_name": safe_name,
                "dashboard": "express",
                "identity": {
                    "country": country_code,
                },
                "configuration": {
                    "recipient": {
                        "capabilities": {
                            "stripe_balance": {
                                "stripe_transfers": {
                                    "requested": True,
                                }
                            }
                        }
                    }
                },
                "defaults": {
                    "currency": "gbp",
                    "locales": ["en-GB"],
                    "responsibilities": {
                        "fees_collector": "application",
                        "losses_collector": "application",
                    },
                    "profile": {
                        "product_description": (
                            "Trading-card marketplace seller and consignor payouts"
                        )
                    },
                },
                "metadata": {
                    "drop_rate_owner_id": owner_id,
                },
                "include": [
                    "configuration.recipient",
                    "defaults",
                    "identity",
                    "requirements",
                    "future_requirements",
                ],
            },
            idempotency_key=f"drop-rate-connect-v2-owner-{owner_id}",
        )

    async def retrieve_account(self, account_id: str) -> dict[str, Any]:
        account_id = account_id.strip()
        if not account_id.startswith("acct_"):
            raise ValueError("Invalid Stripe connected account ID")
        return await self._request("GET", f"/accounts/{account_id}")

    async def create_account_link(
        self,
        *,
        account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/account_links",
            data={
                "account": account_id,
                "refresh_url": refresh_url,
                "return_url": return_url,
                "type": "account_onboarding",
                "collection_options[fields]": "eventually_due",
            },
        )


    async def close_recipient_account(self, account_id: str) -> dict[str, Any]:
        account_id = account_id.strip()
        if not account_id.startswith("acct_"):
            raise ValueError("Invalid Stripe connected account ID")
        return await self._request_v2(
            "POST",
            f"/accounts/{account_id}/close",
            json_body={"applied_configurations": ["recipient"]},
        )
