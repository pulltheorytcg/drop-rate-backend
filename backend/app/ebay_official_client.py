from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import httpx


EBAY_PRODUCTION_BASE_URL = "https://api.ebay.com"
EBAY_DEFAULT_SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayApiError(RuntimeError):
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


class EbayOfficialClient:
    """Small production eBay OAuth + Browse client.

    Credentials never leave the server process. Application access tokens are
    cached in memory and refreshed shortly before expiry.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        marketplace_id: str = "EBAY_GB",
        timeout_seconds: float = 20.0,
    ) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("eBay client credentials are required")
        if not marketplace_id.strip():
            raise ValueError("eBay marketplace ID is required")
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._marketplace_id = marketplace_id.strip()
        self._timeout = timeout_seconds
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def marketplace_id(self) -> str:
        return self._marketplace_id

    async def _mint_application_token(self) -> tuple[str, int]:
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
                        "grant_type": "client_credentials",
                        "scope": EBAY_DEFAULT_SCOPE,
                    },
                )
        except httpx.TimeoutException as exc:
            raise EbayApiError("eBay OAuth request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EbayApiError("eBay OAuth request failed", retryable=True) from exc

        if response.status_code != 200:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise EbayApiError(
                "eBay OAuth rejected the application credentials or access request",
                status_code=response.status_code,
                retryable=retryable,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise EbayApiError("eBay OAuth returned invalid JSON") from exc

        token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(token, str) or not token.strip():
            raise EbayApiError("eBay OAuth response is missing an access token")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise EbayApiError("eBay OAuth response has an invalid expiry")

        return token.strip(), expires_in

    async def application_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        async with self._token_lock:
            now = time.monotonic()
            if self._access_token and now < self._token_expires_at:
                return self._access_token

            token, expires_in = await self._mint_application_token()
            self._access_token = token
            # Refresh at least 60 seconds before expiry; short-lived test tokens
            # still retain a small safety margin.
            margin = min(60, max(5, expires_in // 10))
            self._token_expires_at = time.monotonic() + max(1, expires_in - margin)
            return token

    async def search_items(
        self,
        *,
        query: str,
        limit: int = 50,
        category_id: str | None = None,
        item_location_country: str = "GB",
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("eBay search query is required")
        if limit < 1 or limit > 200:
            raise ValueError("eBay Browse limit must be between 1 and 200")

        token = await self.application_token()
        params: dict[str, str | int] = {
            "q": query.strip(),
            "limit": limit,
        }
        if category_id:
            params["category_ids"] = category_id.strip()
        if item_location_country:
            params["filter"] = f"itemLocationCountry:{item_location_country.strip().upper()}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{EBAY_PRODUCTION_BASE_URL}/buy/browse/v1/item_summary/search",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-EBAY-C-MARKETPLACE-ID": self._marketplace_id,
                        "Accept": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise EbayApiError("eBay Browse request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EbayApiError("eBay Browse request failed", retryable=True) from exc

        if response.status_code != 200:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise EbayApiError(
                "eBay Browse request was rejected",
                status_code=response.status_code,
                retryable=retryable,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise EbayApiError("eBay Browse returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise EbayApiError("eBay Browse returned an invalid response shape")
        return payload
