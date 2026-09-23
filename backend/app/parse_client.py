from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx


PARSE_API_BASE_URL = "https://api.parse.bot"
logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True, slots=True)
class ParseApiError(Exception):
    """Sanitised Parse/provider error safe to persist in ingestion logs."""

    detail: str
    status_code: int | None = None
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def _response_shape_diagnostics(data: dict[str, Any]) -> tuple[list[str], dict[str, int], list[str]]:
    """Return a secret-safe summary of a Parse response for live diagnostics.

    We deliberately keep this to field names, list sizes and a few listing titles.
    API keys, request headers, URLs and raw response bodies are never logged.
    """

    keys = sorted(str(key) for key in data)
    list_counts: dict[str, int] = {}
    sample_titles: list[str] = []

    for key, value in data.items():
        if not isinstance(value, list):
            continue
        list_counts[str(key)] = len(value)
        if sample_titles:
            continue
        for item in value[:5]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            if isinstance(title, str) and title.strip():
                sample_titles.append(title.strip()[:200])

    return keys, list_counts, sample_titles


def _request_headers(*, api_key: str, snapshot_version: int | None) -> dict[str, str]:
    """Build Parse headers without exposing or implicitly pinning a stale release.

    Parse marketplace APIs may be called against the current canonical release by
    omitting ``API-Snapshot-Version``. Adapters can still deliberately pin a known
    good release by passing an explicit positive snapshot version.
    """

    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
    }
    if snapshot_version is not None:
        if snapshot_version < 1:
            raise ValueError("snapshot_version must be positive")
        headers["API-Snapshot-Version"] = str(snapshot_version)
    return headers


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
        snapshot_version: int | None = None,
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
        snapshot_version: int | None = None,
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
        snapshot_version: int | None,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        try:
            UUID(scraper_id)
        except (ValueError, TypeError) as exc:
            raise ValueError("scraper_id must be a UUID") from exc
        if not endpoint or not endpoint.replace("_", "").isalnum():
            raise ValueError("endpoint must contain only letters, numbers and underscores")

        url = f"{self._base_url}/scraper/{scraper_id}/{endpoint}"
        headers = _request_headers(api_key=self._api_key, snapshot_version=snapshot_version)

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

        keys, list_counts, sample_titles = _response_shape_diagnostics(data)
        logger.warning(
            "parse_response_shape endpoint=%s snapshot=%s keys=%s list_counts=%s sample_titles=%s",
            endpoint,
            snapshot_version if snapshot_version is not None else "CURRENT",
            keys,
            list_counts,
            sample_titles,
        )
        return data
