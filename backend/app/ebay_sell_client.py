from __future__ import annotations

import asyncio
import base64
import time
from typing import Any
from urllib.parse import quote

import httpx

from .ebay_official_client import EBAY_PRODUCTION_BASE_URL, EbayApiError, EbayOfficialClient


class EbaySellApiError(EbayApiError):
    """Safe eBay seller-API error that never exposes credentials or raw payloads."""


class EbaySellClient:
    """eBay Inventory/Fulfillment client using seller-authorised OAuth.

    Drop Rate deliberately keeps seller OAuth separate from application OAuth.
    The refresh token must have been granted by the seller through eBay's
    Authorization Code Grant flow. Application credentials alone can never
    publish listings or retrieve the seller's orders.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        marketplace_id: str = "EBAY_GB",
        timeout_seconds: float = 20.0,
    ) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("eBay application credentials are required")
        if not refresh_token.strip():
            raise ValueError("eBay seller refresh token is required")
        if not marketplace_id.strip():
            raise ValueError("eBay marketplace ID is required")
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._refresh_token = refresh_token.strip()
        self._marketplace_id = marketplace_id.strip()
        self._timeout = timeout_seconds
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._granted_scopes: frozenset[str] = frozenset()
        self._application_client = EbayOfficialClient(
            client_id=self._client_id,
            client_secret=self._client_secret,
            marketplace_id=self._marketplace_id,
            timeout_seconds=timeout_seconds,
        )

    @property
    def marketplace_id(self) -> str:
        return self._marketplace_id

    @property
    def granted_scopes(self) -> frozenset[str]:
        return self._granted_scopes

    async def _refresh_user_token(self) -> tuple[str, int, frozenset[str]]:
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode("utf-8")
        ).decode("ascii")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{EBAY_PRODUCTION_BASE_URL}/identity/v1/oauth2/token",
                    headers={
                        "Authorization": f"Basic {credentials}",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._refresh_token,
                    },
                )
        except httpx.TimeoutException as exc:
            raise EbaySellApiError("eBay seller OAuth request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EbaySellApiError("eBay seller OAuth request failed", retryable=True) from exc

        if response.status_code != 200:
            raise EbaySellApiError(
                "eBay rejected the seller authorisation",
                status_code=response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EbaySellApiError("eBay seller OAuth returned invalid JSON") from exc

        token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        scope_text = payload.get("scope") or ""
        if not isinstance(token, str) or not token.strip():
            raise EbaySellApiError("eBay seller OAuth response is missing an access token")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise EbaySellApiError("eBay seller OAuth response has an invalid expiry")
        scopes = frozenset(str(scope_text).split())
        return token.strip(), expires_in, scopes

    async def user_access_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at:
            return self._access_token
        async with self._token_lock:
            now = time.monotonic()
            if self._access_token and now < self._token_expires_at:
                return self._access_token
            token, expires_in, scopes = await self._refresh_user_token()
            margin = min(60, max(5, expires_in // 10))
            self._access_token = token
            self._token_expires_at = time.monotonic() + max(1, expires_in - margin)
            self._granted_scopes = scopes
            return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        expected: set[int] | None = None,
        content_language: bool = False,
    ) -> dict[str, Any] | None:
        token = await self.user_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self._marketplace_id,
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if content_language:
            headers["Content-Language"] = "en-GB"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    f"{EBAY_PRODUCTION_BASE_URL}{path}",
                    headers=headers,
                    json=json_body,
                    params=params,
                )
        except httpx.TimeoutException as exc:
            raise EbaySellApiError("eBay seller API request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EbaySellApiError("eBay seller API request failed", retryable=True) from exc

        allowed = expected or {200}
        if response.status_code not in allowed:
            raise EbaySellApiError(
                "eBay seller API rejected the request",
                status_code=response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            payload = response.json()
        except ValueError as exc:
            raise EbaySellApiError("eBay seller API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise EbaySellApiError("eBay seller API returned an invalid response shape")
        return payload

    async def get_payment_policy(self, policy_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/sell/account/v1/payment_policy/{quote(policy_id, safe='')}",
        )
        if payload is None:
            raise EbaySellApiError("eBay payment policy response was empty")
        return payload

    async def get_fulfillment_policy(self, policy_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/sell/account/v1/fulfillment_policy/{quote(policy_id, safe='')}",
        )
        if payload is None:
            raise EbaySellApiError("eBay fulfillment policy response was empty")
        return payload

    async def get_return_policy(self, policy_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/sell/account/v1/return_policy/{quote(policy_id, safe='')}",
        )
        if payload is None:
            raise EbaySellApiError("eBay return policy response was empty")
        return payload

    async def get_inventory_location(self, merchant_location_key: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/sell/inventory/v1/location/{quote(merchant_location_key, safe='')}",
        )
        if payload is None:
            raise EbaySellApiError("eBay inventory location response was empty")
        return payload

    async def put_inventory_item(self, sku: str, payload: dict[str, Any]) -> None:
        await self._request(
            "PUT",
            f"/sell/inventory/v1/inventory_item/{quote(sku, safe='')}",
            json_body=payload,
            expected={204},
            content_language=True,
        )

    async def get_inventory_item(self, sku: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/sell/inventory/v1/inventory_item/{quote(sku, safe='')}",
        )
        if payload is None:
            raise EbaySellApiError("eBay inventory item response was empty")
        return payload

    async def get_offers(self, *, sku: str) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/sell/inventory/v1/offer",
            params={"sku": sku, "marketplace_id": self._marketplace_id},
        )
        rows = [] if payload is None else payload.get("offers", [])
        if rows is None:
            return []
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError("eBay offers response has an invalid shape")
        return rows

    async def create_offer(self, payload: dict[str, Any]) -> str:
        response = await self._request(
            "POST",
            "/sell/inventory/v1/offer",
            json_body=payload,
            expected={201},
            content_language=True,
        )
        offer_id = str((response or {}).get("offerId") or "").strip()
        if not offer_id:
            raise EbaySellApiError("eBay create offer response is missing offerId")
        return offer_id

    async def update_offer(self, offer_id: str, payload: dict[str, Any]) -> None:
        await self._request(
            "PUT",
            f"/sell/inventory/v1/offer/{quote(offer_id, safe='')}",
            json_body=payload,
            expected={204},
            content_language=True,
        )

    async def get_offer(self, offer_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/sell/inventory/v1/offer/{quote(offer_id, safe='')}",
        )
        if payload is None:
            raise EbaySellApiError("eBay offer response was empty")
        return payload

    async def publish_offer(self, offer_id: str) -> str:
        payload = await self._request(
            "POST",
            f"/sell/inventory/v1/offer/{quote(offer_id, safe='')}/publish",
            json_body={},
            expected={200},
        )
        listing_id = str((payload or {}).get("listingId") or "").strip()
        if not listing_id:
            raise EbaySellApiError("eBay publish response is missing listingId")
        return listing_id

    async def withdraw_offer(self, offer_id: str) -> None:
        await self._request(
            "POST",
            f"/sell/inventory/v1/offer/{quote(offer_id, safe='')}/withdraw",
            json_body={},
            expected={200, 204},
        )

    async def get_order(self, order_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/sell/fulfillment/v1/order/{quote(order_id, safe='')}",
        )
        if payload is None:
            raise EbaySellApiError("eBay order response was empty")
        return payload

    async def get_public_key(self, key_id: str) -> dict[str, Any]:
        token = await self._application_client.application_token()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{EBAY_PRODUCTION_BASE_URL}/commerce/notification/v1/public_key/"
                    f"{quote(key_id, safe='')}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise EbaySellApiError("eBay notification key request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EbaySellApiError("eBay notification key request failed", retryable=True) from exc
        if response.status_code != 200:
            raise EbaySellApiError(
                "eBay notification public key request was rejected",
                status_code=response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EbaySellApiError("eBay notification public key response was invalid") from exc
        if not isinstance(payload, dict):
            raise EbaySellApiError("eBay notification public key response has an invalid shape")
        return payload
