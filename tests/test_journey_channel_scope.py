"""One source of truth for the existing eBay publisher scope."""
import pytest
from app.seller_inventory_policy import ebay_listing_scope_blocker

@pytest.mark.parametrize("owner,kind,expected",[
    ("CONSIGNOR","CARD","Consignor eBay publishing is not enabled yet"),
    ("CONSIGNOR","SEALED","Consignor eBay publishing is not enabled yet"),
    ("FOUNDER","SEALED","eBay v1 only supports individual physical cards"),
    ("FOUNDER","COLLECTION","eBay v1 only supports individual physical cards"),
    ("FOUNDER","CARD",None),
])
def test_unchanged_channel_scope(owner,kind,expected):
    assert ebay_listing_scope_blocker(owner,kind)==expected
