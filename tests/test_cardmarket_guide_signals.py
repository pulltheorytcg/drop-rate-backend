from datetime import datetime, timezone
from decimal import Decimal

from app.cardmarket_guide_signals import offer_floor_context
from app.fx import FxQuote

NOW=datetime(2026,11,14,12,tzinfo=timezone.utc)
FX=FxQuote("EUR","GBP",Decimal("0.85"),NOW,NOW,"ECB_EURO_REFERENCE_RATES")


def test_lowest_active_offer_is_context_not_market_value():
    q=offer_floor_context({"low":"40.00","trend":"100"},FX,observed=NOW)
    assert q["price_gbp_minor"]==3400
    assert q["source_field"]=="low"
    assert q["quote_type"]=="LOWEST_ACTIVE_ASKING"
    assert q["seller_count_verified"] is False
    assert q["physical_valuation_eligible"] is False
    assert q["sold_price"] is False
    assert "market_value_minor" not in q
    assert "retail" not in q["quote_type"].casefold()


def test_foil_low_cannot_inherit_normal_offer():
    guide={"low":"1.00","low-foil":"7.00"}
    q=offer_floor_context(guide,FX,observed=NOW,foil=True)
    assert q["source_field"]=="low-foil" and q["price_gbp_minor"]==595


def test_unavailable_or_malformed_low_does_not_become_valuation():
    for row in ({"low":None},{"low":0},{"low":False},{"low":"NaN"},
                {"low":"Infinity"},{"low":-1},{}):
        assert offer_floor_context(row,FX,observed=NOW) is None
    assert offer_floor_context({"trend":"100"},FX,observed=NOW) is None
