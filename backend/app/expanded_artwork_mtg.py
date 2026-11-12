"""MTGJSON ↔ Scryfall exact-print artwork leads (unapproved, offline-only).

MTGJSON does not distribute card artwork. It does expose the exact MTGJSON
printing UUID and an identifiers.scryfallId join in its original source data.
A credible Scryfall image still requires byte, printing/finish, and rights review
before Drop Rate may mirror or publish anything.

Inputs are a maximum 25 already-extracted *source* printing records, never
arbitrary URLs from a customer or a name-based match. No HTTP or R2 writes.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from uuid import UUID

from . import r2_first_mtgjson as mtg
from .expanded_artwork_pilot import (
    ArtworkPreviewError, _decision, _identity_matches, _references,
)
from .r2_first_sources import SourceError


_SCRYFALL_FRONT = re.compile(
    r"https://cards\.scryfall\.io/(?:normal|large)/front/"
    r"([0-9a-f])/([0-9a-f])/([0-9a-f]{8}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jpg(?:\?[0-9]{1,20})?\Z"
)
_ALLOWED_FINISHES = frozenset({"foil", "nonfoil", "etched"})


def _source_rows(bundle: Mapping) -> dict[str, tuple[dict, Mapping]]:
    printings = bundle.get("printings")
    if not isinstance(printings, list) or not 1 <= len(printings) <= 25:
        raise ArtworkPreviewError("MTG source pack must contain 1–25 printings")
    rows = {}
    for entry in printings:
        if not isinstance(entry, Mapping):
            raise ArtworkPreviewError("Invalid MTG source entry")
        raw_card, source_set, scryfall = (
            entry.get("card"), entry.get("set"), entry.get("scryfall"),
        )
        if not isinstance(raw_card, Mapping) or not isinstance(source_set, Mapping):
            raise ArtworkPreviewError("MTG printing identity requires card and set")
        try:
            code, name, date = (source_set["code"], source_set["name"],
                                source_set["releaseDate"])
            selected = mtg._selected_card(dict(raw_card), code)
            if selected is None or not isinstance(name, str) or not name.strip():
                raise ArtworkPreviewError("Only complete English paper printings qualify")
            release = selected["release_date"] or mtg._date(date, "set release")
        except (KeyError, SourceError, TypeError, ValueError) as exc:
            raise ArtworkPreviewError("Malformed MTGJSON print identity") from exc
        if not isinstance(scryfall, Mapping):
            scryfall = {}
        crosswalk = raw_card.get("identifiers")
        crosswalk_id = crosswalk.get("scryfallId") if isinstance(crosswalk, Mapping) else None
        for finish in selected["finishes"]:
            provider_id = f"mtgjson:{selected['uuid']}:{finish}"
            if provider_id in rows:
                raise ArtworkPreviewError("Duplicate MTG printing and finish")
            row = {
                "provider": "mtgjson", "system_code": "MAGIC_THE_GATHERING",
                "language": "English", "provider_id": provider_id,
                "product_type": "CARD", "name": selected["name"],
                "set_id": code, "set_name": name,
                "card_number": selected["number"], "rarity": selected["rarity"],
                "finish": finish, "release_date": release,
                "source_url": mtg.DOWNLOAD_URL,
            }
            rows[provider_id] = (row, {
                "source_uuid": selected["uuid"],
                "crosswalk_id": crosswalk_id,
                "scryfall": scryfall,
                "finish": finish,
            })
    return rows


def _image(info: Mapping) -> tuple[str, str | None]:
    """Return reason-coded candidate, never a publishable asset."""
    crosswalk_id = info.get("crosswalk_id")
    if not isinstance(crosswalk_id, str):
        return "MISSING_SCRYFALL_PRINTING_CROSSWALK", None
    try:
        crosswalk_id = str(UUID(crosswalk_id))
    except ValueError:
        return "INVALID_SCRYFALL_PRINTING_CROSSWALK", None
    scryfall = info["scryfall"]
    if (scryfall.get("id") != crosswalk_id
            or scryfall.get("lang") != "en"
            or scryfall.get("digital") is not False
            or "paper" not in (scryfall.get("games") or [])
            or info["finish"] not in (scryfall.get("finishes") or [])):
        return "SCRYFALL_PRINTING_IDENTITY_MISMATCH", None
    # Scryfall's set token and collector number must match the source
    # printing, not just its name or artwork name.
    # The caller performs the exact MTGJSON row-identity comparison first.
    if "card_faces" in scryfall or scryfall.get("layout") in {
        "transform", "modal_dfc", "double_faced_token", "reversible_card",
    }:
        return "MULTIFACE_PRINTING_REQUIRES_FRONT_BACK_REVIEW", None
    url = scryfall.get("image_uris", {}).get("normal") if isinstance(
        scryfall.get("image_uris"), Mapping) else None
    match = _SCRYFALL_FRONT.fullmatch(url) if isinstance(url, str) else None
    if (not match or match.group(3) != crosswalk_id
            or (match.group(1), match.group(2)) !=
               (crosswalk_id[0], crosswalk_id[1])):
        return "UNTRUSTED_MTG_IMAGE_LOCATOR", None
    return "MTG_PRINT_ART_PENDING_FINISH_AND_RIGHTS_REVIEW", url


def preview_mtgjson(bundle: Mapping, published_rows: list[dict]) -> list[dict]:
    """Compare exact MTGJSON record identities before considering art locators.

    Original source evidence must include the MTGJSON printing UUID and
    identifiers.scryfallId from the same card record, together with a matching
    Scryfall card response. No name-only joining, art substitution, or approval.
    """
    references = _references(
        published_rows, provider="mtgjson", system="MAGIC_THE_GATHERING",
    )
    if not isinstance(bundle, Mapping) or set(bundle) != {"printings"}:
        raise ArtworkPreviewError("Invalid MTG source review pack")
    mapped = _source_rows(bundle)
    decisions = []
    for provider_id, (reference, key) in references.items():
        pair = mapped.get(provider_id)
        if pair is None or not _identity_matches(reference, pair[0]):
            decisions.append(_decision(reference, key, "SOURCE_IDENTITY_MISMATCH"))
            continue
        actual, info = pair
        source_scryfall = info["scryfall"]
        if (source_scryfall.get("set", "").lower() != actual["set_id"].lower()
                or source_scryfall.get("collector_number") != actual["card_number"]
                or source_scryfall.get("name") != actual["name"]):
            decisions.append(_decision(reference, key, "SCRYFALL_PRINTING_IDENTITY_MISMATCH"))
            continue
        status, url = _image(info)
        decisions.append(_decision(reference, key, status, url))
    return decisions
