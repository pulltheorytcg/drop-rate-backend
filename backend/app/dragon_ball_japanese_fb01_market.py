"""Batch 1: evidence-gated Non-English Fusion World FB01 market guide.

This narrow adapter is deliberately reference-only. Cardmarket's separate
Non-English region is not proof of a Japanese-only sale, Near Mint condition,
foil treatment or a graded price. It must never update a physical inventory
item or infer a slab multiplier.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .one_piece_market import SOURCE, normalized
from .reference_market import _minor

SYSTEM = "DRAGON_BALL_SUPER_FUSION_WORLD"
PROVIDER = "Bandai Official"
JP_SET = "584001"
EN_SET = "583001"
JP_TITLE = "ブースターパック 覚醒の鼓動[FB01]"
EN_TITLE = "BOOSTER PACK -AWAKENED PULSE- [FB01]"
PRINT_RE = re.compile(r"FB01-\d{3}\Z")
SINGLE_RE = re.compile(r"(.+) \((FB01-\d{3})\) \[Fusion World\]\Z")
EN_BOOSTER = "Awakened Pulse Booster [Fusion World]"
NON_EN_BOOSTER = EN_BOOSTER + " (Non-English)"
MATCH_BASIS = "OFFICIAL_JP_EN_FB01_BASE_ID_UNIQUE_CARDMARKET_NONENGLISH_EXPANSION"


def _official_base(ref: dict, language: str) -> bool:
    source_set = JP_SET if language == "Japanese" else EN_SET
    official_title = JP_TITLE if language == "Japanese" else EN_TITLE
    number = ref.get("card_number")
    return (
        ref.get("provider") == PROVIDER
        and ref.get("system_code") == SYSTEM
        and ref.get("language") == language
        and ref.get("set_id") == source_set
        and ref.get("set_name") == official_title
        and isinstance(number, str)
        and PRINT_RE.fullmatch(number) is not None
        and ref.get("provider_id") == source_set + ":" + number
        and isinstance(ref.get("name"), str) and bool(ref["name"].strip())
    )


def _distinct_region_expansion(packaging: dict, name: str) -> int | None:
    """A single identifiable marketplace expansion, not the first item."""
    ids = set()
    for pack in packaging.values():
        if (pack.get("idCategory") == 1050
                and pack.get("categoryName") == "Dragon Ball Super Boosters"
                and pack.get("name") == name
                and type(pack.get("idExpansion")) is int
                and pack["idExpansion"] > 0):
            ids.add(pack["idExpansion"])
    return next(iter(ids)) if len(ids) == 1 else None


def matched_japanese_fb01(references: list[dict], singles: dict, packaging: dict) -> dict:
    """Return only independently matched *base* Japanese printing IDs.

    Market pricing cannot choose among duplicated English/Japanese official
    identities or among multiple marketplace products, even if only one of
    those alternatives has a price guide.
    """
    non_english_expansion = _distinct_region_expansion(packaging, NON_EN_BOOSTER)
    english_expansion = _distinct_region_expansion(packaging, EN_BOOSTER)
    if (non_english_expansion is None or english_expansion is None
            or non_english_expansion == english_expansion):
        return {}

    en_by_number = defaultdict(list)
    jp_by_number = defaultdict(list)
    for ref in references:
        if _official_base(ref, "English"):
            en_by_number[ref["card_number"]].append(ref)
        if _official_base(ref, "Japanese"):
            jp_by_number[ref["card_number"]].append(ref)

    products = defaultdict(list)
    for product in singles.values():
        if (product.get("idCategory") != 1049
                or product.get("categoryName") != "Dragon Ball Super Singles"
                or product.get("idExpansion") != non_english_expansion
                or type(product.get("idProduct")) is not int
                or product["idProduct"] <= 0):
            continue
        exact = SINGLE_RE.fullmatch(str(product.get("name") or ""))
        if exact:
            products[(exact[2], normalized(exact[1]))].append(product)

    matched = {}
    used_products = set()
    for number, japanese in jp_by_number.items():
        english = en_by_number.get(number, [])
        if len(japanese) != 1 or len(english) != 1:
            continue
        jp, en = japanese[0], english[0]
        matches = products.get((number, normalized(en["name"])), [])
        if len(matches) != 1:
            continue
        product = matches[0]
        # The same Cardmarket product must not be assigned to two printings.
        if product["idProduct"] in used_products:
            continue
        used_products.add(product["idProduct"])
        matched[jp["provider_id"]] = {
            "product": product,
            "english_provider_id": en["provider_id"],
            "english_set_id": en["set_id"],
            "english_expansion_id": english_expansion,
            "region_expansion_id": non_english_expansion,
        }
    return matched


def japanese_fb01_quote(
    reference: dict, match: dict, price: dict | None, observed: datetime, conversion,
) -> dict | None:
    """Current GBP reference guide, not exact-language sold/graded evidence."""
    product = match["product"]
    if (not _official_base(reference, "Japanese")
            or not isinstance(price, dict)
            or price.get("idCategory") != 1049
            or str(price.get("idProduct")) != str(product.get("idProduct"))
            or product.get("idExpansion") != match.get("region_expansion_id")
            or match.get("english_expansion_id") == match.get("region_expansion_id")):
        return None
    try:
        original = _minor(price.get("trend"))
        gbp = int((Decimal(original) * conversion.rate).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        if original <= 0 or gbp <= 0:
            return None
    except (ValueError, TypeError, ArithmeticError):
        return None
    return {
        "source": SOURCE,
        "product_id": str(product["idProduct"]),
        "expansion_id": match["region_expansion_id"],
        "source_field": "trend",
        "finish": "Non-English regional printing guide",
        "original_currency": "EUR",
        "original_minor": original,
        "price_gbp_minor": gbp,
        "observed_at": observed.isoformat(),
        "valuation_role": "MIXED_NON_ENGLISH_REFERENCE",
        "reference_language": "Japanese",
        "marketplace_region_label": "Non-English",
        "physical_language_confirmed": False,
        "condition_specific": False,
        "physical_valuation_eligible": False,
        "match_basis": MATCH_BASIS,
        "reference_printing_id": reference["provider_id"],
        "reference_rarity": reference.get("rarity"),
        "reference_identity": {
            key: reference[key]
            for key in ("name", "set_id", "card_number", "set_name")
        },
        "english_checklist_provider_id": match["english_provider_id"],
        "english_checklist_set_id": match["english_set_id"],
        "english_marketplace_expansion_id": match["english_expansion_id"],
        "fx_rate_to_gbp": str(conversion.rate),
        "fx_source": conversion.source,
        "fx_effective_at": conversion.effective_at.isoformat(),
        "fx_retrieved_at": conversion.retrieved_at.isoformat(),
    }
