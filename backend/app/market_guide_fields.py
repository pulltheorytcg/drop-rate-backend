"""Conservative fallbacks within Cardmarket's official daily price-guide file.

These are retailer-market statistical guides, never independent sold records.
No provider requests or financial writes happen here.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .reference_market import _minor

# Only published 30-day aggregates of the SAME identified product/finish.
# Other fields (asking-price low, available offers) are not eligible.
_ROLLING_FIELDS = {
    "trend": "avg30",
    "trend-foil": "avg30-foil",
}


def choose_bulk_price_field(price: dict, trend_field: str) -> tuple[int, str] | None:
    """Prefer positive trend; allow 30-day average only if trend is absent/zero.

    A malformed, negative, non-finite or too-large TREND value must fail
    closed, not be hidden by an alternative source column. Both columns
    are aggregated across languages and conditions; this utility never
    establishes a physical printing/finish match.
    """
    if not isinstance(price, dict) or trend_field not in _ROLLING_FIELDS:
        return None
    raw = price.get(trend_field)
    if isinstance(raw, bool):
        return None
    if raw is not None:
        try:
            amount = Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            return None
        if not amount.is_finite() or amount < 0:
            return None
        if amount > 0:
            try:
                return _minor(raw), trend_field
            except (InvalidOperation, ValueError, TypeError):
                return None
    alternate = _ROLLING_FIELDS[trend_field]
    try:
        return _minor(price.get(alternate)), alternate
    except (InvalidOperation, ValueError, TypeError):
        return None
