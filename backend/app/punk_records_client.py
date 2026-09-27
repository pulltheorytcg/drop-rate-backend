from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx


PUNK_RECORDS_RAW_BASE = "https://raw.githubusercontent.com/Kuroro1990/OPTCG/main"
PUNK_RECORDS_REPO_URL = "https://github.com/Kuroro1990/OPTCG"

LANGUAGE_FOLDERS = {
    "English": "english",
    "Japanese": "japanese",
}


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


def _name_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _base_card_id(provider_id: object) -> str:
    return re.sub(r"_(?:p|r)\d+$", "", str(provider_id or "").strip(), flags=re.I).upper()


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


def _trusted_image_url(value: object) -> str | None:
    image_url = str(value or "").strip()
    parsed = urlparse(image_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not (
            parsed.hostname == "onepiece-cardgame.com"
            or parsed.hostname.endswith(".onepiece-cardgame.com")
        )
    ):
        return None
    return image_url


def _art_treatment(provider_id: str, *, base_id: str) -> str:
    lowered = provider_id.casefold()
    if lowered == base_id.casefold():
        return "Base"
    if re.search(r"_p\d+$", lowered):
        return "Parallel"
    if re.search(r"_r\d+$", lowered):
        return "Reprint"
    return "Unknown"


class PunkRecordsClient:
    """Static One Piece provider client with language-aware candidate discovery."""

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
        self._indices: dict[str, dict[str, Any]] = {}
        self._name_indices: dict[str, dict[str, Any]] = {}
        self._index_expires_at: dict[tuple[str, str], float] = {}
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

        index = await self._cards_index("japanese")
        record = index.get(base_id)
        if not isinstance(record, Mapping):
            return {"resolved": False, "reason": "One Piece base card not found in Punk Records"}

        provider_id = str(record.get("card_id") or "").strip()
        pack_id = str(record.get("pack_id") or "").strip()
        if provider_id != base_id:
            return {"resolved": False, "reason": "Punk Records base-card identity mismatch"}
        if not pack_id:
            return {"resolved": False, "reason": "Punk Records record is missing pack ID"}

        card = await self._card("japanese", pack_id, provider_id)
        if str(card.get("id") or "").strip() != provider_id:
            return {"resolved": False, "reason": "Punk Records card JSON identity mismatch"}

        image_url = _trusted_image_url(card.get("img_full_url"))
        if not image_url:
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

    async def find_japanese_candidates(
        self,
        *,
        card_number: str,
        name: str | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        return await self.find_candidates(
            language="Japanese",
            card_number=card_number,
            name=name,
            limit=limit,
        )

    async def find_candidates(
        self,
        *,
        language: str,
        card_number: str | None = None,
        name: str | None = None,
        cost: int | None = None,
        power: int | None = None,
        card_type: str | None = None,
        colors: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        folder = LANGUAGE_FOLDERS.get(str(language or "").strip())
        if folder is None or limit < 1:
            return []

        index = await self._cards_index(folder)
        candidate_ids: list[str] = []
        base_id = str(card_number or "").strip().upper()

        if base_id:
            candidate_ids = [
                str(key)
                for key in index
                if str(key).upper() == base_id
                or str(key).upper().startswith(f"{base_id}_")
            ]
        elif name:
            name_index = await self._by_name_index(folder)
            wanted = _name_key(name)
            for indexed_name, ids in name_index.items():
                if _name_key(indexed_name) != wanted or not isinstance(ids, list):
                    continue
                candidate_ids.extend(str(value) for value in ids)
        else:
            return []

        wanted_type = _norm(card_type)
        wanted_colors = {_norm(value) for value in (colors or []) if _norm(value)}

        filtered: list[str] = []
        for provider_id in candidate_ids:
            record = index.get(provider_id)
            if not isinstance(record, Mapping):
                continue
            if cost is not None and record.get("cost") is not None and int(record["cost"]) != cost:
                continue
            if power is not None and record.get("power") is not None and int(record["power"]) != power:
                continue
            if wanted_type and _norm(record.get("category")) != wanted_type:
                continue
            provider_colors = {
                _norm(value)
                for value in (record.get("colors") or [])
                if _norm(value)
            }
            if wanted_colors and provider_colors and not wanted_colors.issubset(provider_colors):
                continue
            filtered.append(provider_id)

        def priority(provider_id: str) -> tuple[int, str]:
            lowered = provider_id.casefold()
            root = _base_card_id(provider_id).casefold()
            if lowered == root:
                return (0, lowered)
            if re.search(r"_p\d+$", lowered):
                return (1, lowered)
            if re.search(r"_r\d+$", lowered):
                return (2, lowered)
            return (3, lowered)

        filtered = list(dict.fromkeys(filtered))
        filtered.sort(key=priority)

        results: list[dict[str, Any]] = []
        for provider_id in filtered[:limit]:
            record = index.get(provider_id)
            if not isinstance(record, Mapping):
                continue
            pack_id = str(record.get("pack_id") or "").strip()
            if not pack_id:
                continue
            try:
                card = await self._card(folder, pack_id, provider_id)
            except PunkRecordsError as exc:
                if exc.status_code == 404:
                    continue
                raise

            root_id = _base_card_id(provider_id)
            results.append(
                {
                    "provider": "Punk Records",
                    "provider_id": provider_id,
                    "base_card_id": root_id,
                    "pack_id": pack_id,
                    "language": language,
                    "name": card.get("name") or record.get("name"),
                    "rarity": card.get("rarity") or record.get("rarity"),
                    "card_type": card.get("category") or record.get("category"),
                    "colors": card.get("colors") or record.get("colors") or [],
                    "cost": card.get("cost", record.get("cost")),
                    "power": card.get("power", record.get("power")),
                    "counter": card.get("counter", record.get("counter")),
                    "attributes": card.get("attributes") or [],
                    "types": card.get("types") or [],
                    "effect": card.get("effect") or "",
                    "trigger": card.get("trigger"),
                    "art_treatment": _art_treatment(provider_id, base_id=root_id),
                    "image_url": _trusted_image_url(card.get("img_full_url")),
                    "source_reference": (
                        f"{PUNK_RECORDS_REPO_URL}/blob/main/"
                        f"{folder}/cards/{pack_id}/{provider_id}.json"
                    ),
                }
            )
        return results

    async def _card(self, folder: str, pack_id: str, provider_id: str) -> Mapping[str, Any]:
        card = await self._get_json(
            f"/{folder}/cards/{pack_id}/{provider_id}.json"
        )
        if not isinstance(card, Mapping):
            raise PunkRecordsError("Punk Records card response is invalid")
        return card

    async def _cards_index(self, folder: str = "japanese") -> dict[str, Any]:
        now = time.monotonic()
        key = (folder, "cards")
        cached = self._indices.get(folder)
        if cached is not None and now < self._index_expires_at.get(key, 0.0):
            return cached

        async with self._index_lock:
            now = time.monotonic()
            cached = self._indices.get(folder)
            if cached is not None and now < self._index_expires_at.get(key, 0.0):
                return cached

            payload = await self._get_json(f"/{folder}/index/cards_by_id.json")
            if not isinstance(payload, dict):
                raise PunkRecordsError("Punk Records index response is invalid")
            self._indices[folder] = payload
            self._index_expires_at[key] = now + self._index_ttl
            return payload

    async def _by_name_index(self, folder: str) -> dict[str, Any]:
        now = time.monotonic()
        key = (folder, "names")
        cached = self._name_indices.get(folder)
        if cached is not None and now < self._index_expires_at.get(key, 0.0):
            return cached

        async with self._index_lock:
            now = time.monotonic()
            cached = self._name_indices.get(folder)
            if cached is not None and now < self._index_expires_at.get(key, 0.0):
                return cached

            payload = await self._get_json(f"/{folder}/index/by_name.json")
            if not isinstance(payload, dict):
                raise PunkRecordsError("Punk Records name index response is invalid")
            self._name_indices[folder] = payload
            self._index_expires_at[key] = now + self._index_ttl
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
