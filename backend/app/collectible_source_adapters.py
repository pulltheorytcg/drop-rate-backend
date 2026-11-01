"""Exact-reference normalizers for future provider-approved catalogue imports.

These functions never fetch providers, ingest prices, approve artwork, create
physical inventory or write Shopify. Caller must retain original source proofs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
from urllib.parse import urlsplit

from .recognition_games import collector_key


class ReferenceSourceError(ValueError):
    """Missing or contradictory provider identity; send for human review."""


def _text(value, *, field: str, max_length: int = 240) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise ReferenceSourceError(f"Invalid {field}")
    return value.strip()


def _https(value: str, *, hosts: frozenset[str]) -> str:
    url = urlsplit(_text(value, field="source_url", max_length=2048))
    if (url.scheme != "https" or url.hostname not in hosts or url.port not in (None, 443)
            or url.username or url.password or url.fragment):
        raise ReferenceSourceError("Source URL is not an approved provider host")
    return value


def _set_id(value: str) -> str:
    return "src-" + hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:20]


def yugioh_printings(cardinfo: dict, *, official_tcg_sets: dict[str, dict]) -> list[tuple[dict, dict]]:
    """Provider-set identity, not a name/passcode-only merge.

    YGOPRODeck's free v7 endpoint also includes prices and card_images. Neither
    is a verified sold transaction or proven printing-specific retail photo.
    """
    if not isinstance(cardinfo, dict) or not isinstance(official_tcg_sets, dict):
        raise ReferenceSourceError("Invalid YGOPRODeck source response")
    card_id = cardinfo.get("id")
    if type(card_id) is not int or card_id <= 0:
        raise ReferenceSourceError("Missing Yu-Gi-Oh! passcode")
    name = _text(cardinfo.get("name"), field="card name")
    source_url = f"https://db.ygoprodeck.com/api/v7/cardinfo.php?id={card_id}"
    offerings = cardinfo.get("card_sets") or []
    if not isinstance(offerings, list) or len(offerings) > 2000:
        raise ReferenceSourceError("Unbounded Yu-Gi-Oh! printing list")
    output = []
    seen: dict[str, tuple[str, str, str]] = {}
    for offering in offerings:
        if not isinstance(offering, dict):
            raise ReferenceSourceError("Invalid Yu-Gi-Oh! printing")
        set_name = _text(offering.get("set_name"), field="set name")
        info = official_tcg_sets.get(set_name)
        if info is None:
            continue  # Do not guess OCG/TGC language from a global product feed.
        official_code = _text(info.get("set_code"), field="official set code", max_length=80)
        set_code = _text(offering.get("set_code"), field="set code", max_length=80)
        if set_code.split("-", 1)[0] != official_code:
            # Real provider data has 25TH-EN001 incorrectly assigned to Battle
            # of Chaos (BACH). It must be reviewed, not treated as BACH.
            raise ReferenceSourceError("Set-printing code conflicts with official TCG checklist")
        rarity = _text(offering.get("set_rarity"), field="rarity", max_length=100)
        rarity_code = offering.get("set_rarity_code") or rarity
        rarity_code = _text(rarity_code, field="rarity code", max_length=100)
        provider_id = f"{card_id}:{set_code}:{rarity_code}"
        identity = (set_name, set_code, rarity)
        if provider_id in seen:
            if seen[provider_id] != identity:
                raise ReferenceSourceError("Conflicting Yu-Gi-Oh! printing evidence")
            continue
        seen[provider_id] = identity
        release_date = info.get("tcg_date")
        if release_date is not None:
            try:
                release_date = date.fromisoformat(release_date).isoformat()
            except (TypeError, ValueError) as exc:
                raise ReferenceSourceError("Invalid official TCG release date") from exc
        declared_count = info.get("num_of_cards")
        if declared_count is not None and (type(declared_count) is not int or declared_count < 0):
            raise ReferenceSourceError("Invalid official TCG set count")
        set_record = {"provider": "YGOPRODeck", "system_code": "YUGIOH",
                      "language": "English", "set_id": _set_id(set_name),
                      "name": set_name, "release_date": release_date,
                      "declared_card_count": declared_count, "source_url": source_url}
        card_record = {"provider_id": provider_id, "name": name,
                       "card_number": set_code, "number_key": collector_key(set_code),
                       "finish": None, "rarity": rarity, "image_url": None,
                       "source_url": source_url,
                       "evidence": {"provider_local_id": str(card_id),
                                    "set_code": set_code, "rarity_code": rarity_code,
                                    "artwork_status": "UNVERIFIED_EXACT_PRINTING",
                                    "market_value_status": "NO_VERIFIED_SOLD_EVIDENCE"}}
        output.append((set_record, card_record))
    return output


def group_yugioh_printings(cards: list[dict], *, official_tcg_sets: dict[str, dict]) -> dict[str, tuple[dict, list[dict]]]:
    """Ready for existing reference_library.save_reference_set, no R2 fork."""
    if not isinstance(cards, list) or len(cards) > 1000:
        raise ReferenceSourceError("YGO import batches must contain at most 1000 cards")
    grouped = defaultdict(lambda: [None, []])
    identities = set()
    for card in cards:
        for set_record, printing in yugioh_printings(card, official_tcg_sets=official_tcg_sets):
            key = (set_record["set_id"], printing["provider_id"])
            if key in identities:
                continue
            identities.add(key)
            group = grouped[set_record["set_id"]]
            group[0] = set_record
            group[1].append(printing)
    return {key: (value[0], value[1]) for key, value in grouped.items()}


LORCANA_LANGUAGES = {"en": "English", "fr": "French", "de": "German",
                     "it": "Italian", "es": "Spanish"}


def lorcana_printing(card: dict) -> tuple[dict, dict]:
    """Exact Lorcast print ID only; cannot infer a foil from a digital image.

    Deliberately no network fetch/import until commercial and artwork usage is
    reviewed. Lorcast's USD prices are not a UK sold-price observation.
    """
    if not isinstance(card, dict) or not isinstance(card.get("set"), dict):
        raise ReferenceSourceError("Invalid Lorcana card/set response")
    provider_id = _text(card.get("id"), field="Lorcana printing ID", max_length=100)
    if not provider_id.startswith("crd_"):
        raise ReferenceSourceError("Unrecognised Lorcana printing ID")
    set_data = card["set"]
    set_id = _text(set_data.get("id"), field="Lorcana set ID", max_length=100)
    if not set_id.startswith("set_"):
        raise ReferenceSourceError("Unrecognised Lorcana set identity")
    set_name = _text(set_data.get("name"), field="Lorcana set name")
    card_number = _text(card.get("collector_number"), field="Lorcana collector number", max_length=80)
    name = _text(card.get("name"), field="Lorcana name")
    rarity = _text(card.get("rarity"), field="Lorcana rarity", max_length=100)
    code = card.get("lang")
    if code not in LORCANA_LANGUAGES:
        raise ReferenceSourceError("Unsupported Lorcana language")
    release_date = card.get("released_at")
    if release_date is not None:
        try:
            release_date = date.fromisoformat(release_date).isoformat()
        except (TypeError, ValueError) as exc:
            raise ReferenceSourceError("Invalid Lorcana release date") from exc
    source = "https://www.lorcast.com/docs/api/cards"
    set_record = {"provider": "Lorcast", "system_code": "DISNEY_LORCANA",
                  "language": LORCANA_LANGUAGES[code], "set_id": set_id,
                  "name": set_name, "release_date": release_date,
                  "declared_card_count": None, "source_url": source}
    card_record = {"provider_id": provider_id, "name": name,
                   "card_number": card_number, "number_key": collector_key(card_number),
                   "finish": None, "rarity": rarity, "image_url": None,
                   "source_url": source,
                   "evidence": {"provider_local_id": provider_id,
                                "set_code": set_data.get("code"),
                                "version": card.get("version"),
                                "artwork_status": "UNVERIFIED_REHOST_RIGHTS",
                                "finish_status": "UNKNOWN_NO_FOIL_ASSUMPTION",
                                "market_value_status": "NO_VERIFIED_SOLD_EVIDENCE"}}
    return set_record, card_record


SPORT_CODES = frozenset({"SPORT_SOCCER", "SPORT_AMERICAN_FOOTBALL",
                         "SPORT_BASKETBALL", "SPORT_BASEBALL", "SPORT_HOCKEY",
                         "SPORT_MOTORSPORT"})
SPORT_SOURCE_HOSTS = frozenset({"uk.topps.com", "www.topps.com", "topps.com",
                                "www.paniniamerica.net", "paniniamerica.net"})


def sports_checklist_printing(row: dict) -> tuple[dict, dict, dict]:
    """Only an explicit official checklist row; parallel/athlete stay distinct."""
    if not isinstance(row, dict) or row.get("system_code") not in SPORT_CODES:
        raise ReferenceSourceError("Unsupported sport")
    source_url = _https(row.get("source_url"), hosts=SPORT_SOURCE_HOSTS)
    manufacturer = _text(row.get("manufacturer"), field="manufacturer", max_length=160)
    series = _text(row.get("series"), field="series")
    year = row.get("year")
    if type(year) is not int or not 1900 <= year <= 2100:
        raise ReferenceSourceError("Invalid release year")
    card_number = _text(row.get("card_number"), field="card number", max_length=80)
    athlete = _text(row.get("athlete"), field="athlete")
    parallel = _text(row.get("parallel"), field="parallel", max_length=100)
    team = row.get("team")
    if team is not None:
        team = _text(team, field="team")
    print_run = row.get("print_run")
    if print_run is not None and (type(print_run) is not int or print_run <= 0):
        raise ReferenceSourceError("Invalid print run")
    set_title = f"{year} {manufacturer} {series}"
    provider = f"{manufacturer} Official Checklist"
    set_record = {"provider": provider, "system_code": row["system_code"],
                  "language": "English", "set_id": _set_id(set_title), "name": set_title,
                  "release_date": None, "declared_card_count": None, "source_url": source_url}
    identity = "|".join((row["system_code"], set_title, card_number, athlete, parallel))
    provider_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    card_record = {"provider_id": provider_id, "name": athlete,
                   "card_number": card_number, "number_key": collector_key(card_number),
                   "finish": parallel, "rarity": None, "image_url": None,
                   "source_url": source_url,
                   "evidence": {"checklist_identity": identity,
                                "photo_status": "NO_PRINTING_VERIFIED_IMAGE",
                                "market_value_status": "NO_VERIFIED_SOLD_EVIDENCE"}}
    details = {"provider": provider, "system_code": row["system_code"],
               "language": "English", "provider_id": provider_id,
               "manufacturer": manufacturer, "product_line": series,
               "sport": row["system_code"], "league": row.get("league"),
               "team": team, "athlete": athlete, "parallel": parallel,
               "print_run": print_run, "is_autograph": row.get("is_autograph") is True,
               "is_memorabilia": row.get("is_memorabilia") is True,
               "manufacturer_sku": row.get("manufacturer_sku"),
               "source_url": source_url, "attributes": {"checklist_year": year}}
    return set_record, card_record, details


def figure_product(row: dict) -> dict:
    """Normalize authorised metadata; all art initially unverified and unmirrored."""
    if not isinstance(row, dict) or row.get("system_code") not in {"FUNKO_POP", "COLLECTIBLE_FIGURES"}:
        raise ReferenceSourceError("Unsupported figure catalogue")
    manufacturer = _text(row.get("manufacturer"), field="manufacturer", max_length=160)
    if row["system_code"] == "FUNKO_POP" and manufacturer.casefold() != "funko":
        raise ReferenceSourceError("Funko system must have Funko as manufacturer")
    source_url = _https(row.get("source_url"), hosts=frozenset({"funko.com", "www.funko.com"})
                        if row["system_code"] == "FUNKO_POP" else frozenset({"funko.com", "www.funko.com", "www.bandai.com", "bandai.com"}))
    provider_id = _text(row.get("provider_id"), field="provider ID", max_length=160)
    name = _text(row.get("name"), field="product name")
    barcode = row.get("barcode_gtin")
    if barcode is not None and (not isinstance(barcode, str) or
                                not barcode.isdecimal() or not 8 <= len(barcode) <= 14):
        raise ReferenceSourceError("Invalid GTIN")
    return {"provider": manufacturer + " Official", "system_code": row["system_code"],
            "language": _text(row.get("language", "English"), field="language", max_length=48),
            "provider_id": provider_id, "name": name, "manufacturer": manufacturer,
            "franchise": row.get("franchise"), "series_name": row.get("series_name"),
            "figure_number": row.get("figure_number"),
            "manufacturer_sku": row.get("manufacturer_sku"), "barcode_gtin": barcode,
            "edition": row.get("edition"), "variant": row.get("variant") or "",
            "exclusive_to": row.get("exclusive_to"), "release_date": row.get("release_date"),
            "source_url": source_url, "reference_image_url": row.get("reference_image_url"),
            "image_rights_status": "UNVERIFIED", "image_rights_evidence_url": None,
            "image_r2_key": None, "image_sha256": None, "attributes": {}}
