"""Proven-complete, bounded R2 shortlist for dynamic catalogue value sorts.

R2 holds only shared public reference evidence; every item on the shortlist is
still priced, authorized, and sorted by the original PostgreSQL query.

We can exclude an *unlinked* reference only when its exact current public
market price is known and falls below/above the requested page's cutoff.
Every canonical-linked, alias-priced, and tied-boundary entry stays in SQL.
Unknown evidence, stale publications or unsupported shapes fail closed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

MAX_SHORTLIST = 1800
EDGE_WINDOW = timedelta(minutes=3)


class PriceExpiryBoundary(ValueError):
    """An expiry-adjacent candidate must be retained for PostgreSQL."""


def _quote(record):
    if record is None:
        return {}
    quotes = record.get("quotes") or []
    if not isinstance(quotes, list):
        raise ValueError("Invalid market quote structure")
    if not quotes:
        return {}
    if not isinstance(quotes[0], dict):
        raise ValueError("Invalid market quote evidence")
    return quotes[0]


def _recent(record, days, now):
    if record is None:
        return False
    stamp = record.get("pricing_updated_at")
    if stamp is None:
        return False
    if not isinstance(stamp, str):
        raise ValueError("Invalid market observation timestamp")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Unparseable market timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("Naive market timestamp")
    boundary = now - timedelta(days=days)
    # The database compares to its own clock. Never short-list around the
    # cutoff if the two clocks could disagree.
    if abs(parsed - boundary) < EDGE_WINDOW:
        raise PriceExpiryBoundary("Price expiry boundary needs original SQL")
    return parsed >= boundary


def reference_value(row, market, now):
    """Match SOURCE_CTE's shared price order and exact-identity join guards.

    This is a *selection proof*, not the value returned to the customer.
    PostgreSQL continues to calculate the final displayed price.
    """
    source_kind = row["source_kind"]
    if source_kind == "CATALOGUE":
        return None
    key = tuple(row[field] for field in ("provider", "system_code", "language", "provider_id"))
    data = market.rows
    if source_kind == "SEALED_REFERENCE":
        sealed = data["reference_sealed_market_prices"].get(key)
        return sealed.get("market_value_minor") if _recent(sealed, 7, now) else None
    if source_kind != "REFERENCE":
        raise ValueError("Unknown shared card type")
    identity = {name: row.get(name) for name in
                ("name", "set_id", "card_number", "set_name")}
    m = data["reference_market_prices"].get(key)
    b = data["reference_catalogue_prices"].get(key)
    mq = _quote(m)
    # An exact Masters rarity and a Cardmarket bulk printing identity are
    # both mandatory. No value may transfer between printings or finishes.
    if (mq.get("match_basis") == "CARDTRADER_MASTERS_NUMBER_RARITY_SINGLETON_CARDMARKET_ID"
            and row.get("rarity") != mq.get("reference_rarity")):
        m = None
    if mq.get("source") == "CARDMARKET_BULK_SINGLES" and mq.get("reference_identity") != identity:
        m = None
    bq = _quote(b)
    if b is not None:
        source = bq.get("source")
        model_ok = (source is not None and source != "DROP_RATE_COMPUTED_MARKET_V1")
        recent_model = _recent(b, 2, now) if not model_ok else False
        if bq.get("reference_identity") != identity or not (model_ok or recent_model):
            b = None
    market_price = m.get("market_value_minor") if _recent(m, 7, now) else None
    catalogue_price = b.get("market_value_minor") if _recent(b, 7, now) else None
    return market_price if market_price is not None else catalogue_price


def complete_shortlist(rows, market, *, wanted, descending=True, shared_keys=(),
                       now=None, max_rows=MAX_SHORTLIST):
    """Reduce the matching static population without changing the top page.

    Excluded references have no canonical ID or dynamic shared alias value;
    their *exact* R2 market amount must rank strictly beyond the boundary.
    Ties are kept whole. All owner-specific and canonical values are left to
    the original RLS SQL, which sees these candidates in full.
    """
    if (not isinstance(wanted, int) or not 1 <= wanted <= 512
            or max_rows > 2000 or not isinstance(market.rows, dict)):
        raise ValueError("Unbounded or incomplete value ranking")
    now = now or datetime.now(timezone.utc)
    aliases = set(shared_keys)
    fixed, ordinary = [], []
    for row in rows:
        if row.get("catalogue_id") is not None or row["key"] in aliases or row["source_kind"] == "CATALOGUE":
            fixed.append(row)
            continue
        try:
            score = reference_value(row, market, now)
        except PriceExpiryBoundary:
            # Either side of the 7-day / 2-day cutoff could be correct as
            # clocks advance. Retain this identity, then let live SQL decide.
            fixed.append(row)
            continue
        if score is not None:
            if type(score) is not int:
                raise ValueError("Non-integer market price")
            ordinary.append((score, row))
    if len(ordinary) < wanted:
        # Could require nulls in the requested page. Don't guess their rank.
        raise ValueError("Not enough fully priced candidates")
    ordered = sorted((score for score, _ in ordinary), reverse=descending)
    cutoff = ordered[wanted - 1]
    chosen = fixed + [row for score, row in ordinary
                      if score >= cutoff] if descending else (
        fixed + [row for score, row in ordinary if score <= cutoff]
    )
    if len(chosen) > max_rows:
        raise ValueError("Candidate shortlist exceeds the safe transport bound")
    return chosen
