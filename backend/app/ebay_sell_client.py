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


REQUIRED_SELLER_SCOPES = (
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/commerce.notification.subscription",
)


async def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Exchange one eBay consent code for seller access + refresh tokens."""

    if not client_id.strip() or not client_secret.strip():
        raise ValueError("eBay application credentials are required")
    if not code.strip() or not redirect_uri.strip():
        raise ValueError("eBay authorization code and RuName are required")
    credentials = base64.b64encode(
        f"{client_id.strip()}:{client_secret.strip()}".encode("utf-8")
    ).decode("ascii")
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{EBAY_PRODUCTION_BASE_URL}/identity/v1/oauth2/token",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code.strip(),
                    "redirect_uri": redirect_uri.strip(),
                },
            )
    except httpx.TimeoutException as exc:
        raise EbaySellApiError("eBay OAuth code exchange timed out", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise EbaySellApiError("eBay OAuth code exchange failed", retryable=True) from exc

    if response.status_code != 200:
        raise EbaySellApiError(
            "eBay rejected the seller consent code",
            status_code=response.status_code,
            retryable=response.status_code == 429 or response.status_code >= 500,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise EbaySellApiError("eBay OAuth code exchange returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise EbaySellApiError("eBay OAuth code exchange returned an invalid response")

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    refresh_expires_in = payload.get("refresh_token_expires_in")
    if not isinstance(access_token, str) or not access_token.strip():
        raise EbaySellApiError("eBay OAuth response is missing an access token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise EbaySellApiError("eBay OAuth response is missing a refresh token")
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise EbaySellApiError("eBay OAuth response has an invalid access-token expiry")
    if not isinstance(refresh_expires_in, int) or refresh_expires_in <= 0:
        raise EbaySellApiError("eBay OAuth response has an invalid refresh-token expiry")
    return {
        "access_token": access_token.strip(),
        "refresh_token": refresh_token.strip(),
        "expires_in": expires_in,
        "refresh_token_expires_in": refresh_expires_in,
        "token_type": str(payload.get("token_type") or "User Access Token"),
    }


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
                        "scope": " ".join(REQUIRED_SELLER_SCOPES),
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
        scope_text = payload.get("scope") or " ".join(REQUIRED_SELLER_SCOPES)
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

    async def get_opted_in_programs(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/sell/account/v1/program/get_opted_in_programs",
        )
        rows = [] if payload is None else payload.get("programs", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError("eBay opted-in programs response has an invalid shape")
        return rows

    async def opt_in_to_program(self, program_type: str) -> None:
        value = program_type.strip()
        if not value:
            raise ValueError("eBay program type is required")
        await self._request(
            "POST",
            "/sell/account/v1/program/opt_in",
            json_body={"programType": value},
            expected={200, 204},
        )

    async def create_payment_policy(self, payload: dict[str, Any]) -> str:
        response = await self._request(
            "POST",
            "/sell/account/v1/payment_policy",
            json_body=payload,
            expected={201},
        )
        policy_id = str((response or {}).get("paymentPolicyId") or "").strip()
        if not policy_id:
            raise EbaySellApiError("eBay payment policy response is missing paymentPolicyId")
        return policy_id

    async def create_fulfillment_policy(self, payload: dict[str, Any]) -> str:
        response = await self._request(
            "POST",
            "/sell/account/v1/fulfillment_policy",
            json_body=payload,
            expected={201},
        )
        policy_id = str((response or {}).get("fulfillmentPolicyId") or "").strip()
        if not policy_id:
            raise EbaySellApiError(
                "eBay fulfillment policy response is missing fulfillmentPolicyId"
            )
        return policy_id

    async def create_return_policy(self, payload: dict[str, Any]) -> str:
        response = await self._request(
            "POST",
            "/sell/account/v1/return_policy",
            json_body=payload,
            expected={201},
        )
        policy_id = str((response or {}).get("returnPolicyId") or "").strip()
        if not policy_id:
            raise EbaySellApiError("eBay return policy response is missing returnPolicyId")
        return policy_id

    async def create_inventory_location(
        self,
        merchant_location_key: str,
        payload: dict[str, Any],
    ) -> None:
        await self._request(
            "POST",
            f"/sell/inventory/v1/location/{quote(merchant_location_key, safe='')}",
            json_body=payload,
            expected={201, 204},
        )

    async def get_notification_config(self) -> dict[str, Any] | None:
        return await self._request(
            "GET",
            "/commerce/notification/v1/config",
            expected={200, 404},
        )

    async def put_notification_config(self, alert_email: str) -> None:
        await self._request(
            "PUT",
            "/commerce/notification/v1/config",
            json_body={"alertEmail": alert_email},
            expected={204},
        )

    async def get_notification_destinations(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/commerce/notification/v1/destination",
            params={"limit": 100},
        )
        rows = [] if payload is None else payload.get("destinations", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError("eBay destinations response has an invalid shape")
        return rows

    async def create_notification_destination(
        self,
        *,
        name: str,
        endpoint: str,
        verification_token: str,
    ) -> str:
        response = await self._request(
            "POST",
            "/commerce/notification/v1/destination",
            json_body={
                "name": name,
                "status": "ENABLED",
                "deliveryConfig": {
                    "endpoint": endpoint,
                    "verificationToken": verification_token,
                },
            },
            expected={201},
        )
        destination_id = str((response or {}).get("destinationId") or "").strip()
        if destination_id:
            return destination_id

        # eBay REST create calls can return 201 with no JSON body and identify
        # the created resource via Location. Our shared request helper
        # deliberately does not expose raw headers, so reconcile the new
        # destination through the official collection endpoint instead of
        # treating a successful 201 as failure.
        for attempt in range(4):
            destinations = await self.get_notification_destinations()
            for row in destinations:
                delivery = row.get("deliveryConfig")
                if not isinstance(delivery, dict):
                    continue
                if str(delivery.get("endpoint") or "").strip() != endpoint.strip():
                    continue
                destination_id = str(row.get("destinationId") or "").strip()
                if destination_id:
                    return destination_id
            if attempt < 3:
                await asyncio.sleep(0.25 * (attempt + 1))
        raise EbaySellApiError(
            "eBay created the notification destination but it could not be reconciled"
        )

    async def update_notification_destination(
        self,
        destination_id: str,
        *,
        name: str,
        endpoint: str,
        verification_token: str,
    ) -> None:
        await self._request(
            "PUT",
            f"/commerce/notification/v1/destination/{quote(destination_id, safe='')}",
            json_body={
                "name": name,
                "status": "ENABLED",
                "deliveryConfig": {
                    "endpoint": endpoint,
                    "verificationToken": verification_token,
                },
            },
            expected={204},
        )

    async def get_notification_topics(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/commerce/notification/v1/topic",
            params={"limit": 100},
        )
        rows = [] if payload is None else payload.get("topics", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError("eBay notification topics response has an invalid shape")
        return rows

    async def get_notification_subscriptions(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/commerce/notification/v1/subscription",
            params={"limit": 100},
        )
        rows = [] if payload is None else payload.get("subscriptions", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError("eBay subscriptions response has an invalid shape")
        return rows

    async def create_notification_subscription(
        self,
        *,
        topic_id: str,
        destination_id: str,
        schema_version: str,
    ) -> str:
        response = await self._request(
            "POST",
            "/commerce/notification/v1/subscription",
            json_body={
                "topicId": topic_id,
                "destinationId": destination_id,
                "status": "ENABLED",
                "payload": {
                    "deliveryProtocol": "HTTPS",
                    "format": "JSON",
                    "schemaVersion": schema_version,
                },
            },
            expected={201},
        )
        subscription_id = str((response or {}).get("subscriptionId") or "").strip()
        if subscription_id:
            return subscription_id

        for attempt in range(4):
            subscriptions = await self.get_notification_subscriptions()
            for row in subscriptions:
                if str(row.get("topicId") or "").strip() != topic_id.strip():
                    continue
                if str(row.get("destinationId") or "").strip() != destination_id.strip():
                    continue
                subscription_id = str(row.get("subscriptionId") or "").strip()
                if subscription_id:
                    return subscription_id
            if attempt < 3:
                await asyncio.sleep(0.25 * (attempt + 1))
        raise EbaySellApiError(
            "eBay created the notification subscription but it could not be reconciled"
        )

    async def enable_notification_subscription(self, subscription_id: str) -> None:
        await self._request(
            "POST",
            f"/commerce/notification/v1/subscription/{quote(subscription_id, safe='')}/enable",
            json_body={},
            expected={204},
        )

    async def get_notification_subscription(self, subscription_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/commerce/notification/v1/subscription/{quote(subscription_id, safe='')}",
        )
        if payload is None:
            raise EbaySellApiError("eBay subscription response was empty")
        return payload

    async def test_notification_subscription(self, subscription_id: str) -> None:
        await self._request(
            "POST",
            f"/commerce/notification/v1/subscription/{quote(subscription_id, safe='')}/test",
            json_body={},
            expected={204},
        )

    async def get_payment_policies(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/sell/account/v1/payment_policy",
            params={"marketplace_id": self._marketplace_id},
        )
        rows = [] if payload is None else payload.get("paymentPolicies", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError("eBay payment policies response has an invalid shape")
        return rows

    async def get_fulfillment_policies(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/sell/account/v1/fulfillment_policy",
            params={"marketplace_id": self._marketplace_id},
        )
        rows = [] if payload is None else payload.get("fulfillmentPolicies", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError("eBay fulfillment policies response has an invalid shape")
        return rows

    async def get_return_policies(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/sell/account/v1/return_policy",
            params={"marketplace_id": self._marketplace_id},
        )
        rows = [] if payload is None else payload.get("returnPolicies", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError("eBay return policies response has an invalid shape")
        return rows

    async def get_inventory_locations(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/sell/inventory/v1/location",
            params={"limit": 200, "offset": 0},
        )
        rows = [] if payload is None else payload.get("locations", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError("eBay inventory locations response has an invalid shape")
        return rows

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

    async def get_shipping_fulfillments(
        self,
        order_id: str,
    ) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            f"/sell/fulfillment/v1/order/{quote(order_id, safe='')}/shipping_fulfillment",
        )
        rows = [] if payload is None else payload.get("fulfillments", [])
        if rows is None:
            return []
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EbaySellApiError(
                "eBay shipping fulfillments response has an invalid shape"
            )
        return rows

    async def get_shipping_fulfillment(
        self,
        order_id: str,
        fulfillment_id: str,
    ) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/sell/fulfillment/v1/order/{quote(order_id, safe='')}/"
            f"shipping_fulfillment/{quote(fulfillment_id, safe='')}",
        )
        if payload is None:
            raise EbaySellApiError("eBay shipping fulfillment response was empty")
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
