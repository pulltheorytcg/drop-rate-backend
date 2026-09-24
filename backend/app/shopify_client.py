from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


class ShopifyApiError(RuntimeError):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable


class ShopifyAdminClient:
    """Server-side Shopify GraphQL Admin API client using client credentials.

    The app exchanges its Client ID + Client Secret for a short-lived Admin API
    token, caches it in memory, and refreshes it before expiry. Credentials and
    access tokens never leave the server process.
    """

    def __init__(
        self,
        *,
        shop_domain: str,
        client_id: str,
        client_secret: str,
        api_version: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        domain = shop_domain.strip().casefold()
        app_id = client_id.strip()
        app_secret = client_secret.strip()
        version = api_version.strip()

        if not domain.endswith(".myshopify.com"):
            raise ValueError("A canonical Shopify myshopify.com domain is required")
        if not app_id:
            raise ValueError("Shopify Client ID is required")
        if not app_secret:
            raise ValueError("Shopify Client Secret is required")
        if not version:
            raise ValueError("Shopify API version is required")

        self._shop_domain = domain
        self._client_id = app_id
        self._client_secret = app_secret
        self._api_version = version
        self._timeout = timeout_seconds
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def shop_domain(self) -> str:
        return self._shop_domain

    @property
    def api_version(self) -> str:
        return self._api_version

    async def _mint_access_token(self) -> tuple[str, int]:
        url = f"https://{self._shop_domain}/admin/oauth/access_token"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
        except httpx.TimeoutException as exc:
            raise ShopifyApiError(
                "Shopify OAuth token request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ShopifyApiError(
                "Shopify OAuth token request failed",
                retryable=True,
            ) from exc

        if response.status_code != 200:
            raise ShopifyApiError(
                "Shopify OAuth rejected the app credentials or store access",
                status_code=response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ShopifyApiError("Shopify OAuth returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify OAuth returned an invalid response shape")

        token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(token, str) or not token.strip():
            raise ShopifyApiError("Shopify OAuth response is missing an access token")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise ShopifyApiError("Shopify OAuth response has an invalid expiry")
        return token.strip(), expires_in

    async def access_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        async with self._token_lock:
            now = time.monotonic()
            if self._access_token and now < self._token_expires_at:
                return self._access_token

            token, expires_in = await self._mint_access_token()
            self._access_token = token
            # Shopify client-credentials tokens last 24 hours. Refresh at least
            # five minutes before expiry so a token never expires mid-request.
            margin = min(300, max(30, expires_in // 20))
            self._token_expires_at = time.monotonic() + max(1, expires_in - margin)
            return token

    async def graphql(
        self,
        *,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("Shopify GraphQL query is required")

        token = await self.access_token()
        url = (
            f"https://{self._shop_domain}/admin/api/"
            f"{self._api_version}/graphql.json"
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    headers={
                        "X-Shopify-Access-Token": token,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json={"query": query, "variables": variables or {}},
                )
        except httpx.TimeoutException as exc:
            raise ShopifyApiError(
                "Shopify Admin API request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ShopifyApiError(
                "Shopify Admin API request failed",
                retryable=True,
            ) from exc

        if response.status_code != 200:
            raise ShopifyApiError(
                "Shopify Admin API rejected the request",
                status_code=response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ShopifyApiError("Shopify Admin API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ShopifyApiError("Shopify Admin API returned an invalid response shape")
        if payload.get("errors"):
            raise ShopifyApiError("Shopify Admin API returned GraphQL errors")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ShopifyApiError("Shopify Admin API response is missing data")
        return data

    async def probe_shop(self) -> dict[str, Any]:
        data = await self.graphql(
            query="""
            query DropRateShopProbe {
              shop {
                id
                name
                myshopifyDomain
                currencyCode
              }
            }
            """
        )
        shop = data.get("shop")
        if not isinstance(shop, dict):
            raise ShopifyApiError("Shopify shop probe returned an invalid response")
        return {
            "id": shop.get("id"),
            "name": shop.get("name"),
            "myshopify_domain": shop.get("myshopifyDomain"),
            "currency_code": shop.get("currencyCode"),
        }
