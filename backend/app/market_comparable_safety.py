"""Evidence-only rules for variants, sealed SKUs and rogue eBay asking prices.

Do not plug asking-price diagnostics directly into physical inventory market values.
The existing drop-rate-market-v4 engine remains the sole valuation authority.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median
from typing import Any, Mapping, Sequence


def _token(pattern: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])", re.I)


# Acronyms are deliberately scoped to a particular game: SR / SEC / SP
# do not mean the same treatment across franchises.
_SHARED = {
    "ALT_ART": [r"alt(?:ernat(?:e|ive))?\s+art", r"parallel\s+art"],
    "REVERSE_HOLO": [r"reverse[\s-]*(?:holo|foil)"],
    "PROMO": [r"promo(?:tional)?"],
    "FIRST_EDITION": [r"1st[\s-]*edition", r"first[\s-]*edition"],
    "STAMPED": [r"stamp(?:ed)?"],
}
_GAME = {
    "pokemon": {
        "SECRET_RARE": [r"secret[\s-]*rare"],
        "ILLUSTRATION_RARE": [r"illustration[\s-]*rare", r"\bIR\b", r"art[\s-]*rare"],
        "SPECIAL_ILLUSTRATION_RARE": [r"special[\s-]*illustration[\s-]*rare", r"\bSIR\b", r"\bSAR\b"],
        "FULL_ART": [r"full[\s-]*art"],
        "RAINBOW_RARE": [r"rainbow[\s-]*rare"],
        "GOLD_RARE": [r"gold[\s-]*rare", r"hyper[\s-]*rare"],
        "SHADOWLESS": [r"shadowless"],
    },
    "one piece": {
        "SECRET_RARE": [r"secret[\s-]*rare", r"\bSEC\b"],
        "SUPER_RARE": [r"super[\s-]*rare", r"\bSR\b"],
        "MANGA_RARE": [r"manga(?:[\s-]*(?:rare|alt|art))?"],
        "SP_RARE": [r"special[\s-]*parallel", r"\bSP\b"],
        "TREASURE_RARE": [r"treasure[\s-]*rare"],
        "PARALLEL": [r"parallel", r"\bAA\b"],
    },
    "dragon ball": {
        "SECRET_RARE": [r"secret[\s-]*rare", r"\bSCR\b"],
        "SPECIAL_RARE": [r"special[\s-]*rare", r"\bSPR\b"],
        "SUPER_RARE": [r"super[\s-]*rare", r"\bSR\b"],
    },
    "yu-gi-oh": {
        "QUARTER_CENTURY_SECRET": [r"quarter[\s-]*century[\s-]*secret[\s-]*rare", r"\bQCR\b"],
        "PRISMATIC_SECRET": [r"prismatic[\s-]*secret[\s-]*rare"],
        "SECRET_RARE": [r"secret[\s-]*rare"],
        "COLLECTORS_RARE": [r"collector'?s?[\s-]*rare"],
        "ULTRA_RARE": [r"ultra[\s-]*rare"],
    },
    "lorcana": {"ENCHANTED": [r"enchanted"]},
    "magic": {
        "SHOWCASE": [r"showcase"],
        "BORDERLESS": [r"borderless"],
        "EXTENDED_ART": [r"extended[\s-]*art"],
        "ETCHED_FOIL": [r"etched[\s-]*foil"],
        "SERIALIZED": [r"seriali[sz]ed"],
    },
    "riftbound": {"ALTERNATE_ART": [r"alternate[\s-]*art"]},
    "naruto": {"PARALLEL": [r"parallel"]},
}
_SPECIAL = frozenset({
    "ALT_ART", "REVERSE_HOLO", "PROMO", "FIRST_EDITION", "STAMPED",
    "SECRET_RARE", "ILLUSTRATION_RARE", "SPECIAL_ILLUSTRATION_RARE",
    "FULL_ART", "RAINBOW_RARE", "GOLD_RARE", "SHADOWLESS", "SUPER_RARE",
    "MANGA_RARE", "SP_RARE", "TREASURE_RARE", "PARALLEL", "SPECIAL_RARE",
    "QUARTER_CENTURY_SECRET", "PRISMATIC_SECRET", "COLLECTORS_RARE",
    "ULTRA_RARE", "ENCHANTED", "SHOWCASE", "BORDERLESS", "EXTENDED_ART",
    "ETCHED_FOIL", "SERIALIZED", "ALTERNATE_ART",
})
_PREFERRED = {
    "SPECIAL_ILLUSTRATION_RARE": {"ILLUSTRATION_RARE"},
    "QUARTER_CENTURY_SECRET": {"SECRET_RARE"},
    "PRISMATIC_SECRET": {"SECRET_RARE"},
    "MANGA_RARE": {"ALT_ART", "PARALLEL"},
    "SP_RARE": {"PARALLEL"},
}
_GAME_ALIASES = {
    "pokemon tcg": "pokemon", "pokémon": "pokemon",
    "one piece card game": "one piece", "one-piece": "one piece",
    "dragon ball fusion world": "dragon ball", "dragon ball super": "dragon ball",
    "dragon ball masters": "dragon ball", "fusion world": "dragon ball",
    "yugioh": "yu-gi-oh", "yu gi oh": "yu-gi-oh", "yu-gi-oh!": "yu-gi-oh",
    "magic the gathering": "magic", "mtg": "magic",
    "disney lorcana": "lorcana",
}


def normal_game(game: object) -> str:
    g = " ".join(re.sub(r"[^\w\s]", " ", str(game or "").casefold()).split())
    return _GAME_ALIASES.get(g, g)


def treatment_signals(game: object, text: object) -> frozenset[str]:
    """Game-scoped unambiguous treatment clues; never infer a treatment from price."""
    g = normal_game(game)
    source = str(text or "")
    rules = {**_SHARED, **_GAME.get(g, {})}
    present = {label for label, expressions in rules.items()
               if any(_token(expression).search(source) for expression in expressions)}
    for stronger, redundant in _PREFERRED.items():
        if stronger in present:
            present.difference_update(redundant)
    return frozenset(present)


@dataclass(frozen=True)
class TreatmentResult:
    status: str
    target: tuple[str, ...]
    listing: tuple[str, ...]
    conflicts: tuple[str, ...]
    missing_evidence: tuple[str, ...]


def evaluate_treatment(
    *, game: str, requested_name: str, requested_variant: str | None,
    requested_rarity: str | None, listing_title: str,
) -> TreatmentResult:
    """Absence => review. Explicit wrong treatment => reject.

    This is an independent safety helper for the eBay matching pipeline; it
    never asserts that a title alone verifies a complete print identity.
    """
    wanted = treatment_signals(game, " ".join(filter(None, (
        requested_name, requested_variant, requested_rarity))))
    observed = treatment_signals(game, listing_title)
    conflicts = sorted(x for x in observed if x in _SPECIAL and x not in wanted)
    missing = sorted(x for x in wanted if x in _SPECIAL and x not in observed)
    return TreatmentResult(
        status="REJECTED" if conflicts else "REVIEW_REQUIRED" if missing else "NO_TREATMENT_CONFLICT",
        target=tuple(sorted(wanted)),
        listing=tuple(sorted(observed)),
        conflicts=tuple(conflicts),
        missing_evidence=tuple(missing),
    )


_SEALED_TYPES = {
    "BOOSTER_BOX": [r"booster[\s-]*box"],
    "BOOSTER_PACK": [r"booster[\s-]*pack", r"single[\s-]*pack"],
    "ELITE_TRAINER_BOX": [r"elite[\s-]*trainer[\s-]*box", r"\bETB\b"],
    "DISPLAY": [r"booster[\s-]*display", r"display[\s-]*box"],
    "CASE": [r"factory[\s-]*case", r"booster[\s-]*case", r"sealed[\s-]*case"],
    "COLLECTION_BOX": [r"collection[\s-]*box"],
    "STARTER_DECK": [r"starter[\s-]*deck", r"theme[\s-]*deck"],
    "BUNDLE": [r"booster[\s-]*bundle"],
}
_PACKAGING_RISKS = [
    r"opened", r"unsealed", r"empty[\s-]*box", r"box[\s-]*only",
    r"repack(?:ed|aging)?", r"reseal(?:ed)?", r"weighed",
    r"loose[\s-]*cards?", r"proxy", r"replica", r"counterfeit",
]


def sealed_product_type(title: str) -> frozenset[str]:
    return frozenset(key for key, variants in _SEALED_TYPES.items()
                     if any(_token(x).search(title) for x in variants))


def verify_sealed_product(*, expected_type: str, title: str) -> str:
    """Check exact pack-vs-box-vs-case family and reject opened/repacked."""
    if any(_token(x).search(title) for x in _PACKAGING_RISKS):
        return "REJECTED_UNSAFE_SEAL"
    actual = sealed_product_type(title)
    if expected_type not in _SEALED_TYPES:
        return "REVIEW_UNKNOWN_SEALED_TYPE"
    if actual and (expected_type not in actual or len(actual) > 1):
        return "REJECTED_WRONG_SEALED_TYPE"
    if not actual:
        return "REVIEW_UNVERIFIED_PACKAGING"
    if not _token(r"factory[\s-]*sealed|sealed|unopened").search(title):
        return "REVIEW_SEAL_NOT_VERIFIED"
    return "POTENTIAL_MATCH_REQUIRES_IDENTITY_REVIEW"


def _money_minor(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number > 100_000:
            return None
        minor = int((number * Decimal(100)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return minor if minor > 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def asking_price_diagnostics(
    candidates: Sequence[Mapping[str, Any]], *, min_listings: int = 5,
    min_sellers: int = 3,
) -> dict[str, Any]:
    """Same-identity GBP asking context; NOT a sold-derived market value.

    Only independently approved EXACT_MATCH records with unique seller/item
    IDs are considered. The caller must itself verify canonical identity and
    grades; a seller query match alone is never adequate.
    """
    if not (3 <= min_listings <= 100 and 2 <= min_sellers <= 100):
        raise ValueError("invalid evidence thresholds")
    items: dict[str, dict[str, Any]] = {}
    conflicted: set[str] = set()
    rejected = 0
    for row in candidates:
        if not isinstance(row, Mapping):
            rejected += 1
            continue
        item = str(row.get("source_item_id") or "").strip()
        seller = str(row.get("seller_id") or "").strip()
        amount = _money_minor(row.get("asking_price_gbp"))
        eligible = (row.get("match_status") == "EXACT_MATCH"
                    and row.get("observation_type") == "ACTIVE"
                    and row.get("actual_paid_price_verified") is False
                    and row.get("currency") == "GBP"
                    and row.get("source") in {"EBAY_BROWSE", "EBAY_BROWSE_UK"}
                    and item and seller and amount is not None)
        if not eligible:
            rejected += 1
            continue
        candidate = {"id": item, "seller": seller, "price_minor": amount}
        if item in items and items[item] != candidate:
            conflicted.add(item)
        else:
            items[item] = candidate
    for item in conflicted:
        items.pop(item, None)
    groups: dict[str, list[int]] = defaultdict(list)
    for candidate in items.values():
        groups[candidate["seller"]].append(candidate["price_minor"])
    seller_medians = [int(median(values)) for values in groups.values()]
    base = {
        "basis": "EBAY_BROWSE_ACTIVE_ASKING_ONLY",
        "market_value_gbp": None,
        "market_value_eligible": False,
        "verified_sold_count": 0,
        "actual_paid_price_verified": False,
        "source_listing_count": len(items),
        "source_seller_count": len(groups),
        "rejected_input_count": rejected + len(conflicted),
        "currency": "GBP",
    }
    if len(items) < min_listings or len(groups) < min_sellers:
        return {**base, "status": "INSUFFICIENT_EXACT_ASKS", "asking_price_median_gbp": None,
                "outliers": []}
    centre = float(median(seller_medians))
    mad = float(median([abs(p - centre) for p in seller_medians]))
    sigma = 1.4826 * mad
    threshold = max(3.5 * sigma, centre * 0.40, 200.0)
    accepted = [v for v in items.values() if abs(v["price_minor"] - centre) <= threshold]
    outliers = [v for v in items.values() if abs(v["price_minor"] - centre) > threshold]
    counted_sellers = {v["seller"] for v in accepted}
    enough = len(accepted) >= min_listings and len(counted_sellers) >= min_sellers
    kept_sellers: dict[str, list[int]] = defaultdict(list)
    for v in accepted:
        kept_sellers[v["seller"]].append(v["price_minor"])
    seller_weighted = [int(median(values)) for values in kept_sellers.values()]
    estimate = int(median(seller_weighted)) if enough else None
    return {
        **base,
        "status": "ASKING_CONTEXT_ONLY" if enough else "INSUFFICIENT_AFTER_OUTLIER_FILTER",
        "asking_price_median_gbp": str((Decimal(estimate) / 100).quantize(Decimal("0.01"))) if estimate else None,
        "accepted_listing_count": len(accepted),
        "accepted_seller_count": len(counted_sellers),
        "outliers": [
            {"source_item_id": row["id"], "asking_price_gbp": str((Decimal(row["price_minor"])/100).quantize(Decimal("0.01"))),
             "reason": "ROBUST_EXTREME_ASKING_PRICE"}
            for row in outliers
        ],
        "outlier_method": "seller-median-centred MAD with 40pct minimum guard",
        "review_required": True,
    }


@dataclass(frozen=True)
class CollectibleReview:
    """Discovery guardrail, NOT proof of an exact product or a paid sale."""
    status: str
    conflicting: tuple[str, ...]
    missing: tuple[str, ...]


def _contains_identifier(title: str, identifier: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(identifier) + r"(?![A-Za-z0-9])", title, re.I))


def review_noncard_identity(category: str, expected: Mapping[str, Any], title: str) -> CollectibleReview:
    """Conservative title checks for comics, manga, Funko, figures and sealed.

    No title-only result may be labelled EXACT_MATCH; eBay item specifics and
    product condition still need independent validation before use.
    """
    category = str(category).strip().casefold()
    title = str(title or "")
    conflicts: list[str] = []
    missing: list[str] = []
    low = title.casefold()
    if _token(r"replica|counterfeit|proxy|empty[\s-]*box|box[\s-]*only|fake").search(title):
        conflicts.append("UNSAFE_PRODUCT")

    if category in {"comic", "comics"}:
        if _token(r"facsimile|trade[\s-]*paperback|omnibus|collected[\s-]*edition|lot|bundle").search(title):
            conflicts.append("NOT_SINGLE_ORIGINAL_ISSUE")
        issue = str(expected.get("issue_number") or "").strip().lstrip("#")
        found = re.search(r"(?<![A-Za-z0-9])#\s*(\d+[A-Za-z]?)\b", title)
        if issue:
            if found and found.group(1).casefold() != issue.casefold():
                conflicts.append("ISSUE_NUMBER_MISMATCH")
            elif not found:
                missing.append("ISSUE_NUMBER_UNVERIFIED")
        else:
            missing.append("ISSUE_NUMBER_REQUIRED")
        cover = str(expected.get("variant") or "").strip()
        match = re.search(r"\bcover[\s-]*([A-Z])\b", title, re.I)
        if cover:
            wanted = re.search(r"\bcover[\s-]*([A-Z])\b", cover, re.I)
            if wanted and match and wanted.group(1).lower() != match.group(1).lower():
                conflicts.append("COVER_VARIANT_MISMATCH")
            elif wanted and not match:
                missing.append("COVER_VARIANT_UNVERIFIED")
        elif match and match.group(1).upper() != "A":
            missing.append("COVER_VARIANT_NOT_SPECIFIED")
        printing = str(expected.get("printing") or "")
        visible_print = re.search(r"\b(1st|2nd|3rd|first|second|third)\s+print(?:ing)?\b", title, re.I)
        if printing and visible_print:
            equivalent = {"1st": "first", "2nd": "second", "3rd": "third"}
            wanted = equivalent.get(printing.split()[0].casefold(), printing.split()[0].casefold())
            listed = equivalent.get(visible_print.group(1).casefold(), visible_print.group(1).casefold())
            if wanted != listed:
                conflicts.append("PRINTING_MISMATCH")
        if expected.get("grading_company") and expected.get("grade"):
            company = str(expected["grading_company"])
            grade = str(expected["grade"])
            if not re.search(r"(?<![A-Za-z0-9])" + re.escape(company) + r"\s*" + re.escape(grade) + r"(?![\d.])", title, re.I):
                missing.append("GRADE_UNVERIFIED")
            for found_grade in re.finditer(r"\b(?:CGC|CBCS|PGX)\s*(\d+(?:\.\d+)?)\b", title, re.I):
                if Decimal(found_grade.group(1)) != Decimal(grade):
                    conflicts.append("GRADE_MISMATCH")

    elif category == "manga":
        if _token(r"omnibus|box[\s-]*set|complete[\s-]*set|bundle|lot").search(title) and not expected.get("omnibus"):
            conflicts.append("MANGA_SINGLE_VS_SET")
        volume = str(expected.get("volume") or "").strip()
        visible = re.search(r"\bvol(?:ume)?\.?\s*(\d+)\b", title, re.I)
        if volume:
            if visible and str(int(visible.group(1))) != str(int(volume)) if volume.isdigit() else False:
                conflicts.append("VOLUME_MISMATCH")
            elif not visible:
                missing.append("VOLUME_UNVERIFIED")
        isbn = re.sub(r"[^0-9X]", "", str(expected.get("isbn") or ""), flags=re.I).upper()
        if isbn:
            if not _contains_identifier(re.sub(r"[-\s]", "", title), isbn):
                visible_isbn = re.findall(r"\b(?:97[89]\d{10}|\d{9}[\dX])\b", re.sub(r"[-\s]", "", title), re.I)
                if visible_isbn:
                    conflicts.append("ISBN_MISMATCH")
                else:
                    missing.append("ISBN_UNVERIFIED")

    elif category in {"funko", "figure", "figures"}:
        if _token(r"box[\s-]*only|empty[\s-]*box|lot|bundle").search(title):
            conflicts.append("FUNKO_NOT_SINGLE_COMPLETE_PRODUCT")
        number = str(expected.get("product_number") or "").strip().lstrip("#")
        found = re.search(r"(?<![A-Za-z0-9])#\s*(\d{1,5})\b", title)
        if number:
            if found and found.group(1).lstrip("0") != number.lstrip("0"):
                conflicts.append("PRODUCT_NUMBER_MISMATCH")
            elif not found:
                missing.append("PRODUCT_NUMBER_UNVERIFIED")
        else:
            missing.append("PRODUCT_NUMBER_REQUIRED")
        for treatment in ("chase", "exclusive", "limited", "signed", "autographed"):
            listed = bool(_token(treatment).search(title))
            requested = bool(_token(treatment).search(" ".join(str(expected.get(k) or "") for k in ("variant", "edition", "signature_status"))))
            if listed and not requested:
                conflicts.append(treatment.upper() + "_UNREQUESTED")
            elif requested and not listed:
                missing.append(treatment.upper() + "_UNVERIFIED")
        if _token(r"damaged[\s-]*box|no[\s-]*box|out[\s-]*of[\s-]*box").search(title) and str(expected.get("box_condition") or "").casefold() in {"mint", "new", "new in box"}:
            conflicts.append("BOX_CONDITION_MISMATCH")
        if category == "funko":
            wanted_line = str(expected.get("product_type") or "Pop")
            if _token(r"funko[\s-]*soda").search(title) and _token(r"pop").search(wanted_line):
                conflicts.append("FUNKO_SODA_VS_POP")

    elif category in {"sealed", "sealed_tcg"}:
        result = verify_sealed_product(expected_type=str(expected.get("product_type") or ""), title=title)
        if result.startswith("REJECTED"):
            conflicts.append(result)
        elif result.startswith("REVIEW"):
            missing.append(result)
    else:
        missing.append("CATEGORY_NOT_SUPPORTED")

    # A title is search context, not verified structured print/condition proof.
    return CollectibleReview(
        status="REJECTED" if conflicts else "REVIEW_REQUIRED",
        conflicting=tuple(dict.fromkeys(conflicts)),
        missing=tuple(dict.fromkeys(missing)),
    )
