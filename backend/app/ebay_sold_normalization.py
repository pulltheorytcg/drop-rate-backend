"""Normalize the connected Trawl feed before any collectible-specific matching.

Only this HTTP boundary interprets Trawl's nominal-Z UK wall times. Stored
observations already contain UTC instants and must never pass through it again.
See https://trawl.dev/docs/ebay/sold and https://trawl.dev/docs/ebay/item.
"""
from __future__ import annotations

from collections import Counter
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

REVISION = "trawl-uk-evidence-2026-11-04"
LONDON = ZoneInfo("Europe/London")
UK_NAMES = {"united kingdom", "great britain", "gb", "uk"}


def has_normalized_uk_evidence(metadata):
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return False
    evidence = metadata.get("provider_evidence") if isinstance(metadata, dict) else None
    return (isinstance(evidence, dict) and evidence.get("normalization_revision") == REVISION
            and evidence.get("item_location_country") == "GB")


def prefer_normalized_uk_rows(rows):
    """After rechecking a physical basis, do not blend its old unverified rows.

    Legacy history remains available until that basis has new normalized
    evidence. Insufficient new evidence must not be padded with legacy rows.
    """
    verified = [row for row in rows if has_normalized_uk_evidence(row.get("metadata"))]
    return verified if verified else rows


def _amount(value, *, positive=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    if not result.is_finite() or result < 0 or result >= Decimal("1e10"):
        return None
    return result if not positive or result > 0 else None


def _local_sale(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # The provider documents only a nominal Z, never an arbitrary UTC offset.
    if parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() != 0:
        return None
    wall = parsed.replace(tzinfo=None)
    first, second = wall.replace(tzinfo=LONDON, fold=0), wall.replace(tzinfo=LONDON, fold=1)
    # Do not guess during the ambiguous/nonexistent daylight-saving hour.
    if first.utcoffset() != second.utcoffset():
        return None
    return first.astimezone(timezone.utc)


def _same_detail_sale(row, details, sold):
    if (details.get("site") != "EBAY_GB" or str(details.get("item_id")) != str(row.get("item_id"))
            or details.get("listing_state") != "sold" or details.get("currency") not in ("GBP", "�")):
        return False
    try:
        instant = datetime.fromisoformat(str(details.get("sold_at")).replace("Z", "+00:00"))
    except ValueError:
        return False
    # Details are a real UTC instant, unlike search timestamps. Day-only sales
    # cannot establish that the details price belongs to this particular sale.
    wall = sold.astimezone(LONDON)
    return (instant.tzinfo is not None and instant == sold
            and (wall.hour, wall.minute, wall.second, wall.microsecond) != (0, 0, 0, 0))


def normalize_uk_sold_payload(payload):
    """Return an immutable-input, minimal payload of defensible UK sales.

    Do not request paid details or infer UK item location from the marketplace.
    Rejections are counted without logging titles, seller data or credentials.
    """
    if (payload.get("site") != "EBAY_GB" or payload.get("currency") != "GBP"
            or not isinstance(payload.get("results"), list)):
        raise ValueError("UK GBP sold response required")
    counts = Counter()
    accepted = {}
    conflicts = set()
    for row in payload["results"]:
        if not isinstance(row, dict):
            counts["INVALID_ROW"] += 1
            continue
        item_id = str(row.get("item_id") or "").strip()
        if not item_id.isdigit():
            counts["INVALID_ITEM_ID"] += 1
            continue
        if item_id in conflicts:
            counts["CONFLICTING_ITEM_ID"] += 1
            continue
        sold = _local_sale(row.get("date_sold"))
        country = str(row.get("location_country") or row.get("location") or "").strip()
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        detail_country = str(details.get("location_country") or "").strip()
        price = _amount(row.get("sale_price"), positive=True)
        shipping = _amount(row.get("shipping_price"))
        reason = None
        if sold is None:
            reason = "INVALID_OR_AMBIGUOUS_SALE_TIME"
        elif not country:
            reason = "UNKNOWN_ITEM_LOCATION"
        elif country.casefold() not in UK_NAMES or (detail_country and detail_country.casefold() not in UK_NAMES):
            reason = "NON_UK_ITEM_LOCATION"
        elif row.get("currency") not in (None, "�", "GBP"):
            reason = "NON_GBP_PRICE"
        elif price is None or (row.get("shipping_price") is not None and shipping is None):
            reason = "INVALID_AMOUNT"
        price_basis = "REPORTED_SOLD_PRICE"
        buying_format = str(row.get("buying_format") or "").strip().casefold()
        if reason is None:
            same_sale = _same_detail_sale(row, details, sold)
            offer = ("offer" in buying_format or row.get("best_offer_available") is True
                     or details.get("best_offer_available") is True
                     or details.get("best_offer_accepted") is True)
            if offer:
                if (same_sale and details.get("best_offer_accepted") is False and "offer" not in buying_format
                        and _amount(details.get("sale_price"), positive=True) == price):
                    price_basis = "DETAILS_CONFIRMED_NON_OFFER"
                elif (same_sale and details.get("best_offer_accepted") is True
                        and _amount(details.get("list_price"), positive=True) == price
                        and (offer_price := _amount(details.get("sale_price"), positive=True)) is not None
                        and offer_price < price):
                    price, price_basis = offer_price, "DETAILS_CONFIRMED_ACCEPTED_OFFER"
                else:
                    reason = "UNVERIFIED_BEST_OFFER"
            elif buying_format == "auction":
                price_basis = "AUCTION_SOLD_PRICE"
            elif buying_format != "buy it now" or row.get("best_offer_available") is not False:
                reason = "UNVERIFIED_SALE_PRICE"
        if reason:
            counts[reason] += 1
            # A contradictory duplicate cannot be made safe by row ordering.
            conflicts.add(item_id)
            if item_id in accepted:
                del accepted[item_id]
                counts["CONFLICTING_ITEM_ID"] += 1
            continue
        evidence = {
            "normalization_revision": REVISION,
            "item_location_country": "GB",
            "provider_location_country": country,
            "provider_date_sold": row["date_sold"],
            "provider_time_zone": "Europe/London",
            "sale_price_basis": price_basis,
            "reported_sale_price": str(_amount(row["sale_price"])),
            "buying_format": row.get("buying_format"),
            "best_offer_available": row.get("best_offer_available"),
            "shipping_status": "UNKNOWN" if shipping is None else "FREE" if shipping == 0 else "KNOWN",
        }
        clean = {key: row.get(key) for key in ("title", "condition", "condition_raw", "item_link")}
        clean.update(item_id=item_id, date_sold=sold.isoformat(), sale_price=str(price),
                     shipping_price=str(shipping) if shipping is not None else None,
                     currency="GBP", _pricing_evidence=evidence)
        if item_id in accepted:
            if clean == accepted[item_id]:
                counts["DUPLICATE_ITEM_ID"] += 1
            else:
                del accepted[item_id]
                conflicts.add(item_id)
                counts["CONFLICTING_ITEM_ID"] += 2
            continue
        accepted[item_id] = clean
    results = list(accepted.values())
    return {"site": "EBAY_GB", "currency": "GBP", "results": results,
            "_normalization": {"revision": REVISION, "received": len(payload["results"]),
                               "accepted": len(results), "excluded": len(payload["results"]) - len(results),
                               "reasons": dict(sorted(counts.items()))}}
