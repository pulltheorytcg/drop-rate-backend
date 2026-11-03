"""Exact-reference normalizers for future provider-approved catalogue imports.

These functions never fetch providers, ingest prices, approve artwork, create
physical inventory or write Shopify. Caller must retain original source proofs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
import re
from urllib.parse import urlsplit
from uuid import UUID

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
    host = urlsplit(source_url).hostname
    expected_manufacturer = "Topps" if host in {"uk.topps.com", "www.topps.com", "topps.com"} else "Panini"
    if manufacturer != expected_manufacturer:
        raise ReferenceSourceError("Checklist host does not match declared manufacturer")
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


MTG_SOURCE_ROOT = "https://mtgjson.com/api/v5"


def magic_printings(set_data: dict, card: dict) -> list[tuple[dict, dict]]:
    """Physical MTGJSON printing UUID + exact finish, never a price/image claim.

    MTGJSON UUID identifies a printing; one printing can have several physical
    finishes, which must not be collapsed to one product reference.
    """
    if not isinstance(set_data, dict) or not isinstance(card, dict):
        raise ReferenceSourceError("Invalid MTGJSON set/card")
    code = _text(set_data.get("code"), field="Magic set code", max_length=10)
    if not re.fullmatch(r"[A-Z0-9]{2,10}", code):
        raise ReferenceSourceError("Invalid Magic set code")
    if card.get("setCode") is not None and card["setCode"] != code:
        raise ReferenceSourceError("Magic printing belongs to a different set")
    if set_data.get("isOnlineOnly") is True:
        return []
    availability = card.get("availability")
    if availability is not None:
        if not isinstance(availability, list):
            raise ReferenceSourceError("Invalid Magic availability")
        if "paper" not in availability:
            return []
    card_uuid = _text(card.get("uuid"), field="Magic printing UUID", max_length=36)
    try:
        if str(UUID(card_uuid)) != card_uuid:
            raise ValueError("Noncanonical UUID")
    except ValueError as exc:
        raise ReferenceSourceError("Invalid Magic printing UUID") from exc
    name = _text(card.get("name"), field="Magic card name")
    number = _text(card.get("number"), field="Magic collector number", max_length=80)
    rarity = _text(card.get("rarity"), field="Magic rarity", max_length=100)
    finishes = card.get("finishes")
    if not isinstance(finishes, list) or not 1 <= len(finishes) <= 8:
        raise ReferenceSourceError("Magic printing lacks bounded finish evidence")
    if len(set(finishes)) != len(finishes) or any(
            not isinstance(finish, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,35}", finish)
            for finish in finishes):
        raise ReferenceSourceError("Invalid or duplicate Magic finish")
    language = card.get("language", "English")
    if language != "English":
        raise ReferenceSourceError("Non-English Magic language needs a separate verified source")
    released = set_data.get("releaseDate")
    if released is not None:
        try:
            released = date.fromisoformat(released).isoformat()
        except (TypeError, ValueError) as exc:
            raise ReferenceSourceError("Invalid Magic release date") from exc
    count = set_data.get("totalSetSize")
    if count is not None and (type(count) is not int or count < 0):
        raise ReferenceSourceError("Invalid Magic declared set size")
    source_url = f"{MTG_SOURCE_ROOT}/{code}.json"
    set_record = {"provider": "MTGJSON", "system_code": "MAGIC_THE_GATHERING",
                  "language": language, "set_id": code,
                  "name": _text(set_data.get("name"), field="Magic set name"),
                  "release_date": released, "declared_card_count": count,
                  "source_url": source_url}
    identifiers = card.get("identifiers") or {}
    if not isinstance(identifiers, dict):
        raise ReferenceSourceError("Invalid Magic identifiers")
    scryfall_id = identifiers.get("scryfallId")
    if scryfall_id is not None:
        try:
            scryfall_id = str(UUID(scryfall_id))
        except (TypeError, ValueError) as exc:
            raise ReferenceSourceError("Invalid Magic Scryfall identity") from exc
    return [(set_record, {
        "provider_id": f"{card_uuid}:{finish}", "name": name,
        "card_number": number, "number_key": collector_key(number),
        "finish": finish, "rarity": rarity, "image_url": None,
        "source_url": source_url,
        "evidence": {"provider_local_id": card_uuid, "set_code": code,
                     "finish": finish, "scryfall_id": scryfall_id,
                     "artwork_status": "UNVERIFIED_EXACT_PRINTING",
                     "market_value_status": "NO_VERIFIED_SOLD_EVIDENCE"}
    }) for finish in finishes]


def lego_set_product(row: dict, *, themes: dict[str, str]) -> tuple[dict, dict]:
    """One Rebrickable source set, no photography, inventory or price rights.

    Output goes into the existing sealed-reference model only *after* a
    separate commercial-data-use review. Dry-run may validate the public CSV.
    """
    if not isinstance(row, dict) or not isinstance(themes, dict):
        raise ReferenceSourceError("Invalid LEGO source row/theme table")
    set_number = _text(row.get("set_num"), field="LEGO set number", max_length=56)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,48}-[1-9][0-9]{0,2}", set_number):
        raise ReferenceSourceError("Invalid exact LEGO set number/edition")
    theme_id = _text(row.get("theme_id"), field="LEGO theme ID", max_length=8)
    if not theme_id.isdecimal() or theme_id not in themes:
        raise ReferenceSourceError("Unverified LEGO theme identity")
    theme = _text(themes[theme_id], field="LEGO theme name")
    name = _text(row.get("name"), field="LEGO set name")
    year = row.get("year")
    piece_count = row.get("num_parts")
    if not isinstance(year, str) or not year.isdecimal() or not 1940 <= int(year) <= 2100:
        raise ReferenceSourceError("Invalid LEGO release year")
    if not isinstance(piece_count, str) or not piece_count.isdecimal() or int(piece_count) > 100000:
        raise ReferenceSourceError("Invalid LEGO piece count")
    if int(piece_count) < 2 or theme.casefold() in {"gear", "books", "non-lego"}:
        raise ReferenceSourceError("LEGO source record is not a confirmed construction set")
    source_url = f"https://rebrickable.com/sets/{set_number}/"
    set_record = {"provider": "Rebrickable", "system_code": "LEGO_SETS",
                  "language": "English", "set_id": f"theme:{theme_id}", "name": theme,
                  "release_date": None, "declared_card_count": None,
                  "source_url": "https://rebrickable.com/downloads/"}
    product = {"provider": "Rebrickable", "system_code": "LEGO_SETS",
               "language": "English", "provider_id": set_number,
               "set_id": set_record["set_id"], "name": name,
               "product_type": "LEGO_SET", "image_url": None,
               "source_url": source_url,
               "evidence": {"manufacturer": "LEGO", "set_number": set_number,
                            "theme_id": theme_id, "theme": theme,
                            "release_year": int(year), "piece_count": int(piece_count) or None,
                            "photo_rights": "UNVERIFIED",
                            "source_data_rights": "COMMERCIAL_REUSE_PENDING_REVIEW",
                            "market_value_status": "NO_VERIFIED_SOLD_EVIDENCE"}}
    return set_record, product
