"""Strict non-English Cardmarket reference guides for Japanese Fusion World base cards.

Non-English marketplace products are NOT verified Japanese sales or languages.
This module only adds globally shared regional context and never authorizes
grading/condition-specific physical pricing or publishing.
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
MATCH_BASIS = "OFFICIAL_FUSION_JP_EN_BASE_PRINT_AND_UNIQUE_NONENGLISH_MARKET_PRODUCT"
REGION_MARKERS = frozenset({
    "Non-English", "Japanese", "Asia Region Legal",
    "Asia Region Legal/Non-English", "Japanese/Non-English",
})


def _booster_identity(ref: dict) -> tuple[str, str] | None:
    """Use two independent official publisher sets; never a guessed translation."""
    if ref.get("provider") != PROVIDER or ref.get("system_code") != SYSTEM:
        return None
    lang = ref.get("language")
    if lang not in {"Japanese", "English"}:
        return None
    number = ref.get("card_number")
    set_id = str(ref.get("set_id") or "")
    if (
        not isinstance(number, str)
        or re.fullmatch(r"FB\d{2}-\d{3}", number) is None
        or ref.get("provider_id") != set_id + ":" + number
        or not ref.get("name")
        or (ref.get("evidence") or {}).get("provider_variant")
        or ref.get("variant")
    ):
        return None
    code = number.split("-", 1)[0]
    # The official publisher assigns 583NNN for English booster and 584NNN
    # for Japanese booster checklists. This additionally prevents promo/set
    # aliases from being treated as an original base printing.
    if set_id != ("583" if lang == "English" else "584") + f"{int(code[2:]):03d}":
        return None
    title = str(ref.get("set_name") or "")
    if lang == "English":
        m = re.fullmatch(r"BOOSTER PACK -(.+)- \[(FB\d{2})\]", title, re.I)
        if not m or m[2].upper() != code:
            return None
        return code, normalized(m[1])
    m = re.fullmatch(r"ブースターパック .+\[(FB\d{2})\]", title)
    return (code, "") if m and m[1] == code else None


def _regional_expansions(packaging: dict) -> dict[str, tuple[int, str]]:
    """Require unambiguous labelled non-English *product*, never English lot."""
    expansion_ids: dict[str, set[int]] = defaultdict(set)
    labels: dict[tuple[str, int], set[str]] = defaultdict(set)
    for pack in packaging.values():
        category = (pack.get("idCategory"), pack.get("categoryName"))
        if category not in {
            (1050, "Dragon Ball Super Boosters"),
            (1052, "Dragon Ball Super Booster Boxes"),
        }:
            continue
        m = re.fullmatch(
            r"(.+?) Booster(?: Box)? \[Fusion World\] "
            r"\((Non-English|Japanese|Asia Region Legal)\)",
            str(pack.get("name") or ""), re.I,
        )
        expansion = pack.get("idExpansion")
        if not m or type(expansion) is not int or expansion <= 0:
            continue
        name = normalized(m[1])
        expansion_ids[name].add(expansion)
        labels[name, expansion].add(m[2])
    return {
        name: (next(iter(ids)), "/".join(sorted(labels[name, next(iter(ids))])))
        for name, ids in expansion_ids.items() if len(ids) == 1
    }


def matched_japanese_products(
    references: list[dict], singles: dict, packaging: dict,
) -> dict[str, dict]:
    """Return only exact base-print, paired-checklist, region-scoped matches."""
    english: dict[tuple[str, str], list] = defaultdict(list)
    japanese: dict[tuple[str, str], list] = defaultdict(list)
    for ref in references:
        release = _booster_identity(ref)
        if not release:
            continue
        key = (release[0], ref["card_number"])
        if ref["language"] == "Japanese":
            japanese[key].append(ref)
        else:
            english[key].append((ref, release[1]))
    regions = _regional_expansions(packaging)
    products: dict[tuple, list] = defaultdict(list)
    for market in singles.values():
        if (market.get("idCategory"), market.get("categoryName")) != (
            1049, "Dragon Ball Super Singles"
        ):
            continue
        match = re.fullmatch(
            r"(.+) \((FB\d{2}-\d{3})\) \[Fusion World\]",
            str(market.get("name") or ""),
        )
        if match:
            products[(
                market.get("idExpansion"), match[2], normalized(match[1])
            )].append(market)

    result: dict[str, dict] = {}
    for key, jp_rows in japanese.items():
        en_rows = english.get(key, [])
        if len(jp_rows) != 1 or len(en_rows) != 1:
            continue
        jp, (en, title) = jp_rows[0], en_rows[0]
        if (
            not title or not str(jp.get("name") or "").strip()
            or not normalized(en["name"])
            or jp["set_id"] == en["set_id"]
            or normalized(jp.get("rarity")) != normalized(en.get("rarity"))
        ):
            continue
        regional = regions.get(title)
        if not regional:
            continue
        expansion, label = regional
        available = products.get((expansion, jp["card_number"], normalized(en["name"])), [])
        # Price presence must never choose between two candidate printings.
        if len(available) != 1:
            continue
        result[jp["provider_id"]] = {
            "product": available[0],
            "english_provider_id": en["provider_id"],
            "english_set_id": en["set_id"],
            "region_marker": label,
        }
    return result


def japanese_nonenglish_quote(
    ref: dict, mapping: dict, price: dict | None, observed: datetime, conversion,
) -> dict | None:
    """Explicitly NOT an exact Japanese sale or verified physical-copy value."""
    market = mapping["product"]
    if (
        not price
        or price.get("idCategory") != 1049
        or str(price.get("idProduct")) != str(market.get("idProduct"))
        or type(market.get("idExpansion")) is not int
        or market["idExpansion"] <= 0
        or mapping.get("region_marker") not in REGION_MARKERS
    ):
        return None
    try:
        original = _minor(price.get("trend"))
        gbp = int(
            (Decimal(original) * conversion.rate).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        if original <= 0 or gbp <= 0:
            return None
    except (ValueError, TypeError, ArithmeticError):
        return None
    return {
        "source": SOURCE,
        "product_id": str(market["idProduct"]),
        "expansion_id": market["idExpansion"],
        "source_field": "trend",
        "finish": "Non-English regional base-print guide",
        "original_currency": "EUR",
        "original_minor": original,
        "price_gbp_minor": gbp,
        "observed_at": observed.isoformat(),
        "valuation_role": "MIXED_NON_ENGLISH_REFERENCE",
        "condition_specific": False,
        "physical_language_confirmed": False,
        "physical_valuation_eligible": False,
        "reference_language": "Japanese",
        "marketplace_region_label": mapping["region_marker"],
        "match_basis": MATCH_BASIS,
        "reference_printing_id": ref["provider_id"],
        "reference_identity": {
            field: ref[field] for field in ("name", "set_id", "card_number", "set_name")
        },
        "english_checklist_provider_id": mapping["english_provider_id"],
        "english_checklist_set_id": mapping["english_set_id"],
        "fx_rate_to_gbp": str(conversion.rate),
        "fx_source": conversion.source,
        "fx_effective_at": conversion.effective_at.isoformat(),
        "fx_retrieved_at": conversion.retrieved_at.isoformat(),
    }
