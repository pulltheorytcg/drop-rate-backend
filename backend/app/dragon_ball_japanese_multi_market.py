"""High-throughput, evidence-gated FB02–FB11 Fusion World regional guide import.

Process ten official Japanese releases together using one existing Cardmarket
public download, not one PR or refresh per set. A Non-English/Asia-region quote
is *not* proof of Japanese-language sales or a physical-copy valuation.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .one_piece_market import SOURCE, normalized
from .reference_market import _minor

PROVIDER = "Bandai Official"
SYSTEM = "DRAGON_BALL_SUPER_FUSION_WORLD"
MATCH_BASIS = "OFFICIAL_JP_EN_FB02_FB11_BASE_UNIQUE_NONENGLISH_PRODUCT"
NUMBER = re.compile(r"FB\d{2}-\d{3}\Z")
MARKET_SINGLE = re.compile(r"(.+) \((FB\d{2}-\d{3})\) \[Fusion World\]\Z")
MARKET_PACK = re.compile(
    r"(.+?) Booster(?: Box)? \[Fusion World\](?: \((Non-English|Asia Region Legal|Japanese)\))?\Z",
    re.I,
)
# Original published Bandai titles are identity fields. Never silently infer a
# release solely from its numeric set ID or an ambiguous translated card name.
RELEASES = {
    "FB02": ("583002", "584002", "BOOSTER PACK -BLAZING AURA- [FB02]", "ブースターパック 烈火の闘気[FB02]", "Blazing Aura"),
    "FB03": ("583003", "584003", "BOOSTER PACK -RAGING ROAR- [FB03]", "ブースターパック 怒りの咆哮[FB03]", "Raging Roar"),
    "FB04": ("583004", "584004", "BOOSTER PACK -ULTRA LIMIT- [FB04]", "ブースターパック 限界を超えし者[FB04]", "Ultra Limit"),
    "FB05": ("583005", "584005", "BOOSTER PACK -NEW ADVENTURE- [FB05]", "ブースターパック 未知なる冒険[FB05]", "New Adventure"),
    "FB06": ("583006", "584006", "BOOSTER PACK -RIVALS CLASH- [FB06]", "ブースターパック 迫り来る脅威[FB06]", "Rivals Clash"),
    "FB07": ("583007", "584007", "BOOSTER PACK -WISH FOR SHENRON- [FB07]", "ブースターパック 神龍への願い[FB07]", "Wish for Shenron"),
    "FB08": ("583008", "584008", "BOOSTER PACK -SAIYAN’s PRIDE- [FB08]", "ブースターパック 誇り高き戦闘民族[FB08]", "Saiyan's Pride"),
    "FB09": ("583009", "584009", "BOOSTER PACK -DUAL EVOLUTION- [FB09]", "ブースターパック DUAL EVOLUTION [FB09]", "Dual Evolution"),
    "FB10": ("583010", "584010", "BOOSTER PACK -CROSS FORCE- [FB10]", "ブースターパック CROSS FORCE [FB10]", "Cross Force"),
    "FB11": ("583011", "584011", "BOOSTER PACK -BRIGHTNESS OF HOPE- [FB11]", "ブースターパック BRIGHTNESS OF HOPE [FB11]", "Brightness of Hope"),
}
JP_SET_IDS = frozenset(row[1] for row in RELEASES.values())


def _official_release(ref: dict, *, language: str) -> str | None:
    if (ref.get("provider") != PROVIDER
            or ref.get("system_code") != SYSTEM
            or ref.get("language") != language):
        return None
    number = ref.get("card_number")
    if not isinstance(number, str) or not NUMBER.fullmatch(number):
        return None
    code = number.split("-", 1)[0]
    identity = RELEASES.get(code)
    if not identity:
        return None
    official_set = identity[0] if language == "English" else identity[1]
    official_title = identity[2] if language == "English" else identity[3]
    if (ref.get("set_id") != official_set
            or ref.get("set_name") != official_title
            or ref.get("provider_id") != official_set + ":" + number
            or not isinstance(ref.get("name"), str)
            or not ref["name"].strip()):
        return None
    return code


def _market_release_expansions(packaging: dict) -> dict[str, dict]:
    """Validate separately identified English and non-English market releases.

    Expansion mapping must agree across boosters and booster boxes. If a
    regional release maps to two different expansions, fail the entire release
    closed instead of picking whichever is quoted/priced.
    """
    observed: dict[tuple[str, str], set[int]] = defaultdict(set)
    regional_labels: dict[tuple[str, int], set[str]] = defaultdict(set)
    for pack in packaging.values():
        category, ident = pack.get("categoryName"), pack.get("idCategory")
        if (category, ident) not in {
            ("Dragon Ball Super Boosters", 1050),
            ("Dragon Ball Super Booster Boxes", 1052),
        }:
            continue
        match = MARKET_PACK.fullmatch(str(pack.get("name") or ""))
        expansion = pack.get("idExpansion")
        if not match or type(expansion) is not int or expansion <= 0:
            continue
        title = normalized(match[1])
        for code, release in RELEASES.items():
            if title != normalized(release[4]):
                continue
            region = "NON_ENGLISH" if match[2] else "ENGLISH"
            observed[(code, region)].add(expansion)
            if match[2]:
                regional_labels[(code, expansion)].add(match[2])
    results = {}
    for code in RELEASES:
        english = observed.get((code, "ENGLISH"), set())
        foreign = observed.get((code, "NON_ENGLISH"), set())
        if len(english) != 1 or len(foreign) != 1:
            continue
        en_exp, region_exp = next(iter(english)), next(iter(foreign))
        if en_exp == region_exp:
            continue
        results[code] = {
            "english_expansion": en_exp,
            "regional_expansion": region_exp,
            "region_label": "/".join(sorted(regional_labels[(code, region_exp)])),
        }
    return results


def match_regional_boosters(
    references: list[dict], singles: dict, packaging: dict
) -> dict:
    """Find only one exact regional product per official base Japanese card."""
    expansions = _market_release_expansions(packaging)
    english: dict[tuple[str, str], list[dict]] = defaultdict(list)
    japanese: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for ref in references:
        code = _official_release(ref, language="English")
        if code is not None:
            english[(code, ref["card_number"])].append(ref)
        code = _official_release(ref, language="Japanese")
        if code is not None:
            japanese[(code, ref["card_number"])].append(ref)
    all_products: dict[tuple[int, str, str], list[dict]] = defaultdict(list)
    for product in singles.values():
        if (product.get("idCategory") != 1049
                or product.get("categoryName") != "Dragon Ball Super Singles"
                or type(product.get("idProduct")) is not int
                or product["idProduct"] <= 0):
            continue
        exact = MARKET_SINGLE.fullmatch(str(product.get("name") or ""))
        expansion = product.get("idExpansion")
        if exact and type(expansion) is int and expansion > 0:
            all_products[(expansion, exact[2], normalized(exact[1]))].append(product)

    result = {}
    market_products_used = set()
    for (code, number), candidates in japanese.items():
        counterparts = english.get((code, number), [])
        region = expansions.get(code)
        if len(candidates) != 1 or len(counterparts) != 1 or region is None:
            continue
        jp, en = candidates[0], counterparts[0]
        products = all_products.get(
            (region["regional_expansion"], number, normalized(en["name"])), []
        )
        # A different artwork/foil/printing sharing the collector number is
        # still a duplicate even if just one product has a market price.
        if len(products) != 1:
            continue
        product = products[0]
        if product["idProduct"] in market_products_used:
            continue
        market_products_used.add(product["idProduct"])
        result[jp["provider_id"]] = {
            "code": code,
            "product": product,
            "english_provider_id": en["provider_id"],
            "english_set_id": en["set_id"],
            **region,
        }
    return result


def regional_booster_quote(
    ref: dict, match: dict, price: dict | None, observed: datetime, fx,
) -> dict | None:
    """Indicate *regional guide* only; never reprice a Japanese physical card."""
    if _official_release(ref, language="Japanese") != match.get("code"):
        return None
    product = match["product"]
    if (not isinstance(price, dict)
            or price.get("idCategory") != 1049
            or str(price.get("idProduct")) != str(product.get("idProduct"))
            or product.get("idExpansion") != match.get("regional_expansion")
            or match.get("english_expansion") == match.get("regional_expansion")
            or not match.get("region_label")):
        return None
    try:
        original = _minor(price.get("trend"))
        gbp = int((Decimal(original) * fx.rate).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        if original <= 0 or gbp <= 0:
            return None
    except (ValueError, TypeError, ArithmeticError):
        return None
    return {
        "source": SOURCE,
        "product_id": str(product["idProduct"]),
        "expansion_id": match["regional_expansion"],
        "source_field": "trend",
        "finish": "Non-English regional printing guide",
        "original_currency": "EUR",
        "original_minor": original,
        "price_gbp_minor": gbp,
        "observed_at": observed.isoformat(),
        "valuation_role": "MIXED_NON_ENGLISH_REFERENCE",
        "reference_language": "Japanese",
        "marketplace_region_label": match["region_label"],
        "physical_language_confirmed": False,
        "physical_valuation_eligible": False,
        "condition_specific": False,
        "match_basis": MATCH_BASIS,
        "reference_printing_id": ref["provider_id"],
        "reference_rarity": ref.get("rarity"),
        "reference_identity": {
            key: ref[key] for key in ("name", "set_id", "card_number", "set_name")
        },
        "english_checklist_provider_id": match["english_provider_id"],
        "english_checklist_set_id": match["english_set_id"],
        "english_marketplace_expansion_id": match["english_expansion"],
        "fx_rate_to_gbp": str(fx.rate),
        "fx_source": fx.source,
        "fx_effective_at": fx.effective_at.isoformat(),
        "fx_retrieved_at": fx.retrieved_at.isoformat(),
    }


def regional_coverage_report(
    references: list[dict], matches: dict, prices: dict
) -> dict:
    """Bounded, owner-independent per-set pipeline attribution.

    Distinguish processed catalogue identities from real source quotes; a batch
    spanning 1,585 references can produce zero new valuations if the source is
    empty, and must report that fact rather than inventing success.
    """
    by_release = {}
    for code, release in RELEASES.items():
        checked = [row for row in references
                   if row.get("language") == "Japanese" and row.get("set_id") == release[1]]
        base = sum(_official_release(row, language="Japanese") == code for row in checked)
        unique = sum(key.startswith(release[1] + ":") for key in matches)
        with_trend = sum(
            key.startswith(release[1] + ":")
            and prices.get(str(item["product"]["idProduct"])) is not None
            and prices[str(item["product"]["idProduct"])].get("trend") is not None
            for key, item in matches.items()
        )
        by_release[code] = {
            "checked": len(checked),
            "base_candidate_count": base,
            "unique_market_matches": unique,
            "source_trend_present": with_trend,
        }
    return by_release
