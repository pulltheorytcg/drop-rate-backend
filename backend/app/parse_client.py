from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx


PARSE_API_BASE_URL = "https://api.parse.bot"


@dataclass(frozen=True, slots=True)
class ParseApiError(Exception):
    """Sanitised Parse/provider error safe to persist in ingestion logs."""

    detail: str
    status_code: int | None = None
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class ParseHttpClient:
    """Minimal async client for Parse marketplace APIs.

    Secrets are supplied by the caller and are never included in exceptions,
    metadata or request URLs. Provider adapters remain responsible for payload
    semantics and normalisation into Drop Rate market observations.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 20.0,
        base_url: str = PARSE_API_BASE_URL,
    ) -> None:
        clean_key = api_key.strip()
        if not clean_key:
            raise ValueError("Parse API key is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._api_key = clean_key
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)

    async def get(
        self,
        *,
        scraper_id: str,
        endpoint: str,
        snapshot_version: int,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            method="GET",
            scraper_id=scraper_id,
            endpoint=endpoint,
            snapshot_version=snapshot_version,
            params=params,
        )

    async def post(
        self,
        *,
        scraper_id: str,
        endpoint: str,
        snapshot_version: int,
        json_body: Any,
    ) -> dict[str, Any]:
        return await self._request(
            method="POST",
            scraper_id=scraper_id,
            endpoint=endpoint,
            snapshot_version=snapshot_version,
            json_body=json_body,
        )

    async def _request(
        self,
        *,
        method: str,
        scraper_id: str,
        endpoint: str,
        snapshot_version: int,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        try:
            UUID(scraper_id)
        except (ValueError, TypeError) as exc:
            raise ValueError("scraper_id must be a UUID") from exc
        if not endpoint or not endpoint.replace("_", "").isalnum():
            raise ValueError("endpoint must contain only letters, numbers and underscores")
        if snapshot_version < 1:
            raise ValueError("snapshot_version must be positive")

        url = f"{self._base_url}/scraper/{scraper_id}/{endpoint}"
        headers = {
            "X-API-Key": self._api_key,
            "API-Snapshot-Version": str(snapshot_version),
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )
        except httpx.TimeoutException as exc:
            raise ParseApiError("Provider request timed out", retryable=True) from exc
        except httpx.RequestError as exc:
            raise ParseApiError("Provider request failed", retryable=True) from exc

        if response.status_code == 429:
            raise ParseApiError("Provider rate limit reached", status_code=429, retryable=True)
        if response.status_code in (401, 403):
            raise ParseApiError("Provider credentials were rejected", status_code=response.status_code)
        if response.status_code == 404:
            raise ParseApiError("Provider record was not found", status_code=404)
        if 400 <= response.status_code < 500:
            raise ParseApiError("Provider request was rejected", status_code=response.status_code)
        if response.status_code >= 500:
            raise ParseApiError("Provider service is unavailable", status_code=response.status_code, retryable=True)

        try:
            payload = response.json()
        except ValueError as exc:
            raise ParseApiError("Provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ParseApiError("Provider returned an invalid response shape")

        status = payload.get("status")
        if status not in (None, "success"):
            raise ParseApiError("Provider returned an unsuccessful response")

        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise ParseApiError("Provider response data must be an object")
        return data
