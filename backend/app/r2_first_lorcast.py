"""Bounded, English metadata-only reads of Lorcast's documented public API.

Provider access reviewed 2026-11-04 at https://lorcast.com/docs/api and
https://lorcast.com/docs/api/sets: programmatic ingestion and local caching are
documented. This is NOT a licence to Disney/Ravensburger artwork. Keep catalogue
lookup free, attribute Lorcast, and do not resell the provider's dataset/API.

Only factual printing identity leaves this module. Artwork URLs, rules/flavour
text, prices, authentication and arbitrary source URLs are never persisted or
followed. No database, R2, inventory, publication or valuation writes occur.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import hashlib
import re

import httpx

from .r2_first_sources import (
    FetchedSource,
    SourceDescriptor,
    SourceError,
    SourcePermissionError,
    _assert_public_client,
    _date,
    _decode_json,
    _deduplicate,
    _download,
    _language,
    _record,
    _text,
)


LORCAST_API = "https://api.lorcast.com/v0"
LORCAST_SETS_URL = LORCAST_API + "/sets"
MAX_SET_LIST_BYTES = 256_000
MAX_RESPONSE_BYTES = 8_000_000
MAX_TOTAL_BYTES = 32_000_000
MAX_REQUESTS = 128
MAX_CARDS_PER_SET = 10_000
MAX_TOTAL_CARDS = 100_000
TOTAL_TIMEOUT_SECONDS = 120
REQUEST_DELAY_SECONDS = 0.25


def _identifier(value, prefix: str) -> str:
    # Fixed-length provider IDs are the only response-derived URL component.
    if not isinstance(value, str) or not re.fullmatch(prefix + r"_[0-9a-f]{32}", value):
        raise SourceError("Invalid Lorcast provider identifier")
    return value


def _set_code(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise SourceError("Invalid Lorcast set code")
    return value


def _sets(value) -> dict[str, dict]:
    if not isinstance(value, list) or not value or len(value) + 1 > MAX_REQUESTS:
        raise SourceError("Invalid or oversized Lorcast set snapshot")
    result, codes = {}, set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise SourceError("Invalid Lorcast set row")
        identifier = _identifier(raw.get("id"), "set")
        code = _set_code(raw.get("code"))
        name = _text(raw.get("name"), "set name")
        # Validate supplied dates without assigning a set's date to an undated
        # individual printing. Missing card dates remain unknown.
        _date(raw.get("released_at"))
        _date(raw.get("prereleased_at"))
        if identifier in result or code in codes:
            raise SourceError("Duplicate Lorcast set identity")
        result[identifier] = {"id": identifier, "code": code, "name": name}
        codes.add(code)
    return result


def _set_cards(value, source_set: dict) -> list[dict]:
    if not isinstance(value, list) or not value or len(value) > MAX_CARDS_PER_SET:
        raise SourceError("Invalid or empty Lorcast set-card snapshot")
    records = []
    for card in value:
        if not isinstance(card, Mapping):
            raise SourceError("Invalid Lorcast card row")
        printing_id = _identifier(card.get("id"), "crd")
        name = _text(card.get("name"), "card name")
        version = _text(card.get("version"), "card version", optional=True)
        language_code = card.get("lang")
        if not isinstance(language_code, str) or language_code not in {"en", "fr", "de", "it"}:
            raise SourceError("Invalid Lorcast printing language")
        if "collector_number" not in card:
            raise SourceError("Missing Lorcast collector number field")
        number = _text(card["collector_number"], "card number", optional=True, max_length=160)
        card_set = card.get("set")
        if not isinstance(card_set, Mapping):
            raise SourceError("Missing Lorcast printing set")
        if (_identifier(card_set.get("id"), "set") != source_set["id"]
                or _set_code(card_set.get("code")) != source_set["code"]
                or _text(card_set.get("name"), "set name") != source_set["name"]):
            raise SourceError("Lorcast printing belongs to an unexpected set")
        row = _record(
            "lorcast", "DISNEY_LORCANA", "English", "lorcast:" + printing_id,
            name=name + (" - " + version if version else ""),
            set_id=source_set["code"], set_name=source_set["name"],
            card_number=number, rarity=card.get("rarity"),
            # Rarity, image variants, and price fields are not finish evidence.
            finish=None, release_date=card.get("released_at"),
            # Preserve the exact source set ID as well as its displayed code.
            source_url=LORCAST_SETS_URL + "/" + source_set["id"] + "/cards",
        )
        if language_code == "en":
            records.append(row)
    return records


def normalize_lorcast(payload, language: str = "English") -> list[dict]:
    """Normalize a complete offline bundle without fetching or mutating it.

    Bundle shape: ``{"sets": [...], "cards_by_set": {set_id: [card, ...]}}``.
    This internal bundle joins the documented set list and per-set card arrays;
    it is not a claimed provider bulk endpoint. Every enumerated set must have
    exactly one supplied array. Non-English cards are excluded, not relabelled.
    """
    language_code, _ = _language(language)
    if language_code != "en":
        raise SourceError("Lorcast metadata import supports English-only")
    if not isinstance(payload, Mapping) or set(payload) != {"sets", "cards_by_set"}:
        raise SourceError("Invalid Lorcast offline snapshot")
    sets = _sets(payload["sets"])
    by_set = payload["cards_by_set"]
    if not isinstance(by_set, Mapping) or set(by_set) != set(sets):
        raise SourceError("Incomplete Lorcast set-card snapshot")
    records, total_cards = [], 0
    for identifier in sorted(sets):
        cards = by_set[identifier]
        rows = _set_cards(cards, sets[identifier])
        total_cards += len(cards)
        if total_cards > MAX_TOTAL_CARDS:
            raise SourceError("Lorcast snapshot exceeds the total card bound")
        records.extend(rows)
    return _deduplicate(records)


def _validate_descriptor(descriptor: SourceDescriptor) -> int:
    if (descriptor.provider != "lorcast" or descriptor.system_code != "DISNEY_LORCANA"
            or descriptor.download_url != LORCAST_SETS_URL
            or descriptor.source_url != LORCAST_SETS_URL):
        raise SourceError("Unexpected Lorcast source descriptor")
    if descriptor.permission_status != "METADATA_ACCESS_DOCUMENTED":
        raise SourcePermissionError("Lorcast lacks reviewed metadata-access approval")
    if (isinstance(descriptor.max_bytes, bool) or not isinstance(descriptor.max_bytes, int)
            or descriptor.max_bytes < 1):
        raise SourceError("Invalid Lorcast byte budget")
    return min(descriptor.max_bytes, MAX_TOTAL_BYTES)


async def fetch_lorcast(client: httpx.AsyncClient, descriptor: SourceDescriptor) -> FetchedSource:
    """Fetch one complete bounded snapshot; never return a partial success.

    The shared dispatcher still owns approval, refresh policy and persistence.
    Public GETs are sequential with a 250ms gap, and 403/429/redirect/transport or
    schema failures stop immediately. Incoming cookies are never sent onward.
    The digest frames each fixed locator and its exact response bytes, while
    only whitelisted metadata is returned to the caller.
    """
    byte_budget = _validate_descriptor(descriptor)
    _assert_public_client(client)
    consumed, calls = 0, 0
    digest = hashlib.sha256(b"DropRate/Lorcast/metadata-v1\x00")

    async def read(url: str, response_limit: int):
        nonlocal consumed, calls
        if calls >= MAX_REQUESTS:
            raise SourceError("Lorcast snapshot exceeds the request bound")
        remaining = byte_budget - consumed
        if remaining <= 0:
            raise SourceError("Lorcast snapshot exceeds the total byte bound")
        if calls:
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
        # A Set-Cookie received on a prior public response cannot contaminate a
        # subsequent request. Reject instead of altering the caller's client.
        _assert_public_client(client)
        calls += 1
        content = await _download(client, url, min(response_limit, remaining))
        consumed += len(content)
        locator = url.encode("ascii")
        digest.update(len(locator).to_bytes(4, "big"))
        digest.update(locator)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        return _decode_json(content)

    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
            index = await read(LORCAST_SETS_URL, MAX_SET_LIST_BYTES)
            # The documented v0 index is a complete results wrapper. A new
            # pagination shape must be reviewed, never treated as complete.
            if not isinstance(index, Mapping) or set(index) != {"results"}:
                raise SourceError("Unexpected or paginated Lorcast set index")
            sets = _sets(index["results"])
            records, total_cards = [], 0
            for identifier in sorted(sets):
                cards = await read(LORCAST_SETS_URL + "/" + identifier + "/cards", MAX_RESPONSE_BYTES)
                rows = _set_cards(cards, sets[identifier])
                total_cards += len(cards)
                if total_cards > MAX_TOTAL_CARDS:
                    raise SourceError("Lorcast snapshot exceeds the total card bound")
                records.extend(rows)
            records = _deduplicate(records)
    except TimeoutError as exc:
        raise SourceError("Lorcast exceeded its total download time bound") from exc
    source_sha256 = digest.hexdigest()
    return FetchedSource(
        descriptor.provider, descriptor.system_code, descriptor.source_url,
        "sha256:" + source_sha256, source_sha256, records,
    )
