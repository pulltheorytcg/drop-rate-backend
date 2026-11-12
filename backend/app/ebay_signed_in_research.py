"""Read-only, human-reviewed eBay UK Product Research preview.

This module does NOT fetch eBay pages, reuse browser cookies, bypass access
controls, ingest production evidence or write a Market Value. It accepts
manually reviewed, item-level sale records and reuses the existing exact-print
matcher and five-sold median ONLY to produce a non-publishable candidate.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from .ebay_sold_pricing import _matches_comp, _query_for_target

REQUIRED_TARGET = ("game", "name", "set_name", "card_number", "variant", "language")
MAX_ROWS = 100
MAX_AGE = timedelta(days=90)
RECENT_AGE = timedelta(days=14)
MAX_FUTURE_DRIFT = timedelta(minutes=5)
OFFICIAL_RESEARCH_HELP = "https://www.ebay.co.uk/help/selling/selling-tools/product-research?id=4853"


def build_sold_search_url(target: dict) -> str:
    """A link to open manually in the already signed-in eBay UK browser."""
    _validate_target(target)
    return "https://www.ebay.co.uk/sch/i.html?" + urlencode({
        "_nkw": _query_for_target(target),
        "LH_Sold": "1",
        "LH_Complete": "1",
    })


def _validate_target(target: dict) -> None:
    if not isinstance(target, dict):
        raise ValueError("Canonical target object required")
    if any(not isinstance(target.get(k), str) or not target[k].strip() for k in REQUIRED_TARGET):
        raise ValueError("Exact canonical game, name, set, number, variant and language required")
    if bool(target.get("grading_company")) != bool(target.get("grade")):
        raise ValueError("Grading company and grade must both be supplied")
    if not target.get("grading_company") and (
        not isinstance(target.get("condition"), str) or not target["condition"].strip()
    ):
        raise ValueError("Raw item condition required")


def _minor(amount: object, *, allow_zero: bool = False) -> int | None:
    if isinstance(amount, bool) or not isinstance(amount, (str, int, float, Decimal)):
        return None
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        return None
    if (not value.is_finite() or value < 0 or value >= Decimal("100000000")
            or value.as_tuple().exponent < -2 or (not allow_zero and value == 0)):
        return None
    return int(value * 100)


def _sold_day(value: object) -> date | None:
    """Sale date only: never invent a precise transaction time."""
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        sold = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if sold.tzinfo is None or sold.utcoffset() is None:
        return None
    return sold.astimezone(timezone.utc).date()


def preview_product_research(
    target: dict,
    rows: list[dict],
    *,
    now: datetime | None = None,
) -> dict:
    """Preview without treating manually transcribed claims as verified data.

    Input rows deliberately use a small, typed contract: item_id, title,
    sold_at (ISO date or timezone-aware datetime), price_gbp,
    shipping_gbp (optional), currency, item_country, source,
    sale_price_basis, condition_raw and exact set/number/variant/language.
    The source must be EBAY_PRODUCT_RESEARCH and the basis ACTUAL_PAID_PRICE.
    Neither a sold-listing asking price nor an unknown Best Offer qualifies.
    """
    _validate_target(target)
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("At most 100 reviewed sale rows may be previewed")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware reference date required")
    now = now.astimezone(timezone.utc)

    rejected = Counter()
    eligible = {}
    duplicated = set()
    for row in rows:
        if not isinstance(row, dict):
            rejected["INVALID_ROW"] += 1
            continue
        item_id = str(row.get("item_id") or "").strip()
        if not item_id.isascii() or not item_id.isdigit() or len(item_id) > 20:
            rejected["INVALID_ITEM_ID"] += 1
            continue
        if item_id in duplicated:
            rejected["DUPLICATE_ITEM_ID"] += 1
            continue
        # No repeated listing may inflate the sample, even if row values agree.
        if item_id in eligible:
            del eligible[item_id]
            duplicated.add(item_id)
            rejected["DUPLICATE_ITEM_ID"] += 2
            continue
        if (row.get("source") != "EBAY_PRODUCT_RESEARCH"
                or row.get("sale_price_basis") != "ACTUAL_PAID_PRICE"):
            rejected["UNCONFIRMED_ACTUAL_SALE_PRICE"] += 1
            continue
        if row.get("currency") != "GBP" or row.get("item_country") != "GB":
            rejected["NON_GB_OR_NON_GBP"] += 1
            continue
        sold = _sold_day(row.get("sold_at"))
        if sold is None or sold > (now + MAX_FUTURE_DRIFT).date() or (now.date() - sold).days > MAX_AGE.days:
            rejected["INVALID_OR_STALE_SOLD_DATE"] += 1
            continue
        price = _minor(row.get("price_gbp"))
        shipping_value = row.get("shipping_gbp")
        shipping = _minor(shipping_value, allow_zero=True) if shipping_value is not None else None
        if price is None or (shipping_value is not None and shipping is None):
            rejected["INVALID_PRICE"] += 1
            continue
        if (any(row.get(key) != target.get(key)
                for key in ("set_name", "card_number", "variant", "language"))
                or not _matches_comp(
                    {"title": row.get("title"), "condition_raw": row.get("condition_raw")}, target
                )):
            rejected["EXACT_PRINT_MISMATCH"] += 1
            continue
        eligible[item_id] = (sold, price)

    # Existing strict eBay flow uses the newest five exact sale observations
    # and a median of item prices (never shipping-inclusive retail prices).
    newest = sorted(eligible.values(), key=lambda item: item[0], reverse=True)[:5]
    recent_count = sum((now.date() - sale_day).days <= RECENT_AGE.days for sale_day, _ in newest)
    candidate = sorted(price for _, price in newest)[2] if len(newest) == 5 and recent_count else None
    return {
        "mode": "SIGNED_IN_RESEARCH_ASSISTED_READ_ONLY",
        "status": "REVIEW_REQUIRED" if candidate is not None else "INSUFFICIENT_EVIDENCE",
        "source": "EBAY_PRODUCT_RESEARCH_MANUALLY_REVIEWED",
        "sold_search_url": build_sold_search_url(target),
        "official_research_help_url": OFFICIAL_RESEARCH_HELP,
        "submitted_count": len(rows),
        "eligible_exact_count": len(eligible),
        "newest_five_count": len(newest),
        "recent_14d_count": recent_count,
        "excluded_reasons": dict(sorted(rejected.items())),
        "candidate_median_item_price_minor": candidate,
        "candidate_is_market_value": False,
        "actual_paid_price_and_provenance_require_independent_review": True,
        "database_writes": False,
        "shopify_writes": False,
        "price_publication_enabled": False,
    }
