from __future__ import annotations

import asyncio
import base64
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx


EBAY_PRODUCTION_BASE_URL = "https://api.ebay.com"
EBAY_DEFAULT_SCOPE = "https://api.ebay.com/oauth/api_scope"


def _retry_after(response) -> float | None:
    raw = getattr(response, "headers", {}).get("Retry-After")
    if raw is None:
        return None
    try:
        if re.fullmatch(r"[0-9]{1,8}", str(raw)):
            return min(86400.0, float(raw))
        expires = parsedate_to_datetime(str(raw))
        if expires.utcoffset() is not None:
            return max(0.0, min(86400.0, (expires - datetime.now(timezone.utc)).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        pass
    return None


class EbayApiError(RuntimeError):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


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
        before_browse_request: Callable[[], Awaitable[None]] | None = None,
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
        self._before_browse_request = before_browse_request

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
                retry_after_seconds=_retry_after(response),
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
        query: str | None = None,
        gtin: str | None = None,
        limit: int = 50,
        category_id: str | None = None,
        item_location_country: str = "GB",
        fixed_price_only: bool = False,
    ) -> dict[str, Any]:
        if query is not None and not isinstance(query, str):
            raise ValueError("eBay search query must be text")
        if not (isinstance(query, str) and query.strip()) and not gtin:
            raise ValueError("eBay search query or GTIN is required")
        if gtin is not None and (not isinstance(gtin, str) or not re.fullmatch(r"(?:[0-9]{8}|[0-9]{12,14})", gtin)):
            raise ValueError("eBay search GTIN must be a complete numeric identifier")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ValueError("eBay Browse limit must be between 1 and 200")

        params: dict[str, str | int] = {"limit": limit}
        if query and query.strip():
            params["q"] = query.strip()
        if gtin:
            params["gtin"] = gtin
        if category_id:
            params["category_ids"] = category_id.strip()
        filters = []
        if item_location_country:
            country = item_location_country.strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", country):
                raise ValueError("eBay item location must be a two-letter country")
            filters.append(f"itemLocationCountry:{country}")
        if fixed_price_only:
            filters.append("buyingOptions:{FIXED_PRICE}")
        if filters:
            params["filter"] = ",".join(filters)
        return await self._browse_get("/buy/browse/v1/item_summary/search", params=params)

    async def get_item(self, item_id: str, *, fieldgroups: str = "PRODUCT") -> dict[str, Any]:
        """Read one returned REST item ID; never follow a caller-supplied URL."""
        if not isinstance(item_id, str) or not re.fullmatch(r"v1\|[1-9][0-9]{0,19}\|(?:0|[1-9][0-9]{0,19})", item_id):
            raise ValueError("Invalid eBay REST item ID")
        # Browse requires COMPACT to be sent alone. It supplies the listing
        # GTIN and revision; PRODUCT supplies full listing and product facts.
        if not isinstance(fieldgroups, str) or fieldgroups not in {"PRODUCT", "COMPACT"}:
            raise ValueError("Unsupported eBay item field group")
        return await self._browse_get(
            "/buy/browse/v1/item/" + quote(item_id, safe=""),
            params={"fieldgroups": fieldgroups},
        )

    async def _browse_get(self, path: str, *, params: dict[str, str | int]) -> dict[str, Any]:
        token = await self.application_token()
        # The optional caller budget counts actual Browse attempts, including
        # failed HTTP requests, but not cached tokens or OAuth token requests.
        if self._before_browse_request is not None:
            await self._before_browse_request()

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                response = await client.get(
                    EBAY_PRODUCTION_BASE_URL + path,
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
            if response.status_code == 401:
                self._access_token = None
                self._token_expires_at = 0
            raise EbayApiError(
                "eBay Browse request was rejected",
                status_code=response.status_code,
                retryable=retryable,
                retry_after_seconds=_retry_after(response),
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise EbayApiError("eBay Browse returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise EbayApiError("eBay Browse returned an invalid response shape")
        return payload
