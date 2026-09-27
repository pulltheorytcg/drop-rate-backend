from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx


PUNK_RECORDS_RAW_BASE = "https://raw.githubusercontent.com/Kuroro1990/OPTCG/main"
PUNK_RECORDS_REPO_URL = "https://github.com/Kuroro1990/OPTCG"


class PunkRecordsError(RuntimeError):
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


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _base_variant(value: object) -> bool:
    return _norm(value) in {
        "",
        "normal",
        "base",
        "regular",
        "foil",
        "holo",
        "holofoil",
    }


def _explicit_alt_art(name: object) -> bool:
    normalized = _norm(name)
    markers = (
        "parallel",
        "alternate art",
        "alt art",
        "manga",
    )
    return any(marker in normalized for marker in markers)


class PunkRecordsClient:
    """Japanese One Piece static dataset client.

    The provider index is cached in memory to avoid downloading ~700 KB for
    every card lookup. Exact card JSON remains fetched from the versioned repo.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        base_url: str = PUNK_RECORDS_RAW_BASE,
        index_ttl_seconds: int = 900,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if index_ttl_seconds < 60:
            raise ValueError("index_ttl_seconds must be at least 60 seconds")
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._index_ttl = index_ttl_seconds
        self._index: dict[str, Any] | None = None
        self._index_expires_at = 0.0
        self._index_lock = asyncio.Lock()

    async def resolve_japanese_card(
        self,
        *,
        card_number: str,
        variant: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        base_id = str(card_number or "").strip().upper()
        if not base_id:
            return {"resolved": False, "reason": "One Piece card number is missing"}

        if _explicit_alt_art(name):
            return {
                "resolved": False,
                "reason": "One Piece alternate-art card requires explicit provider suffix mapping",
            }
        if not _base_variant(variant):
            return {
                "resolved": False,
                "reason": "One Piece variant requires explicit provider suffix mapping",
            }

        index = await self._cards_index()
        record = index.get(base_id)
        if not isinstance(record, Mapping):
            return {"resolved": False, "reason": "One Piece base card not found in Punk Records"}

        provider_id = str(record.get("card_id") or "").strip()
        pack_id = str(record.get("pack_id") or "").strip()
        if provider_id != base_id:
            return {"resolved": False, "reason": "Punk Records base-card identity mismatch"}
        if not pack_id:
            return {"resolved": False, "reason": "Punk Records record is missing pack ID"}

        card = await self._get_json(
            f"/japanese/cards/{pack_id}/{provider_id}.json"
        )
        if not isinstance(card, Mapping):
            raise PunkRecordsError("Punk Records card response is invalid")
        if str(card.get("id") or "").strip() != provider_id:
            return {"resolved": False, "reason": "Punk Records card JSON identity mismatch"}

        image_url = str(card.get("img_full_url") or "").strip()
        parsed = urlparse(image_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not (
                parsed.hostname == "onepiece-cardgame.com"
                or parsed.hostname.endswith(".onepiece-cardgame.com")
            )
        ):
            return {
                "resolved": False,
                "reason": "Punk Records card image is not on the trusted One Piece host",
            }

        return {
            "resolved": True,
            "provider": "Punk Records",
            "provider_id": provider_id,
            "image_url": image_url,
            "source_reference": (
                f"{PUNK_RECORDS_REPO_URL}/blob/main/"
                f"japanese/cards/{pack_id}/{provider_id}.json"
            ),
            "pack_id": pack_id,
            "provider_name": card.get("name"),
        }

    async def _cards_index(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._index is not None and now < self._index_expires_at:
            return self._index

        async with self._index_lock:
            now = time.monotonic()
            if self._index is not None and now < self._index_expires_at:
                return self._index

            payload = await self._get_json("/japanese/index/cards_by_id.json")
            if not isinstance(payload, dict):
                raise PunkRecordsError("Punk Records index response is invalid")
            self._index = payload
            self._index_expires_at = time.monotonic() + self._index_ttl
            return payload

    async def _get_json(self, path: str) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}{path}",
                    headers={"Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise PunkRecordsError(
                "Punk Records request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise PunkRecordsError(
                "Punk Records request failed",
                retryable=True,
            ) from exc

        if response.status_code == 404:
            raise PunkRecordsError(
                "Punk Records record was not found",
                status_code=404,
            )
        if response.status_code == 429:
            raise PunkRecordsError(
                "Punk Records rate limit reached",
                status_code=429,
                retryable=True,
            )
        if 400 <= response.status_code < 500:
            raise PunkRecordsError(
                "Punk Records request was rejected",
                status_code=response.status_code,
            )
        if response.status_code >= 500:
            raise PunkRecordsError(
                "Punk Records source is unavailable",
                status_code=response.status_code,
                retryable=True,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise PunkRecordsError("Punk Records returned invalid JSON") from exc
