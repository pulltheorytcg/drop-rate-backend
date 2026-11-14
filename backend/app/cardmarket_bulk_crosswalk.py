"""Crosswalk Cardmarket's bulk Pokémon guide against existing, proven source IDs.

Inputs are trusted reference/source-link facts read from *existing* Drop Rate
caches, plus the two official Cardmarket public exports. Source-name matching
alone never creates a printing link. No external network, SQL, or price writes
occur in this pure module.

This is a source coverage and daily-guide candidate engine, not a new
Market Value algorithm and not permission to redistribute Cardmarket prices.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
import unicodedata

from .cardmarket_public_pilot import PilotError, _id, _rows

SOURCE_DIRECT = frozenset(("TCGDEX_CARDMARKET", "TCGDEX_CARDMARKET_VARIANT"))
SOURCE_NUMBER = "CARDMARKET_CATALOGUE"
DIRECT_FIELDS = {"trend": "avg7", "trend-holo": "avg7-holo"}
CATEGORIES = frozenset(("pokemon single", "pokémon single"))
SCHEMA = "drop-rate-cardmarket-pokemon-existing-crosswalk-v1"
MAX_LINKS = 120_000
MIN_ANCHOR_NAMES = 8


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _product_name_matches(link: Mapping[str, Any], product: Mapping[str, Any]) -> bool:
    """Cardmarket may append verified attack labels in brackets.

    Never match bare character names on their own. We require a trusted,
    direct TCGdex marketplace product ID and all other set/variant gates.
    Number-only reference guides do not receive this exception.
    """
    name = _text(product.get("name"))
    expected = _text(link.get("name"))
    if not name or not expected:
        return False
    if name == expected:
        return True
    return (
        link.get("source") in SOURCE_DIRECT
        and name.startswith(expected + " [")
        and name.endswith("]")
        and len(name) > len(expected) + 3
        and name.count(" [") == 1
    )


def _number(value: str) -> str:
    # Cardmarket's optional collector number is generally a set-local part.
    # Do not force formats or infer missing number data from product names.
    piece = value.strip().split("/")[0]
    return piece.lstrip("0") or "0" if piece.isascii() and piece.isdecimal() else piece.casefold()


def _valid_link(row: Mapping[str, Any]) -> bool:
    required = ("provider", "system_code", "language", "provider_id", "name",
                "set_name", "card_number", "cardmarket_id", "source",
                "finish", "source_field")
    if any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
        return False
    if (row["provider"] != "TCGdex" or row["system_code"] != "POKEMON_TCG"
            or row["language"] not in ("English", "Japanese")
            or row["source"] not in SOURCE_DIRECT | {SOURCE_NUMBER}):
        return False
    if _id(row["cardmarket_id"]) is None:
        return False
    if row["source"] in SOURCE_DIRECT:
        return (row.get("source_field") in DIRECT_FIELDS
                and row.get("finish") in ("Normal", "Holofoil", "Reverse Holofoil")
                and isinstance(row.get("variant_id"), str) and bool(row["variant_id"]))
    return (row.get("match_basis") ==
            "CARDTRADER_EXPLICIT_NUMBER_AND_SINGLETON_CARDMARKET_ID"
            and row["finish"] == "Printing guide"
            and row.get("source_field") in DIRECT_FIELDS)


def _valid_amount(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        price = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None
    if not price.is_finite() or price <= 0 or price > Decimal("1000000"):
        return None
    pennies = price * 100
    if pennies != pennies.quantize(Decimal("1")) or pennies < 1:
        return None
    return int(pennies)


def match_pokemon_bulk(*, links: list[dict], products_export: dict,
                       price_export: dict, now: datetime) -> dict[str, Any]:
    """Generate reviewed candidates from independently sourced exact IDs.

    Returns candidates with EU aggregate evidence for private review only.
    Does not assign UK, condition/grade-specific, or item-level SOLD values.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise PilotError("Audit clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if not isinstance(links, list) or len(links) > MAX_LINKS:
        raise PilotError("Mapping input is unbounded")
    for payload in (products_export, price_export):
        if not isinstance(payload, dict) or (
            "version" in payload and
            (type(payload["version"]) is not int or payload["version"] != 1)
        ):
            raise PilotError("Unsupported Cardmarket export version")
    products, product_time = _rows(products_export, "products", now=now)
    guides, guide_time = _rows(price_export, "priceGuides", now=now)
    if abs(product_time - guide_time) > timedelta(days=2):
        raise PilotError("Cardmarket catalogue and price files disagree on date")

    products_by_id: dict[int, Mapping[str, Any]] = {}
    for item in products:
        id_product = _id(item.get("idProduct"))
        if id_product is None or id_product in products_by_id:
            raise PilotError("Invalid or duplicate product ID")
        products_by_id[id_product] = item
    guides_by_id: dict[int, Mapping[str, Any]] = {}
    for item in guides:
        id_product = _id(item.get("idProduct"))
        if id_product is None or id_product in guides_by_id:
            raise PilotError("Invalid or duplicate guide ID")
        guides_by_id[id_product] = item

    rejected = Counter()
    normalized = {}
    for item in links:
        if not isinstance(item, Mapping) or not _valid_link(item):
            rejected["INVALID_TRUSTED_SOURCE_LINK"] += 1
            continue
        key = (item["language"], item["provider_id"], int(item["cardmarket_id"]),
               item["finish"], item.get("variant_id") or "", item["source"])
        existing = normalized.get(key)
        if existing and existing != item:
            rejected["DUPLICATE_SOURCE_LINK_CONFLICT"] += 1
            normalized.pop(key, None)
            continue
        normalized[key] = dict(item)

    # One Cardmarket idProduct MUST NOT map to two different canonical
    # printings or languages (even if their English translation is identical).
    ref_by_cardmarket: dict[int, set[tuple]] = defaultdict(set)
    slot_by_cardmarket: dict[tuple[int, str], set[tuple]] = defaultdict(set)
    for item in normalized.values():
        id_product = int(item["cardmarket_id"])
        identity = (item["language"], item["provider_id"])
        ref_by_cardmarket[id_product].add(identity)
        if item["source"] in SOURCE_DIRECT:
            price_field = DIRECT_FIELDS[item["source_field"]]
            slot_by_cardmarket[(id_product, price_field)].add(
                (identity, item["variant_id"], item["finish"])
            )
    collisions = {id_product for id_product, refs in ref_by_cardmarket.items()
                  if len(refs) > 1}
    slot_collisions = {id_product for (id_product, _), slots in slot_by_cardmarket.items()
                       if len(slots) > 1}

    # Corroborate expansion numbers by independent, exact product IDs and names.
    # A single name match is not enough to establish the underlying expansion.
    cohort_names: dict[tuple[int, str], set[str]] = defaultdict(set)
    cohort_sets: dict[int, set[str]] = defaultdict(set)
    for item in normalized.values():
        id_product = int(item["cardmarket_id"])
        if id_product in collisions | slot_collisions or item["source"] not in SOURCE_DIRECT:
            continue
        product = products_by_id.get(id_product)
        if (not product or _text(product.get("categoryName")) not in CATEGORIES
                or not _product_name_matches(item, product)):
            continue
        expansion = _id(product.get("idExpansion"))
        if expansion is None:
            continue
        set_name = _text(item["set_name"])
        if product.get("expansionName") is not None and (
                _text(product["expansionName"]) != set_name):
            continue
        cohort_names[(expansion, set_name)].add(_text(item["name"]))
        cohort_sets[expansion].add(set_name)
    ambiguous_expansions = {id_exp for id_exp, names in cohort_sets.items()
                            if len(names) != 1}

    candidates = []
    seen_candidate = set()
    for item in normalized.values():
        id_product = int(item["cardmarket_id"])
        if id_product in collisions:
            rejected["AMBIGUOUS_PRODUCT_TO_PRINTING"] += 1
            continue
        if id_product in slot_collisions:
            rejected["AMBIGUOUS_VARIANT_PRICE_SLOT"] += 1
            continue
        product = products_by_id.get(id_product)
        if not product:
            rejected["PRODUCT_NOT_FOUND"] += 1
            continue
        if _text(product.get("categoryName")) not in CATEGORIES:
            rejected["WRONG_CATEGORY"] += 1
            continue
        if not _product_name_matches(item, product):
            rejected["NAME_MISMATCH"] += 1
            continue
        number = product.get("number")
        if number is not None and (not isinstance(number, str) or
                                   _number(number) != _number(item["card_number"])):
            rejected["NUMBER_MISMATCH"] += 1
            continue
        expansion = _id(product.get("idExpansion"))
        if expansion is None:
            rejected["MISSING_EXPANSION"] += 1
            continue
        if expansion in ambiguous_expansions:
            rejected["AMBIGUOUS_EXPANSION"] += 1
            continue
        expected = _text(item["set_name"])
        explicit = product.get("expansionName")
        if explicit is not None:
            if _text(explicit) != expected:
                rejected["SET_NAME_MISMATCH"] += 1
                continue
            match_basis = "EXPLICIT_SET_AND_TRUSTED_SOURCE_ID"
        elif len(cohort_names.get((expansion, expected), set())) >= MIN_ANCHOR_NAMES:
            match_basis = "EIGHT_NAME_COHORT_AND_TRUSTED_SOURCE_ID"
        else:
            rejected["UNVERIFIED_EXPANSION"] += 1
            continue
        # A number-only CardTrader guide has no independently verified finish
        # treatment. Preserve mapping provenance but do not emit a price.
        exact_variant = item["source"] in SOURCE_DIRECT
        selected = DIRECT_FIELDS[item["source_field"]]
        guide = guides_by_id.get(id_product)
        value = _valid_amount(guide.get(selected)) if guide else None
        if value is None:
            rejected["MISSING_EXACT_7D_AGGREGATE"] += 1
            continue
        if guide.get("idCategory") is not None and product.get("idCategory") is not None:
            if _id(guide["idCategory"]) != _id(product["idCategory"]):
                rejected["PRICE_CATEGORY_MISMATCH"] += 1
                continue
        slot = (item["language"], item["provider_id"], id_product,
                item["finish"], selected)
        if slot in seen_candidate:
            rejected["DUPLICATE_MAPPING"] += 1
            continue
        seen_candidate.add(slot)
        candidates.append({
            "provider": item["provider"], "system_code": item["system_code"],
            "provider_id": item["provider_id"], "language": item["language"],
            "cardmarket_id": id_product, "finish": item["finish"],
            "variant_id": item.get("variant_id") if exact_variant else None,
            "source_field": selected, "source_link": item["source"],
            "set_name": item["set_name"], "card_number": item["card_number"],
            "expansion_id": expansion, "match_basis": match_basis,
            "daily_guide_eur_minor": value,
            "guide_observed_at": guide_time.isoformat(),
            "is_exact_variant": exact_variant,
            "condition_specific": False, "grade_specific": False,
            "language_specific_guide": False,
            "verified_item_level_sales": 0, "physical_valuation_eligible": False,
            "publishable": False,
        })
    return {
        "schema": SCHEMA, "status": "VERIFIED_SOURCE_ID_CANDIDATES_REVIEW_ONLY",
        "trusted_source_links_examined": len(links),
        "unique_source_links": len(normalized),
        "provider_ids_conflicting": len(collisions),
        "variant_price_slots_conflicting": len(slot_collisions),
        "ambiguous_expansion_ids": len(ambiguous_expansions),
        "candidate_count": len(candidates),
        "exact_variant_candidate_count": sum(c["is_exact_variant"] for c in candidates),
        "canonical_references_covered": len({(c["language"], c["provider_id"])
                                             for c in candidates}),
        "rejections": dict(sorted(rejected.items())),
        "guide_observed_at": guide_time.isoformat(),
        "price_source": "CARDMARKET_PUBLIC_DAILY_GUIDE",
        "physical_market_value_eligible": 0,
        "publishable": False,
        "writes": {"supabase": 0, "shopify": 0, "retail": 0},
        "candidates": candidates,
    }
