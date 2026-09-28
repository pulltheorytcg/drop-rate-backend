from __future__ import annotations

from typing import Any

import httpx


TCGGRAPH_BASE_URL = "https://api.tcggraph.com/v1"


class TcgGraphApiError(RuntimeError):
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


class TcgGraphClient:
    """Minimal server-side TCGGraph client.

    The API key is never exposed to the browser. This client returns provider
    payloads only to deterministic adapter code; raw payloads are not persisted.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 20.0,
        base_url: str = TCGGRAPH_BASE_URL,
    ) -> None:
        clean_key = api_key.strip()
        if not clean_key:
            raise ValueError("TCGGraph API key is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = clean_key
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)

    async def list_cards(
        self,
        *,
        game: str,
        collector_number: str,
        language: str,
        set_name: str | None = None,
        name: str | None = None,
        line: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not game.strip():
            raise ValueError("game is required")
        if not collector_number.strip():
            raise ValueError("collector_number is required")
        if not language.strip():
            raise ValueError("language is required")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")

        params: dict[str, str | int] = {
            "game": game.strip(),
            "collectorNumber": collector_number.strip(),
            "language": language.strip(),
            "limit": limit,
        }
        if set_name and set_name.strip():
            params["set"] = set_name.strip()
        if name and name.strip():
            params["name"] = name.strip()
        if line and line.strip():
            params["line"] = line.strip()

        payload = await self._request("/cards", params=params)
        data = payload.get("data")
        if not isinstance(data, list):
            raise TcgGraphApiError("TCGGraph response is missing card data")
        rows: list[dict[str, Any]] = []
        for row in data:
            if isinstance(row, dict):
                rows.append(row)
        return rows

    async def _request(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}{path}",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise TcgGraphApiError(
                "TCGGraph request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise TcgGraphApiError(
                "TCGGraph request failed",
                retryable=True,
            ) from exc

        if response.status_code == 429:
            raise TcgGraphApiError(
                "TCGGraph rate limit reached",
                status_code=429,
                retryable=True,
            )
        if response.status_code in {401, 403}:
            raise TcgGraphApiError(
                "TCGGraph credentials were rejected",
                status_code=response.status_code,
            )
        if response.status_code == 404:
            raise TcgGraphApiError(
                "TCGGraph resource was not found",
                status_code=404,
            )
        if 400 <= response.status_code < 500:
            raise TcgGraphApiError(
                "TCGGraph request was rejected",
                status_code=response.status_code,
            )
        if response.status_code >= 500:
            raise TcgGraphApiError(
                "TCGGraph service is unavailable",
                status_code=response.status_code,
                retryable=True,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise TcgGraphApiError("TCGGraph returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TcgGraphApiError("TCGGraph returned an invalid response shape")
        return payload
