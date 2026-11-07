"""DR108: real provider artwork candidates against published R2 exact printings.

Admin-only caller supplies trusted server-side R2 rows, never source URLs.
Five-at-a-time bounded HTTP reads; optional image-byte SHA + dimensions check.
No R2 write, SQL write, rights approval, or marketplace publication.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
from collections.abc import Mapping
from urllib.parse import quote
from uuid import UUID

import httpx
from PIL import Image, UnidentifiedImageError

from .expanded_artwork_pilot import (
    ArtworkPreviewError, _decision, preview_lorcana, preview_yugioh,
)
from .expanded_artwork_mtg import _SCRYFALL_FRONT
from . import r2_first_catalogue as codec

HEADERS = {
    "User-Agent": "DropRateArtworkReview/1.0 (+https://app.droprate.co.uk)",
    "Accept": "application/json",
    "Accept-Encoding": "identity",
}
MAX_JSON_BYTES = 256_000
MAX_IMAGE_BYTES = 4_000_000
MAX_ROWS = 5
YGO_CODE = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
LORCAST_SET = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
LORCAST_NUMBER = re.compile(r"[A-Za-z0-9._-]{1,48}\Z")
MTG_SET = re.compile(r"[A-Z0-9_]{1,16}\Z")
MTG_NUMBER = re.compile(r"[A-Za-z0-9+*.-]{1,48}\Z")
_YGO_IMAGE = re.compile(
    r"https://images\.ygoprodeck\.com/images/cards/[1-9][0-9]{0,11}\.jpg\Z")
_LOR_IMAGE = re.compile(
    r"https://cards\.lorcast\.io/card/digital/(?:normal|large)/"
    r"(crd_[0-9a-f]{32})\.avif\?[0-9]{8,12}\Z")
CONNECTIONS = {
    "YUGIOH": ("ygoprodeck", "YUGIOH"),
    "DISNEY_LORCANA": ("lorcast", "DISNEY_LORCANA"),
    "MAGIC_THE_GATHERING": ("mtgjson", "MAGIC_THE_GATHERING"),
}


class ArtworkSourceUnavailable(RuntimeError):
    pass


async def _bounded_get(client: httpx.AsyncClient, url: str, *, image: bool) -> bytes:
    """The caller constructs URLs from fixed provider origins and validated IDs."""
    budget = MAX_IMAGE_BYTES if image else MAX_JSON_BYTES
    try:
        async with asyncio.timeout(9):
            async with client.stream("GET", url, follow_redirects=False) as response:
                if response.status_code == 429:
                    raise ArtworkSourceUnavailable("PROVIDER_RATE_LIMITED")
                if response.status_code != 200:
                    raise ArtworkSourceUnavailable("PROVIDER_HTTP_UNAVAILABLE")
                media = response.headers.get("content-type", "").split(";", 1)[0].lower()
                allowed = ({"image/jpeg", "image/avif"} if image
                           else {"application/json"})
                if media not in allowed:
                    raise ArtworkSourceUnavailable("INVALID_PROVIDER_CONTENT_TYPE")
                length = response.headers.get("content-length")
                if length is not None and (not length.isdecimal() or int(length) > budget):
                    raise ArtworkSourceUnavailable("PROVIDER_BYTES_EXCEED_LIMIT")
                buffer = bytearray()
                async for piece in response.aiter_bytes():
                    buffer.extend(piece)
                    if len(buffer) > budget:
                        raise ArtworkSourceUnavailable("PROVIDER_BYTES_EXCEED_LIMIT")
                if not buffer:
                    raise ArtworkSourceUnavailable("EMPTY_PROVIDER_BODY")
                return bytes(buffer)
    except (httpx.HTTPError, TimeoutError) as exc:
        raise ArtworkSourceUnavailable("PROVIDER_NETWORK_UNAVAILABLE") from exc


async def _json_get(client: httpx.AsyncClient, url: str) -> dict:
    body = await _bounded_get(client, url, image=False)
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ArtworkSourceUnavailable("INVALID_PROVIDER_JSON") from exc
    if not isinstance(value, dict):
        raise ArtworkSourceUnavailable("INVALID_PROVIDER_JSON_SHAPE")
    return value


def _identity(row: Mapping, expected_provider: str, system: str) -> str:
    if (row.get("provider"), row.get("system_code"), row.get("language")) != (
        expected_provider, system, "English"
    ):
        raise ArtworkPreviewError("Wrong source provider or language")
    provider_id = row.get("provider_id")
    if not isinstance(provider_id, str):
        raise ArtworkPreviewError("Missing source printing ID")
    key = codec.stable_key(expected_provider, system, "English", provider_id)
    if row.get("key") != key or not row.get("source_manifest_sha256"):
        raise ArtworkPreviewError("Source record not bound to published R2 manifest")
    return key


async def _ygo(client: httpx.AsyncClient, row: Mapping) -> dict:
    code = row.get("card_number")
    if not isinstance(code, str) or not YGO_CODE.fullmatch(code):
        return _decision(row, row["key"], "UNSUPPORTED_YGO_SET_CODE")
    info = await _json_get(
        client, "https://db.ygoprodeck.com/api/v7/cardsetsinfo.php?setcode="
                + quote(code, safe=""))
    if (info.get("set_code") != code or info.get("set_name") != row.get("set_name")
            or info.get("set_rarity") != row.get("rarity")
            or isinstance(info.get("id"), bool)
            or not re.fullmatch(r"[1-9][0-9]{0,11}", str(info.get("id")))):
        return _decision(row, row["key"], "YGO_SET_PRINTING_IDENTITY_MISMATCH")
    card = await _json_get(
        client, "https://db.ygoprodeck.com/api/v7/cardinfo.php?id="
                + str(info["id"]))
    cards = card.get("data")
    if not isinstance(cards, list) or len(cards) != 1 or cards[0].get("id") != info["id"]:
        return _decision(row, row["key"], "YGO_CARD_IDENTITY_MISMATCH")
    result = preview_yugioh({"data": cards}, [row])[0]
    return result


async def _lorcana(client: httpx.AsyncClient, row: Mapping) -> dict:
    set_code, number = row.get("set_id"), row.get("card_number")
    if (not isinstance(set_code, str) or not LORCAST_SET.fullmatch(set_code)
            or not isinstance(number, str) or not LORCAST_NUMBER.fullmatch(number)):
        return _decision(row, row["key"], "UNSUPPORTED_LORCANA_SET_NUMBER")
    card = await _json_get(
        client, "https://api.lorcast.com/v0/cards/"
                + quote(set_code, safe="") + "/" + quote(number, safe=""))
    source_set = card.get("set")
    if (not isinstance(source_set, Mapping)
            or source_set.get("code") != set_code
            or card.get("collector_number") != number
            or row.get("provider_id") != "lorcast:" + str(card.get("id"))):
        return _decision(row, row["key"], "LORCANA_EXACT_PRINTING_MISMATCH")
    pack = {"sets": [dict(source_set)],
            "cards_by_set": {source_set["id"]: [card]}}
    return preview_lorcana(pack, [row])[0]


async def _magic(client: httpx.AsyncClient, row: Mapping) -> dict:
    source = str(row.get("provider_id", ""))
    native = re.fullmatch(
        r"mtgjson:([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):"
        r"(nonfoil|foil|etched)", source)
    code, number = row.get("set_id"), row.get("card_number")
    if (not native or not isinstance(code, str) or not MTG_SET.fullmatch(code)
            or not isinstance(number, str) or not MTG_NUMBER.fullmatch(number)):
        return _decision(row, row["key"], "UNSUPPORTED_MTG_PRINTING")
    card = await _json_get(
        client, "https://api.scryfall.com/cards/" + quote(code.lower(), safe="")
                + "/" + quote(number, safe=""))
    finish = native.group(2)
    if (card.get("set") != code.lower()
            or card.get("collector_number") != number
            or card.get("name") != row.get("name")
            or card.get("lang") != "en"
            or card.get("rarity") != row.get("rarity")
            or finish not in (card.get("finishes") or [])
            or card.get("digital") is not False
            or "paper" not in (card.get("games") or [])):
        return _decision(row, row["key"], "MTG_SET_COLLECTOR_FINISH_MISMATCH")
    if "card_faces" in card or card.get("layout") in {
        "transform", "modal_dfc", "double_faced_token", "reversible_card",
    }:
        return _decision(row, row["key"], "MTG_MULTIFACE_FRONT_BACK_REVIEW_REQUIRED")
    scryfall = card.get("id")
    try:
        parsed = str(UUID(scryfall))
    except (ValueError, TypeError, AttributeError):
        return _decision(row, row["key"], "MTG_SCRYFALL_ID_INVALID")
    url = card.get("image_uris", {}).get("normal") if isinstance(
        card.get("image_uris"), Mapping) else None
    match = _SCRYFALL_FRONT.fullmatch(url) if isinstance(url, str) else None
    if not match or match.group(3) != parsed or (match.group(1), match.group(2)) != (
        parsed[0], parsed[1]
    ):
        return _decision(row, row["key"], "MTG_UNTRUSTED_IMAGE_URL")
    # Set + collector + finish is strong, but still not the original MTGJSON
    # source identifiers.scryfallId crosswalk. Keep the remaining gate explicit.
    return _decision(
        row, row["key"],
        "MTG_IMAGE_CANDIDATE_PENDING_SOURCE_UUID_CROSSWALK_AND_RIGHTS", url,
    )


def _expected_image(url: str, system: str) -> bool:
    if system == "YUGIOH":
        return _YGO_IMAGE.fullmatch(url) is not None
    if system == "DISNEY_LORCANA":
        return _LOR_IMAGE.fullmatch(url) is not None
    if system == "MAGIC_THE_GATHERING":
        return _SCRYFALL_FRONT.fullmatch(url) is not None
    return False


async def _verify_bytes(client: httpx.AsyncClient, decision: dict, *, stage_callback=None) -> dict:
    url = decision.get("candidate_image_url")
    if not url or not _expected_image(url, decision["system_code"]):
        return decision
    try:
        data = await _bounded_get(client, url, image=True)
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "AVIF"}:
                raise ArtworkSourceUnavailable("IMAGE_FORMAT_MISMATCH")
            w, h = image.size
            if min(w, h) < 200 or max(w, h) > 4096:
                raise ArtworkSourceUnavailable("IMAGE_DIMENSIONS_INVALID")
            image.verify()
        decision["image_byte_verified"] = True
        decision["image_sha256"] = hashlib.sha256(data).hexdigest()
        decision["image_size_bytes"] = len(data)
        decision["image_dimensions"] = {"width": w, "height": h}
        # Only a platform-admin staging call may supply this callback, which
        # writes to isolated PRIVATE-REVIEW, never public media or Shopify.
        if stage_callback is not None:
            content_type = "image/jpeg" if image.format == "JPEG" else "image/avif"
            try:
                receipt = await stage_callback(decision, data, content_type)
                if (receipt.get("state") != "PRIVATE_REVIEW_ONLY"
                        or receipt.get("verified") is not True
                        or receipt.get("sha256") != decision["image_sha256"]):
                    raise ValueError("Private R2 staging receipt mismatch")
                decision["review_storage"] = receipt
            except Exception:
                # Never expose storage credentials, provider responses or
                # raw exception text to the browser. The candidate can be
                # retried without an approval or destructive cleanup.
                decision["review_storage_error"] = "PRIVATE_R2_STAGE_UNAVAILABLE"
        # Byte validity never proves an exact printing, licence or storefront use.
    except (ArtworkSourceUnavailable, UnidentifiedImageError, OSError, ValueError) as exc:
        decision["image_validation_error"] = (
            str(exc) if isinstance(exc, ArtworkSourceUnavailable)
            else "IMAGE_DECODE_INVALID"
        )
    return decision


async def collect(
    system_code: str, references: list[dict],
    *,
    verify_bytes: bool = False,
    client: httpx.AsyncClient | None = None,
    stage_callback=None,
) -> dict:
    """Bounded sequential source reads, with per-record error receipts."""
    if stage_callback is not None and not verify_bytes:
        raise ArtworkPreviewError("Private R2 staging requires image byte verification")
    if system_code not in CONNECTIONS:
        raise ArtworkPreviewError("Unsupported artwork source")
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_ROWS:
        raise ArtworkPreviewError("Use 1–5 exact source references per request")
    provider, system = CONNECTIONS[system_code]
    keys = [_identity(row, provider, system) for row in references]
    if len(set(keys)) != len(keys):
        raise ArtworkPreviewError("Duplicate exact published reference")
    owned = client is None
    if owned:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(6.0, connect=2.0),
            follow_redirects=False,
            headers=HEADERS,
        )
    try:
        result = []
        for ix, row in enumerate(references):
            if ix:
                await asyncio.sleep(.13)  # Bound Lorcast/Scryfall/API rate.
            try:
                func = {"YUGIOH": _ygo, "DISNEY_LORCANA": _lorcana,
                        "MAGIC_THE_GATHERING": _magic}[system_code]
                decision = await func(client, row)
                if verify_bytes:
                    decision = await _verify_bytes(
                        client, decision, stage_callback=stage_callback)
            except ArtworkSourceUnavailable as exc:
                decision = _decision(row, row["key"], str(exc))
                if str(exc) == "PROVIDER_RATE_LIMITED":
                    result.append(decision)
                    result.extend(_decision(next_row, next_row["key"], "PROVIDER_RATE_LIMITED_SKIPPED")
                                  for next_row in references[ix + 1:])
                    break
            except (ArtworkPreviewError, KeyError, TypeError, ValueError):
                decision = _decision(row, row["key"], "SOURCE_IDENTITY_REVIEW_REQUIRED")
            result.append(decision)
    finally:
        if owned:
            await client.aclose()
    return {
        "system_code": system_code,
        "requested": len(references),
        "candidate_count": sum(bool(row.get("candidate_image_url")) for row in result),
        "byte_verified_count": sum(row["image_byte_verified"] for row in result),
        "records": result,
        "can_publish": False,
        "can_mirror": False,
        "storage_writes": sum(
            bool(row.get("review_storage"))
            and not row["review_storage"].get("unchanged", False)
            for row in result
        ),
        "review_staged_count": sum(bool(row.get("review_storage")) for row in result),
        "review_stage_failures": sum(bool(row.get("review_storage_error")) for row in result),
        "database_writes": 0,
    }
