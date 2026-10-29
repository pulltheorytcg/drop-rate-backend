from __future__ import annotations

from typing import Any

import httpx


CARDTRADER_BASE_URL = "https://api.cardtrader.com/api/v2"


class CardTraderApiError(RuntimeError):
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


class CardTraderClient:
    """Minimal read-only CardTrader API client for identity/media resolution."""

    def __init__(
        self,
        *,
        api_token: str,
        timeout_seconds: float = 20.0,
        base_url: str = CARDTRADER_BASE_URL,
    ) -> None:
        token = api_token.strip()
        if not token:
            raise ValueError("CardTrader API token is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)

    async def app_info(self) -> dict[str, Any]:
        payload = await self._request("/info")
        if not isinstance(payload, dict):
            raise CardTraderApiError("CardTrader /info returned an invalid response")
        return payload

    async def list_games(self) -> list[dict[str, Any]]:
        return self._as_list(await self._request("/games"), "games")

    async def list_categories(
        self,
        *,
        game_id: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int | bool] | None = None
        if game_id is not None:
            if game_id <= 0:
                raise ValueError("game_id must be positive")
            params = {"game_id": game_id}
        return self._as_list(
            await self._request("/categories", params=params),
            "categories",
        )

    async def list_expansions(self) -> list[dict[str, Any]]:
        return self._as_list(await self._request("/expansions"), "expansions")

    async def list_blueprints(self, *, expansion_id: int) -> list[dict[str, Any]]:
        if expansion_id <= 0:
            raise ValueError("expansion_id must be positive")
        payload = await self._request(
            "/blueprints/export",
            params={"expansion_id": expansion_id},
        )
        return self._as_list(payload, "blueprints")

    async def list_marketplace_products(
        self,
        *,
        blueprint_id: int,
        language: str | None = None,
        foil: bool | None = None,
    ) -> list[dict[str, Any]]:
        if blueprint_id <= 0:
            raise ValueError("blueprint_id must be positive")
        params: dict[str, str | int | bool] = {"blueprint_id": blueprint_id}
        if language:
            params["language"] = language.strip().lower()
        if foil is not None:
            params["foil"] = foil
        payload = await self._request("/marketplace/products", params=params)
        return self._marketplace_list(payload, blueprint_id=blueprint_id)

    async def list_marketplace_expansion_products(
        self,
        *,
        expansion_id: int,
        language: str | None = None,
        foil: bool | None = None,
    ) -> dict[int, list[dict[str, Any]]]:
        """Read the official expansion-wide marketplace feed in a single request.

        The response maps blueprint IDs to their live offers.  A
        per-blueprint search for a 300-card release would use 300 requests;
        this endpoint uses one without weakening printing identity checks.
        """
        if type(expansion_id) is not int or expansion_id <= 0:
            raise ValueError("expansion_id must be positive")
        params: dict[str, str | int | bool] = {"expansion_id": expansion_id}
        if language:
            lang = language.strip().lower()
            if len(lang) != 2 or not lang.isalpha():
                raise ValueError("language must be a two-letter locale")
            params["language"] = lang
        if foil is not None:
            params["foil"] = foil
        payload = await self._request("/marketplace/products", params=params)
        if not isinstance(payload, dict) or len(payload) > 10_000:
            raise CardTraderApiError("CardTrader expansion marketplace returned an invalid map")
        result: dict[int, list[dict[str, Any]]] = {}
        total_offers = 0
        for raw_id, rows in payload.items():
            if not isinstance(raw_id, str) or not raw_id.isdecimal():
                raise CardTraderApiError("CardTrader expansion marketplace contains an invalid blueprint id")
            blueprint_id = int(raw_id)
            # The published reference describes 25 offers per blueprint, but
            # the live endpoint sometimes returns more. Retain complete,
            # bounded groups instead of dropping an entire large expansion.
            if blueprint_id <= 0 or not isinstance(rows, list) or len(rows) > 2500:
                raise CardTraderApiError("CardTrader expansion marketplace contains invalid offers")
            total_offers += len(rows)
            if total_offers > 100_000:
                raise CardTraderApiError("CardTrader expansion marketplace exceeds safety limit")
            if not all(isinstance(row, dict) and row.get("blueprint_id") == blueprint_id
                       for row in rows):
                raise CardTraderApiError("CardTrader expansion marketplace contains mismatched offers")
            result[blueprint_id] = rows
        return result

    @staticmethod
    def _as_list(payload: object, label: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict) and isinstance(payload.get("array"), list):
            rows = payload["array"]
        else:
            raise CardTraderApiError(
                f"CardTrader {label} response has an unsupported list wrapper"
            )
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _marketplace_list(
        payload: object,
        *,
        blueprint_id: int,
    ) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            if isinstance(payload.get("array"), list):
                rows = payload["array"]
            else:
                rows = payload.get(str(blueprint_id))
                if rows is None:
                    rows = payload.get(blueprint_id)
                if not isinstance(rows, list):
                    raise CardTraderApiError(
                        "CardTrader marketplace response does not contain the requested blueprint"
                    )
        else:
            raise CardTraderApiError(
                "CardTrader marketplace response has an unsupported shape"
            )
        return [row for row in rows if isinstance(row, dict)]

    async def _request(
        self,
        path: str,
        *,
        params: dict[str, str | int | bool] | None = None,
    ) -> object:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}{path}",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise CardTraderApiError(
                "CardTrader request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise CardTraderApiError(
                "CardTrader request failed",
                retryable=True,
            ) from exc

        if response.status_code == 429:
            raise CardTraderApiError(
                "CardTrader rate limit reached",
                status_code=429,
                retryable=True,
            )
        if response.status_code in {401, 403}:
            raise CardTraderApiError(
                "CardTrader credentials were rejected",
                status_code=response.status_code,
            )
        if response.status_code == 404:
            raise CardTraderApiError(
                "CardTrader resource was not found",
                status_code=404,
            )
        if 400 <= response.status_code < 500:
            raise CardTraderApiError(
                "CardTrader request was rejected",
                status_code=response.status_code,
            )
        if response.status_code >= 500:
            raise CardTraderApiError(
                "CardTrader service is unavailable",
                status_code=response.status_code,
                retryable=True,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise CardTraderApiError("CardTrader returned invalid JSON") from exc
