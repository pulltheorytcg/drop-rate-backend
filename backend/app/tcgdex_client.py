from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Mapping

import httpx


TCGDEX_BASE_URL = "https://api.tcgdex.net/v2"
TCGDEX_SOURCE_URL = "https://tcgdex.dev"
TCGDEX_DATABASE_URL = "https://github.com/tcgdex/cards-database"
TCGDEX_JP_SET_TRANSLATIONS_URL = (
    "https://raw.githubusercontent.com/tcgdex/cards-database/master/"
    "scripts/utils-data/jp_set_translations.ts"
)


class TcgDexApiError(RuntimeError):
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


def _number_equivalent(left: object, right: object) -> bool:
    def canonical(value: object) -> str:
        text = str(value or "").strip().upper()
        chunks = re.split(r"([/-])", text)
        out: list[str] = []
        for chunk in chunks:
            if chunk.isdigit():
                out.append(str(int(chunk)))
            else:
                out.append(chunk)
        return "".join(out)

    return canonical(left) == canonical(right)


def _card_number_parts(value: object) -> tuple[str, int | None]:
    text = str(value or "").strip()
    if "/" not in text:
        return text, None
    local, total = text.split("/", 1)
    try:
        official = int(total)
    except ValueError:
        official = None
    return local.strip(), official


def _variant_key(value: object) -> str | None:
    variant = _norm(value)
    if variant in {"", "normal", "base", "regular"}:
        return "normal"
    if variant in {"holofoil", "holo", "foil"}:
        return "holo"
    if variant in {"reverse holofoil", "reverse holo", "reverse foil"}:
        return "reverse"
    return None


def _variant_available(variants: object, key: str) -> bool:
    if isinstance(variants, Mapping):
        return variants.get(key) is True
    if isinstance(variants, list):
        return any(
            isinstance(item, Mapping) and _norm(item.get("type")) == key
            for item in variants
        )
    return False


class TcgDexClient:
    """No-key TCGdex client used only for deterministic Pokémon media lookup."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        base_url: str = TCGDEX_BASE_URL,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._jp_aliases: dict[str, str] | None = None
        self._jp_aliases_expires_at = 0.0
        self._jp_aliases_lock = asyncio.Lock()

    async def resolve_card(
        self,
        *,
        language: str,
        set_name: str,
        card_number: str,
        variant: str,
    ) -> dict[str, Any]:
        normalized_language = _norm(language)
        if normalized_language in {"japanese", "jp", "ja"}:
            return await self.resolve_japanese_card(
                set_name=set_name,
                card_number=card_number,
                variant=variant,
            )
        if normalized_language in {"english", "en"}:
            return await self.resolve_english_card(
                set_name=set_name,
                card_number=card_number,
                variant=variant,
            )
        return {
            "resolved": False,
            "reason": "TCGdex language is not supported by this resolver",
        }

    async def resolve_english_card(
        self,
        *,
        set_name: str,
        card_number: str,
        variant: str,
    ) -> dict[str, Any]:
        local_id, official_count = _card_number_parts(card_number)
        if not local_id:
            return {"resolved": False, "reason": "Pokémon card number is missing"}
        if not set_name.strip():
            return {"resolved": False, "reason": "Pokémon set name is missing"}

        variant_key = _variant_key(variant)
        if variant_key is None:
            return {
                "resolved": False,
                "reason": "Pokémon variant is not mapped to a TCGdex finish",
            }

        sets = await self._get_json(
            "/en/sets",
            params={"name": set_name.strip()},
        )
        if not isinstance(sets, list):
            raise TcgDexApiError("TCGdex set search returned an invalid response")

        exact_sets: list[Mapping[str, Any]] = []
        for item in sets:
            if not isinstance(item, Mapping):
                continue
            if _norm(item.get("name")) != _norm(set_name):
                continue
            if official_count is not None:
                card_count = item.get("cardCount")
                if (
                    isinstance(card_count, Mapping)
                    and isinstance(card_count.get("official"), int)
                    and card_count.get("official") != official_count
                ):
                    continue
            exact_sets.append(item)

        if len(exact_sets) != 1:
            return {
                "resolved": False,
                "reason": "no exact TCGdex English set match",
            }
        set_id = str(exact_sets[0].get("id") or "").strip()
        if not set_id:
            return {
                "resolved": False,
                "reason": "TCGdex English set is missing a stable ID",
            }

        card: Mapping[str, Any] | None = None
        attempts = [local_id]
        stripped = local_id.lstrip("0") or "0"
        if stripped != local_id:
            attempts.append(stripped)

        for candidate_local_id in attempts:
            try:
                payload = await self._get_json(
                    f"/en/sets/{set_id}/{candidate_local_id}",
                )
            except TcgDexApiError as exc:
                if exc.status_code == 404:
                    continue
                raise
            if isinstance(payload, Mapping):
                card = payload
                break

        if card is None:
            return {"resolved": False, "reason": "English TCGdex card not found"}

        provider_set = card.get("set")
        if (
            not isinstance(provider_set, Mapping)
            or str(provider_set.get("id") or "").casefold() != set_id.casefold()
        ):
            return {"resolved": False, "reason": "TCGdex card set identity mismatch"}

        if official_count is not None:
            provider_count = provider_set.get("cardCount")
            if (
                isinstance(provider_count, Mapping)
                and isinstance(provider_count.get("official"), int)
                and provider_count.get("official") != official_count
            ):
                return {
                    "resolved": False,
                    "reason": "TCGdex English set card-count mismatch",
                }

        if not _number_equivalent(card.get("localId"), local_id):
            return {"resolved": False, "reason": "TCGdex card number mismatch"}

        variants = card.get("variants")
        if not _variant_available(variants, variant_key):
            return {
                "resolved": False,
                "reason": f"TCGdex card does not support {variant_key} finish",
            }

        image_base = str(card.get("image") or "").strip()
        if not image_base.startswith("https://assets.tcgdex.net/"):
            return {"resolved": False, "reason": "TCGdex card has no trusted image asset"}

        provider_id = str(card.get("id") or "").strip()
        if not provider_id:
            return {"resolved": False, "reason": "TCGdex card is missing a stable ID"}

        return {
            "resolved": True,
            "provider": "TCGdex",
            "provider_id": provider_id,
            "image_url": f"{image_base.rstrip('/')}/high.webp",
            "source_reference": f"https://api.tcgdex.net/v2/en/cards/{provider_id}",
            "provider_set_id": set_id,
            "provider_local_id": card.get("localId"),
            "provider_name": card.get("name"),
            "provider_rarity": card.get("rarity"),
            "provider_category": card.get("category"),
            "provider_types": card.get("types") or [],
            "finish_key": variant_key,
        }

    async def resolve_japanese_card(
        self,
        *,
        set_name: str,
        card_number: str,
        variant: str,
    ) -> dict[str, Any]:
        local_id, official_count = _card_number_parts(card_number)
        if not local_id:
            return {"resolved": False, "reason": "Pokémon card number is missing"}
        if not set_name.strip():
            return {"resolved": False, "reason": "Pokémon set name is missing"}

        variant_key = _variant_key(variant)
        if variant_key is None:
            return {
                "resolved": False,
                "reason": "Pokémon variant is not mapped to a TCGdex finish",
            }

        set_id = await self._japanese_set_id(
            set_name=set_name,
            official_count=official_count,
        )
        if set_id is None:
            return {"resolved": False, "reason": "no exact TCGdex Japanese set match"}

        card: Mapping[str, Any] | None = None
        attempts = [local_id]
        stripped = local_id.lstrip("0") or "0"
        if stripped != local_id:
            attempts.append(stripped)

        for candidate_local_id in attempts:
            try:
                payload = await self._get_json(
                    f"/ja/sets/{set_id}/{candidate_local_id}",
                )
            except TcgDexApiError as exc:
                if exc.status_code == 404:
                    continue
                raise
            if isinstance(payload, Mapping):
                card = payload
                break

        if card is None:
            return {"resolved": False, "reason": "Japanese TCGdex card not found"}

        provider_set = card.get("set")
        if (
            not isinstance(provider_set, Mapping)
            or str(provider_set.get("id") or "").casefold() != set_id.casefold()
        ):
            return {"resolved": False, "reason": "TCGdex card set identity mismatch"}
        if official_count is not None:
            provider_count = provider_set.get("cardCount")
            if (
                isinstance(provider_count, Mapping)
                and isinstance(provider_count.get("official"), int)
                and provider_count.get("official") != official_count
            ):
                return {
                    "resolved": False,
                    "reason": "TCGdex Japanese set card-count mismatch",
                }
        if not _number_equivalent(card.get("localId"), local_id):
            return {"resolved": False, "reason": "TCGdex card number mismatch"}

        variants = card.get("variants")
        if not _variant_available(variants, variant_key):
            return {
                "resolved": False,
                "reason": f"TCGdex card does not support {variant_key} finish",
            }

        image_base = str(card.get("image") or "").strip()
        if not image_base.startswith("https://assets.tcgdex.net/"):
            return {"resolved": False, "reason": "TCGdex card has no trusted image asset"}

        provider_id = str(card.get("id") or "").strip()
        if not provider_id:
            return {"resolved": False, "reason": "TCGdex card is missing a stable ID"}

        return {
            "resolved": True,
            "provider": "TCGdex",
            "provider_id": provider_id,
            "image_url": f"{image_base.rstrip('/')}/high.webp",
            "source_reference": f"https://api.tcgdex.net/v2/ja/cards/{provider_id}",
            "provider_set_id": set_id,
            "provider_local_id": card.get("localId"),
            "provider_name": card.get("name"),
            "provider_rarity": card.get("rarity"),
            "provider_category": card.get("category"),
            "provider_types": card.get("types") or [],
            "finish_key": variant_key,
        }

    async def _japanese_set_id(
        self,
        *,
        set_name: str,
        official_count: int | None,
    ) -> str | None:
        aliases = await self._japanese_set_aliases()
        mapped = aliases.get(_norm(set_name))
        if mapped:
            return mapped

        # Fallback for sets that are genuinely shared with the international
        # catalogue. This is not the primary Japanese-set path.
        sets = await self._get_json(
            "/en/sets",
            params={"name": set_name.strip()},
        )
        if not isinstance(sets, list):
            raise TcgDexApiError("TCGdex set search returned an invalid response")

        exact: list[Mapping[str, Any]] = []
        for item in sets:
            if not isinstance(item, Mapping):
                continue
            if _norm(item.get("name")) != _norm(set_name):
                continue
            if official_count is not None:
                card_count = item.get("cardCount")
                if (
                    isinstance(card_count, Mapping)
                    and isinstance(card_count.get("official"), int)
                    and card_count.get("official") != official_count
                ):
                    continue
            exact.append(item)

        if len(exact) != 1:
            return None
        set_id = str(exact[0].get("id") or "").strip()
        return set_id or None

    async def _japanese_set_aliases(self) -> dict[str, str]:
        now = time.monotonic()
        if self._jp_aliases is not None and now < self._jp_aliases_expires_at:
            return self._jp_aliases

        async with self._jp_aliases_lock:
            now = time.monotonic()
            if self._jp_aliases is not None and now < self._jp_aliases_expires_at:
                return self._jp_aliases

            text = await self._get_text_url(TCGDEX_JP_SET_TRANSLATIONS_URL)
            aliases: dict[str, str] = {}
            pattern = re.compile(
                r"\['((?:\\'|[^'])+)',\s*'((?:\\'|[^'])+)'\]"
            )
            for set_id, english_name in pattern.findall(text):
                clean_id = set_id.replace("\\'", "'").strip()
                clean_name = english_name.replace("\\'", "'").strip()
                if clean_id and clean_name:
                    aliases[_norm(clean_name)] = clean_id

            if not aliases:
                raise TcgDexApiError(
                    "TCGdex Japanese set translation map could not be parsed"
                )
            self._jp_aliases = aliases
            self._jp_aliases_expires_at = time.monotonic() + 3600
            return aliases

    async def _get_text_url(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers={"Accept": "text/plain"})
        except httpx.TimeoutException as exc:
            raise TcgDexApiError(
                "TCGdex set translation request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise TcgDexApiError(
                "TCGdex set translation request failed",
                retryable=True,
            ) from exc

        if response.status_code == 429:
            raise TcgDexApiError(
                "TCGdex set translation source rate limit reached",
                status_code=429,
                retryable=True,
            )
        if response.status_code >= 500:
            raise TcgDexApiError(
                "TCGdex set translation source is unavailable",
                status_code=response.status_code,
                retryable=True,
            )
        if response.status_code != 200:
            raise TcgDexApiError(
                "TCGdex set translation source was rejected",
                status_code=response.status_code,
            )
        return response.text

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}{path}",
                    params=params,
                    headers={"Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise TcgDexApiError("TCGdex request timed out", retryable=True) from exc
        except httpx.RequestError as exc:
            raise TcgDexApiError("TCGdex request failed", retryable=True) from exc

        if response.status_code == 404:
            raise TcgDexApiError(
                "TCGdex record was not found",
                status_code=404,
            )
        if response.status_code == 429:
            raise TcgDexApiError(
                "TCGdex rate limit reached",
                status_code=429,
                retryable=True,
            )
        if 400 <= response.status_code < 500:
            raise TcgDexApiError(
                "TCGdex request was rejected",
                status_code=response.status_code,
            )
        if response.status_code >= 500:
            raise TcgDexApiError(
                "TCGdex service is unavailable",
                status_code=response.status_code,
                retryable=True,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise TcgDexApiError("TCGdex returned invalid JSON") from exc
