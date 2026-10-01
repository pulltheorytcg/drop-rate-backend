from __future__ import annotations

from pathlib import Path

from app.ebay_reconciliation import reconcile_ebay_link


ROOT = Path(__file__).parents[1]
EBAY = ROOT / "backend" / "app" / "ebay_sales.py"


def live_local(**overrides):
    row = {
        "state": "LIVE",
        "inventory_status": "APPROVED",
        "sale_intent": "FOR_SALE",
        "sku": "INV-PKM-1",
        "offer_id": "offer-1",
        "listing_id": "listing-1",
        "marketplace_id": "EBAY_GB",
        "listed_price_minor": 1234,
    }
    row.update(overrides)
    return row


def published_offer(**overrides):
    row = {
        "status": "PUBLISHED",
        "offerId": "offer-1",
        "sku": "INV-PKM-1",
        "marketplaceId": "EBAY_GB",
        "listing": {"listingId": "listing-1"},
        "pricingSummary": {"price": {"currency": "GBP", "value": "12.34"}},
    }
    row.update(overrides)
    return row


def inventory_item(quantity=1):
    return {
        "availability": {
            "shipToLocationAvailability": {"quantity": quantity}
        }
    }


def test_live_link_is_healthy_only_when_remote_readback_matches() -> None:
    result = reconcile_ebay_link(
        live_local(),
        offer=published_offer(),
        inventory_item=inventory_item(1),
    )
    assert result["healthy"] is True
    assert result["discrepancies"] == []
    assert result["remote"]["quantity"] == 1
    assert result["remote"]["price_minor"] == 1234


def test_live_link_flags_listing_price_and_quantity_drift() -> None:
    result = reconcile_ebay_link(
        live_local(),
        offer=published_offer(
            listing={"listingId": "listing-other"},
            pricingSummary={"price": {"currency": "GBP", "value": "11.00"}},
        ),
        inventory_item=inventory_item(0),
    )
    assert result["healthy"] is False
    assert "REMOTE_LISTING_ID_MISMATCH" in result["discrepancies"]
    assert "REMOTE_PRICE_MISMATCH" in result["discrepancies"]
    assert "LIVE_LINK_REMOTE_QUANTITY_NOT_ONE" in result["discrepancies"]


def test_sold_inventory_still_published_is_oversell_risk() -> None:
    result = reconcile_ebay_link(
        live_local(state="SOLD", inventory_status="SOLD"),
        offer=published_offer(),
        inventory_item=inventory_item(1),
    )
    assert result["healthy"] is False
    assert "NON_LIVE_LINK_REMOTE_STILL_PUBLISHED" in result["discrepancies"]
    assert "CROSS_CHANNEL_OVERSELL_RISK" in result["discrepancies"]


def test_live_link_with_unsellable_local_inventory_is_flagged() -> None:
    result = reconcile_ebay_link(
        live_local(inventory_status="INSPECTION"),
        offer=published_offer(),
        inventory_item=inventory_item(1),
    )
    assert "LOCAL_LIVE_LINK_INVENTORY_NOT_SELLABLE" in result["discrepancies"]


def test_missing_offer_fails_closed() -> None:
    result = reconcile_ebay_link(
        live_local(),
        offer=None,
        inventory_item=inventory_item(1),
    )
    assert result["healthy"] is False
    assert "REMOTE_OFFER_MISSING" in result["discrepancies"]
    assert "LIVE_LINK_REMOTE_NOT_PUBLISHED" in result["discrepancies"]


def test_reconciliation_route_is_admin_read_only_and_bounded() -> None:
    source = EBAY.read_text()
    marker = '@router.get("/reconciliation", dependencies=[Depends(require_platform_admin_request)])'
    assert marker in source
    start = source.index(marker)
    end = source.index('@router.post("/listings/{inventory_id}"', start)
    block = source[start:end]

    assert "limit: int = Query(default=50, ge=1, le=50)" in block
    assert "asyncio.Semaphore(4)" in block
    assert "client.get_offer(" in block
    assert "client.get_inventory_item(" in block
    assert "connection.execute(" not in block
    assert "connection.fetch(" in block
    assert ".publish_offer(" not in block
    assert ".withdraw_offer(" not in block
    assert ".update_offer(" not in block
    assert ".put_inventory_item(" not in block
