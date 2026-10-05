"""Read-only exact-card market evidence for approved social-content research."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from typing import Any

from .ebay_official_adapter import _looks_like_multi_item_listing
from .ebay_sold_pricing import SoldComparable, _money_minor, _sold_at
from .ebay_uk_parse_adapter import _contains_term, _normalise_text


_NON_ENGLISH = (
    "japanese", "jpn", "jp", "korean", "kr", "chinese", "cn",
    "german", "french", "italian", "spanish", "portuguese",
)
_GRADING_TERMS = ("psa", "bgs", "beckett", "cgc", "sgc", "ace", "graded", "slab")


@dataclass(frozen=True, slots=True)
class SocialMarketTarget:
    key: str
    display_name: str
    query: str
    card_number: str
    required_name_terms: tuple[str, ...]
    grading_company: str | None = None
    grade: str | None = None
    print_family: str | None = None


TARGETS = (
    SocialMarketTarget(
        key="umbreon_vmax_215_raw",
        display_name="Umbreon VMAX 215/203 — Raw",
        query="Umbreon VMAX 215/203 Evolving Skies English",
        card_number="215/203",
        required_name_terms=("umbreon", "vmax"),
    ),
    SocialMarketTarget(
        key="umbreon_vmax_215_psa10",
        display_name="Umbreon VMAX 215/203 — PSA 10",
        query="Umbreon VMAX 215/203 Evolving Skies English PSA 10",
        card_number="215/203",
        required_name_terms=("umbreon", "vmax"),
        grading_company="psa",
        grade="10",
    ),
    SocialMarketTarget(
        key="goku_fb01_139_p2_raw",
        display_name="Son Goku FB01-139 _p2 Super Alternate Art — Raw",
        query="Son Goku FB01-139 Super Alt Art English",
        card_number="FB01-139",
        required_name_terms=("son", "goku"),
        print_family="goku_super_alt",
    ),
    SocialMarketTarget(
        key="goku_fb01_139_p2_psa10",
        display_name="Son Goku FB01-139 _p2 Super Alternate Art — PSA 10",
        query="Son Goku FB01-139 Super Alt Art English PSA 10",
        card_number="FB01-139",
        required_name_terms=("son", "goku"),
        grading_company="psa",
        grade="10",
        print_family="goku_super_alt",
    ),
)


def _english_title(title: str) -> bool:
    normalised = _normalise_text(title)
    return not any(_contains_term(normalised, term) for term in _NON_ENGLISH)


def _goku_super_alt(title: str) -> bool:
    normalised = _normalise_text(title)
    # Exact p2/SCR-double-star listings are not described consistently by sellers.
    # Require one strong "super" printing marker, never merely "alternate art".
    phrases = (
        "super alt art",
        "super alternate art",
        "super alternative art",
        "god rare",
        "gdr",
        "double star",
        "2 star",
        "two star",
        "ghost",
    )
    return any(_contains_term(normalised, phrase) for phrase in phrases)


def _grade_matches(title: str, target: SocialMarketTarget) -> bool:
    normalised = _normalise_text(title)
    if target.grading_company:
        if not _contains_term(normalised, target.grading_company):
            return False
        if not _contains_term(normalised, str(target.grade or "")):
            return False
        return True
    return not any(_contains_term(normalised, term) for term in _GRADING_TERMS)


def matches_target(row: dict[str, Any], target: SocialMarketTarget) -> bool:
    title = row.get("title")
    if not isinstance(title, str) or not title.strip():
        return False
    if _looks_like_multi_item_listing(title):
        return False

    normalised = _normalise_text(title)
    if not _contains_term(normalised, target.card_number):
        return False
    if any(not _contains_term(normalised, term) for term in target.required_name_terms):
        return False
    if not _english_title(title):
        return False
    if target.print_family == "goku_super_alt" and not _goku_super_alt(title):
        return False
    if not _grade_matches(title, target):
        return False
    return True


def select_newest_exact_comps(
    payload: dict[str, Any],
    *,
    target: SocialMarketTarget,
    limit: int = 5,
) -> list[SoldComparable]:
    if limit < 1:
        raise ValueError("limit must be positive")
    if str(payload.get("currency") or "").strip().upper() != "GBP":
        raise ValueError("Sold-data response is not GBP / eBay UK")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("Sold-data response is missing results")

    accepted: dict[str, SoldComparable] = {}
    for row in rows:
        if not isinstance(row, dict) or not matches_target(row, target):
            continue
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            continue
        sold_at = _sold_at(row.get("date_sold"))
        price_minor = _money_minor(row.get("sale_price"))
        if sold_at is None or price_minor is None or price_minor <= 0:
            continue
        shipping_minor = _money_minor(row.get("shipping_price"))
        accepted[item_id] = SoldComparable(
            item_id=item_id,
            title=str(row.get("title") or "").strip(),
            sold_at=sold_at,
            price_minor=price_minor,
            shipping_minor=shipping_minor,
            condition_raw=(
                str(row.get("condition_raw")).strip()
                if row.get("condition_raw") is not None
                else None
            ),
            url=(str(row.get("item_link")).strip() if row.get("item_link") else None),
        )

    return sorted(
        accepted.values(),
        key=lambda comp: comp.sold_at,
        reverse=True,
    )[:limit]


def summarise_exact_market(
    target: SocialMarketTarget,
    comps: list[SoldComparable],
    *,
    usd_to_gbp_rate: Decimal,
    fx_effective_at: datetime,
    fx_retrieved_at: datetime,
) -> dict[str, Any]:
    if usd_to_gbp_rate <= 0:
        raise ValueError("USD/GBP rate must be positive")
    if fx_effective_at.tzinfo is None or fx_retrieved_at.tzinfo is None:
        raise ValueError("FX timestamps must be timezone-aware")

    payload = {
        "target": target.key,
        "display_name": target.display_name,
        "query": target.query,
        "comparable_count": len(comps),
        "method": "MEDIAN_OF_FIVE_NEWEST_EXACT_EBAY_GB_SALES",
        "currency": "GBP",
        "market_value_gbp_minor": None,
        "market_value_usd_minor": None,
        "fx": {
            "source": "ECB_EURO_REFERENCE_RATES",
            "usd_to_gbp_rate": str(usd_to_gbp_rate),
            "effective_at": fx_effective_at.isoformat(),
            "retrieved_at": fx_retrieved_at.isoformat(),
        },
        "comps": [
            {
                "item_id": comp.item_id,
                "title": comp.title,
                "sold_at": comp.sold_at.isoformat(),
                "price_gbp_minor": comp.price_minor,
                "shipping_gbp_minor": comp.shipping_minor,
                "url": comp.url,
            }
            for comp in comps
        ],
    }
    if len(comps) < 5:
        payload["status"] = "INSUFFICIENT_EVIDENCE"
        payload["reason"] = "Fewer than five exact comparable eBay UK sold records"
        return payload

    market_gbp = int(median([comp.price_minor for comp in comps]))
    market_usd = int(
        (Decimal(market_gbp) / usd_to_gbp_rate).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )
    payload["status"] = "READY"
    payload["reason"] = None
    payload["market_value_gbp_minor"] = market_gbp
    payload["market_value_usd_minor"] = market_usd
    return payload
