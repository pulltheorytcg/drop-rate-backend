"""Cardmarket daily public-guide asking context, separate from retail and sold prices.

An official low is a single lowest offer, across unspecified conditions and
languages; do not infer grade, Near Mint, sale completion or a fair UK price.
The deterministic pricing engine must not use this floor as Market Value.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .reference_market import _minor


def offer_floor_context(price: dict, conversion, *, observed: datetime,
                        foil: bool = False) -> dict | None:
    field = "low-foil" if foil else "low"
    if not isinstance(price, dict) or not isinstance(observed, datetime) or observed.utcoffset() is None:
        return None
    try:
        amount = _minor(price.get(field))
        gbp = int((Decimal(amount) * conversion.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        return None
    if amount <= 0 or gbp <= 0:
        return None
    return {
        "source_field": field, "original_currency": "EUR",
        "original_minor": amount, "price_gbp_minor": gbp,
        "observed_at": observed.isoformat(),
        "quote_type": "LOWEST_ACTIVE_ASKING", "market_scope": "CARDMARKET_EU",
        "condition_basis": "MIXED_UNSPECIFIED",
        "language_basis": "MIXED_UNSPECIFIED",
        "grade_basis": "NOT_GRADED",
        "listing_count_verified": False,
        "seller_count_verified": False,
        "physical_valuation_eligible": False,
        "sold_price": False,
        "fx_source": conversion.source,
        "fx_rate_to_gbp": str(conversion.rate),
        "fx_effective_at": conversion.effective_at.isoformat(),
        "valuation_role": "ASKING_CONTEXT_ONLY_NOT_RETAIL_RRP",
    }
