"""Read-only provenance and source-row coverage for Cardmarket public game exports.

These exports have no trusted match to Drop Rate's Yu-Gi-Oh!/Lorcana
printing/finish identities. Counts are *not* pricing coverage, inventory
valuations, individual sales, or permission to display provider content.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

MAX_ROWS = 200_000
MAX_GUIDE_AGE = timedelta(days=3)
MAX_CATALOG_AGE = timedelta(days=45)
MAX_SOURCE_AMOUNT = Decimal("10000000")
GAMES = {
    "YUGIOH": {"id": 3, "label": "Yu-Gi-Oh!"},
    "DISNEY_LORCANA": {"id": 19, "label": "Disney Lorcana"},
}


class SourceRejected(ValueError):
    """Source is untrustworthy or outside the bounded pilot's limits."""


def _date(value):
    if not isinstance(value, str):
        raise SourceRejected("Provider export date missing")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceRejected("Invalid provider export timestamp") from exc
    if date.utcoffset() is None:
        raise SourceRejected("Provider timestamp lacks timezone")
    return date.astimezone(timezone.utc)


def _ids(records, *, label):
    result = {}
    if not isinstance(records, list) or not 0 < len(records) <= MAX_ROWS:
        raise SourceRejected("Unbounded or empty " + label)
    for row in records:
        if not isinstance(row, dict):
            raise SourceRejected("Malformed " + label + " record")
        key = row.get("idProduct")
        if type(key) is not int or not 0 < key <= 2**31 - 1 or key in result:
            raise SourceRejected("Missing, invalid or duplicate exact product ID in " + label)
        result[key] = row
    return result


def _published_stat(row, keys):
    # Consider only source statistical trend / rolling average data. The
    # listing low, suggested retail, volume and asking fields are ineligible.
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            num = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if num.is_finite() and 0 < num <= MAX_SOURCE_AMOUNT:
            return True
    return False


def source_availability(*, game: str, catalogue: dict, guides: dict,
                        now: datetime) -> dict:
    """Strict source-level join by official numeric ID; no card identity join."""
    if game not in GAMES:
        raise SourceRejected("Unapproved Cardmarket game")
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise SourceRejected("Invalid observation time")
    now = now.astimezone(timezone.utc)
    if not isinstance(catalogue, dict) or not isinstance(guides, dict):
        raise SourceRejected("Source export must be JSON objects")
    catalogue_date = _date(catalogue.get("createdAt"))
    guide_date = _date(guides.get("createdAt"))
    if (catalogue_date > now or guide_date > now
            or now - catalogue_date > MAX_CATALOG_AGE
            or now - guide_date > MAX_GUIDE_AGE):
        raise SourceRejected("Stale or future-dated source export")
    product_rows = _ids(catalogue.get("products"), label="catalogue")
    guide_rows = _ids(guides.get("priceGuides"), label="price guide")
    matches = product_rows.keys() & guide_rows.keys()
    trend = sum(_published_stat(guide_rows[key], ("trend", "avg30")) for key in matches)
    foil = sum(_published_stat(guide_rows[key], ("trend-foil", "avg30-foil")) for key in matches)
    return {
        "status": "SOURCE_AVAILABILITY_ONLY_NO_VALUATION",
        "game": game, "game_id": GAMES[game]["id"],
        "source_currency": "EUR", "catalogue_created_at": catalogue_date.isoformat(),
        "guide_created_at": guide_date.isoformat(),
        "source_product_rows": len(product_rows), "source_guide_rows": len(guide_rows),
        "matching_product_ids": len(matches),
        "with_nonzero_statistical_normal": trend,
        "with_nonzero_statistical_foil": foil,
        "unjoined_source_products": len(product_rows) - len(matches),
        "exact_printing_matches": 0,
        "verified_uk_sold_market_values": 0,
        "database_writes": 0, "r2_writes": 0, "shopify_writes": 0,
    }
