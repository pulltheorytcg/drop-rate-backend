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
