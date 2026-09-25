from __future__ import annotations

MIN_STORE_PRICE_MINOR = 100


def store_price_floor(value_minor: int) -> int:
    """Apply Drop Rate's hard minimum sellable Store Price.

    Market Value is evidence-derived and may legitimately be below the floor.
    Store Price is the commercial selling price and may not be below £1.00.
    """
    if value_minor < 0:
        raise ValueError("Store Price basis cannot be negative")
    return max(MIN_STORE_PRICE_MINOR, int(value_minor))
