"""Read-only, rights-unapproved artwork candidate review for R2-first card references.

This module intentionally performs NO networking, R2 writes, public image delivery,
media approval, Shopify publication or price changes. It only reports exact-ID
candidates supplied by existing, separately authorised source reads.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from . import r2_first_catalogue as catalogue
from .r2_first_sources import normalize_ygoprodeck
from .r2_first_lorcast import normalize_lorcast

MAX_PILOT_REFERENCES = 25
_YGO_IMAGE = re.compile(r"https://images\.ygoprodeck\.com/images/cards/([1-9][0-9]{0,11})\.jpg\Z")
_LORCAST_IMAGE = re.compile(
    r"https://cards\.lorcast\.io/card/digital/normal/(crd_[0-9a-f]{32})\.avif\?[0-9]{1,20}\Z"
)


class ArtworkPreviewError(ValueError):
    """Refuse missing, oversized or malformed preview input before publishing anything."""


def _references(rows, *, provider: str, system: str):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_PILOT_REFERENCES:
        raise ArtworkPreviewError("Pilot requires 1–25 published reference rows")
    result = {}
    for row in rows:
        if not isinstance(row, Mapping) or (row.get("provider"), row.get("system_code"), row.get("language")) != (provider, system, "English"):
            raise ArtworkPreviewError("Incorrect provider/system/language scope")
        provider_id = row.get("provider_id")
        if not isinstance(provider_id, str) or not provider_id:
            raise ArtworkPreviewError("Missing exact provider ID")
        key = catalogue.stable_key(provider, system, "English", provider_id)
        if row.get("key", key) != key or provider_id in result:
            raise ArtworkPreviewError("Duplicate or inconsistent source reference key")
        result[provider_id] = (row, key)
    return result


def _identity_matches(expected: Mapping, actual: Mapping) -> bool:
    """Never match by name alone; set, code, rarity, finish and language matter."""
    return all(expected.get(field) == actual.get(field) for field in (
        "provider", "system_code", "language", "provider_id", "product_type",
        "name", "set_id", "set_name", "card_number", "rarity", "finish",
        "release_date", "source_url",
    ))


def _decision(row: Mapping, key: str, status: str, url: str | None = None) -> dict:
    # A preview is not permission, a validated image, or a physical-copy photo.
    return {
        "reference_key": key,
        "provider_id": row["provider_id"],
        "system_code": row["system_code"],
        "language": row["language"],
        "set_id": row["set_id"],
        "card_number": row["card_number"],
        "status": status,
        "candidate_image_url": url,
        "rights_status": "PENDING_PUBLISHER_PERMISSION",
        "image_byte_verified": False,
        "printing_image_verified": False,
        "can_mirror": False,
        "can_publish": False,
    }


def preview_yugioh(payload: Mapping, published_rows: list[dict]) -> list[dict]:
    """Check one artwork ID per logical card; never infer an alternate-art/set map."""
    references = _references(published_rows, provider="ygoprodeck", system="YUGIOH")
    cards = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(cards, list) or not 1 <= len(cards) <= MAX_PILOT_REFERENCES:
        raise ArtworkPreviewError("Yu-Gi-Oh! preview source must contain 1–25 cards")
    # Reuse the production's exact hashed passcode+set+rarity identity algorithm.
    # Its normalizer deliberately omits artwork and prices.
    normalized = normalize_ygoprodeck(payload)
    matching = {row["provider_id"]: row for row in normalized}
    images = {}
    for card in cards:
        one = normalize_ygoprodeck({"data": [card]})
        for row in one:
            if row["provider_id"] in images:
                raise ArtworkPreviewError("Duplicate source card/printing evidence")
            images[row["provider_id"]] = card

    decisions = []
    for provider_id, (reference, key) in references.items():
        actual = matching.get(provider_id)
        if actual is None or not _identity_matches(reference, actual):
            decisions.append(_decision(reference, key, "SOURCE_IDENTITY_MISMATCH"))
            continue
        if not reference["card_number"] or not reference["set_id"]:
            decisions.append(_decision(reference, key, "INCOMPLETE_PRINTING_IDENTITY"))
            continue
        card = images[provider_id]
        card_images = card.get("card_images")
        if not isinstance(card_images, list) or not card_images:
            status, url = "NO_SOURCE_ARTWORK", None
        elif len(card_images) != 1:
            status, url = "ALTERNATE_ART_SET_MAPPING_UNKNOWN", None
        else:
            image = card_images[0]
            raw = image.get("image_url") if isinstance(image, Mapping) else None
            match = _YGO_IMAGE.fullmatch(raw) if isinstance(raw, str) else None
            if not match or str(image.get("id")) != match.group(1) or str(card.get("id")) != match.group(1):
                status, url = "UNTRUSTED_IMAGE_LOCATOR", None
            else:
                # Even one card-level image is not evidence for every reprint.
                status, url = "CARD_LEVEL_ART_PENDING_PRINT_AND_RIGHTS_REVIEW", raw
        decisions.append(_decision(reference, key, status, url))
    return decisions


def preview_lorcana(bundle: Mapping, published_rows: list[dict]) -> list[dict]:
    """Check Lorcast exact printing IDs; digital imagery still requires rights review."""
    references = _references(published_rows, provider="lorcast", system="DISNEY_LORCANA")
    if not isinstance(bundle, Mapping):
        raise ArtworkPreviewError("Invalid Lorcast source bundle")
    # Exact Lorcast set/card association and English language validation reuse
    # the same production normalizer as the existing R2 catalogue publication.
    normalized = normalize_lorcast(bundle)
    actual = {row["provider_id"]: row for row in normalized}
    raw_cards = {}
    by_set = bundle.get("cards_by_set")
    if not isinstance(by_set, Mapping):
        raise ArtworkPreviewError("Missing Lorcast source set registry")
    for card_rows in by_set.values():
        if not isinstance(card_rows, list):
            raise ArtworkPreviewError("Invalid Lorcast source card list")
        for card in card_rows:
            if isinstance(card, Mapping) and isinstance(card.get("id"), str):
                provider_id = "lorcast:" + card["id"]
                if provider_id in raw_cards:
                    raise ArtworkPreviewError("Duplicate Lorcast printing ID")
                raw_cards[provider_id] = card
    decisions = []
    for provider_id, (reference, key) in references.items():
        if provider_id not in actual or not _identity_matches(reference, actual[provider_id]):
            decisions.append(_decision(reference, key, "SOURCE_IDENTITY_MISMATCH"))
            continue
        image_uris = raw_cards[provider_id].get("image_uris")
        digital = image_uris.get("digital") if isinstance(image_uris, Mapping) else None
        url = digital.get("normal") if isinstance(digital, Mapping) else None
        match = _LORCAST_IMAGE.fullmatch(url) if isinstance(url, str) else None
        if match and provider_id == "lorcast:" + match.group(1):
            decisions.append(_decision(reference, key, "DIGITAL_ART_PENDING_RIGHTS_AND_PRINT_REVIEW", url))
        else:
            decisions.append(_decision(reference, key, "NO_VERIFIED_PRINTING_IMAGE_LOCATOR"))
    return decisions
