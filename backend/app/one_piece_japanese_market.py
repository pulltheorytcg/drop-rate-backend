"""Evidence-gated Cardmarket Non-English One Piece price guides.

The Cardmarket public product list contains separate Non-English/Asia-region
expansions. These are *not* English prices and are NOT proof of a Japanese sale.
Map only a base printing which has a unique exact-number counterpart in the
official Japanese and English checklists, plus a unique marketplace product
and a marketplace expansion tagged Non-English/Japanese/Asia Region Legal.
The result is a non-publishable, mixed-language regional guide, not a
Japanese-condition-specific current sold market value.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .one_piece_market import SOURCE, normalized, release_identity
from .reference_market import _minor

SYSTEM = "ONE_PIECE_CARD_GAME"
JP_PROVIDER = "Punk Records"
JP_REGION_MARKERS = ("Non-English", "Japanese", "Asia Region Legal")
JP_MATCH_BASIS = "OFFICIAL_JP_EN_BASE_ID_AND_UNIQUE_NONENGLISH_MARKET_PRODUCT"
# Bandai's newer English checklist abbreviates rarity, while the independent
# Japanese checklist spells it out. Only these observed publisher labels are
# considered equivalent; unknown grades and parallel treatments fail closed.
OFFICIAL_EN_RARITIES = {
    "C": "Common", "UC": "Uncommon", "R": "Rare",
    "SR": "SuperRare", "L": "Leader", "SEC": "SecretRare",
}
# Add publisher release pairs only after an exact live-source replay. The
# official English OP15/EB04 combined checklist includes the OP15 Japanese
# booster; it must not become a generic translation rule for other releases.
BANDAI_EN_JP_RELEASES = {
    "BOOSTER PACK -ADVENTURE ON KAMI’S ISLAND- [OP15-EB04]":
        ("OP15", "ブースターパック 神の島の冒険【OP-15】"),
}


def japanese_release_code(ref: dict) -> str | None:
    if (
        ref.get("provider") != JP_PROVIDER
        or ref.get("system_code") != SYSTEM
        or ref.get("language") != "Japanese"
    ):
        return None
    title = str(ref.get("set_name") or "")
    # Reprints/parallel/promos are not equivalent to the base print on release.
    if not (title.startswith("ブースターパック ") or title.startswith("エクストラブースター ")):
        return None
    marker = re.search(r"【((?:OP|EB)-?(\d{2}))】$", title)
    if not marker:
        return None
    code = marker[1].replace("-", "").upper()
    number = str(ref.get("card_number") or "")
    if (
        ref.get("provider_id") != number
        or not re.fullmatch(r"(?:OP|EB)\d{2}-\d{3}", number)
        or number.split("-", 1)[0] != code
    ):
        return None
    return code


def _english_release_code(ref: dict) -> tuple[str, str] | None:
    if (
        ref.get("provider") not in {JP_PROVIDER, "Bandai Official"}
        or ref.get("system_code") != SYSTEM
        or ref.get("language") != "English"
        or ref.get("provider_id") != ref.get("card_number")
        or not re.fullmatch(r"(?:OP|EB)\d{2}-\d{3}", str(ref.get("card_number") or ""))
    ):
        return None
    if (ref["provider"] == "Bandai Official" and
            ref.get("set_name") not in BANDAI_EN_JP_RELEASES):
        return None
    release = release_identity(ref.get("set_name", ""), include_starters=False)
    if not release or ref["card_number"].split("-", 1)[0] != release[1]:
        return None
    if (ref["provider"] == "Bandai Official" and
            release[1] != BANDAI_EN_JP_RELEASES[ref["set_name"]][0]):
        return None
    return release


def _rarity_agrees(english: dict, japanese: dict) -> bool:
    if english.get("provider") == "Bandai Official":
        release = BANDAI_EN_JP_RELEASES.get(english.get("set_name"))
        if release is None or japanese.get("set_name") != release[1]:
            return False
        official = OFFICIAL_EN_RARITIES.get(str(english.get("rarity") or ""))
        return bool(official and normalized(official) == normalized(japanese.get("rarity")))
    return bool(normalized(english.get("rarity")) and
                normalized(english.get("rarity")) == normalized(japanese.get("rarity")))


def _market_expansions(packaging: dict) -> dict[str, tuple[int, str]]:
    """Name and region must identify one Non-English marketplace expansion."""
    by_title = defaultdict(set)
    names_by_key = {}
    for pack in packaging.values():
        if pack.get("idCategory") != 1622 or pack.get("categoryName") != "One Piece Booster":
            continue
        match = re.fullmatch(
            r"(.+?) Booster \((Non-English|Japanese|Asia Region Legal)\)",
            str(pack.get("name") or ""), re.I,
        )
        expansion = pack.get("idExpansion")
        if not match or type(expansion) is not int or expansion <= 0:
            continue
        title = normalized(match[1])
        if title == "500yearsinthefuture":
            title = "500yearsintothefuture"
        by_title[title].add(expansion)
        names_by_key.setdefault((title, expansion), set()).add(match[2])
    return {
        title: (next(iter(ids)), "/".join(sorted(names_by_key[title, next(iter(ids))])))
        for title, ids in by_title.items() if len(ids) == 1
    }


def matched_japanese_products(references: list[dict], singles: dict, packaging: dict) -> dict:
    """Strict double-checklist matching; a price cannot choose among alternatives."""
    releases = _market_expansions(packaging)
    english = defaultdict(list)
    for ref in references:
        parsed = _english_release_code(ref)
        if parsed:
            english[(parsed[1], ref["card_number"])].append((ref, parsed[0]))

    products = defaultdict(list)
    for product in singles.values():
        if product.get("idCategory") != 1621 or product.get("categoryName") != "One Piece Single":
            continue
        marker = re.fullmatch(r"(.+) \(((?:OP|EB)\d{2}-\d{3})\)", str(product.get("name") or ""))
        if marker:
            products[(product.get("idExpansion"), marker[2], normalized(marker[1]))].append(product)

    candidates = defaultdict(list)
    for jp in references:
        code = japanese_release_code(jp)
        if not code:
            continue
        counterparts = english.get((code, jp["card_number"]), [])
        if len(counterparts) != 1:
            continue
        en, title = counterparts[0]
        # Same printed number AND published rarity in independent publisher
        # checklists; a reprint in another set must never be silently borrowed.
        if (
            not _rarity_agrees(en, jp)
            or not normalized(en.get("name"))
            or (en.get("set_id") == jp.get("set_id"))
        ):
            continue
        region = releases.get(title)
        if not region:
            continue
        expansion, region_marker = region
        market_candidates = products.get(
            (expansion, jp["card_number"], normalized(en["name"])), []
        )
        # Do not pick the cheapest, first, or priced product among parallels.
        if len(market_candidates) != 1:
            continue
        candidates[jp["provider_id"]].append({
            "product": market_candidates[0],
            "english_provider_id": en["provider_id"],
            "english_set_id": en["set_id"],
            "english_checklist_provider": en["provider"],
            "region_marker": region_marker,
        })
    return {key: rows[0] for key, rows in candidates.items() if len(rows) == 1}


def japanese_nonenglish_quote(
    ref: dict, match: dict, price: dict | None, observed: datetime, conversion,
) -> dict | None:
    """GBP indicative marketplace-region guide, NEVER an exact Japanese SOLD."""
    product = match["product"]
    if (
        not price or price.get("idCategory") != 1621
        or str(price.get("idProduct")) != str(product.get("idProduct"))
        or product.get("idExpansion") is None
        or match.get("region_marker") not in {
            "Non-English", "Japanese", "Asia Region Legal",
            "Asia Region Legal/Non-English",
            "Japanese/Non-English",
        }
    ):
        return None
    try:
        euro = _minor(price.get("trend"))
        gbp = int((Decimal(euro) * conversion.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if euro <= 0 or gbp <= 0:
            return None
    except (ValueError, TypeError, ArithmeticError):
        return None
    return {
        "source": SOURCE,
        "product_id": str(product["idProduct"]),
        "expansion_id": product["idExpansion"],
        "source_field": "trend",
        "finish": "Non-English regional printing guide",
        "original_currency": "EUR",
        "original_minor": euro,
        "price_gbp_minor": gbp,
        "observed_at": observed.isoformat(),
        "valuation_role": "MIXED_NON_ENGLISH_REFERENCE",
        "condition_specific": False,
        "physical_language_confirmed": False,
        "physical_valuation_eligible": False,
        "reference_language": "Japanese",
        "marketplace_region_label": match["region_marker"],
        "match_basis": JP_MATCH_BASIS,
        "reference_printing_id": ref["provider_id"],
        "reference_rarity": ref.get("rarity"),
        "reference_identity": {
            key: ref[key] for key in ("name", "set_id", "card_number", "set_name")
        },
        "english_checklist_provider_id": match["english_provider_id"],
        "english_checklist_set_id": match["english_set_id"],
        "english_checklist_provider": match["english_checklist_provider"],
        "fx_rate_to_gbp": str(conversion.rate),
        "fx_source": conversion.source,
        "fx_effective_at": conversion.effective_at.isoformat(),
        "fx_retrieved_at": conversion.retrieved_at.isoformat(),
    }
