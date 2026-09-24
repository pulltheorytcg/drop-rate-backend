from __future__ import annotations

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
    """Minimal server-side Shopify GraphQL Admin API client.

    This client never exposes the Admin API access token in responses or errors.
    Publishing mutations are intentionally not implemented in this foundation.
    """

    def __init__(
        self,
        *,
        shop_domain: str,
        access_token: str,
        api_version: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        domain = shop_domain.strip().casefold()
        token = access_token.strip()
        version = api_version.strip()
        if not domain.endswith(".myshopify.com"):
            raise ValueError("A canonical Shopify myshopify.com domain is required")
        if not token:
            raise ValueError("Shopify Admin API access token is required")
        if not version:
            raise ValueError("Shopify API version is required")
        self._shop_domain = domain
        self._access_token = token
        self._api_version = version
        self._timeout = timeout_seconds

    @property
    def shop_domain(self) -> str:
        return self._shop_domain

    @property
    def api_version(self) -> str:
        return self._api_version

    async def graphql(
        self,
        *,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("Shopify GraphQL query is required")
        url = (
            f"https://{self._shop_domain}/admin/api/"
            f"{self._api_version}/graphql.json"
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    headers={
                        "X-Shopify-Access-Token": self._access_token,
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
        errors = payload.get("errors")
        if errors:
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
