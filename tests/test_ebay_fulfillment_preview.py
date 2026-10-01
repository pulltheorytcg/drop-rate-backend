from __future__ import annotations

from app.ebay_fulfillment import (
    build_shipping_fulfillment_payload,
    evaluate_shipping_fulfillment_preview,
)


OWNER = "00000000-0000-0000-0000-000000000001"
ORDER = "ebay-order-1"


def local_row(line_item_id: str, inventory: str) -> dict:
    return {
        "order_id": "00000000-0000-0000-0000-000000000010",
        "order_item_id": "00000000-0000-0000-0000-000000000020",
        "inventory_id": inventory,
        "owner_id": OWNER,
        "ebay_order_id": ORDER,
        "ebay_line_item_id": line_item_id,
        "order_source": "EBAY",
        "source_reference": ORDER,
        "order_status": "PAID",
        "order_item_inventory_id": inventory,
        "order_item_owner_id": OWNER,
        "inventory_owner_id": OWNER,
        "inventory_status": "SOLD",
    }


def remote_order(*line_ids: str, status: str = "NOT_STARTED") -> dict:
    return {
        "orderId": ORDER,
        "orderFulfillmentStatus": status,
        "lineItems": [
            {"lineItemId": line_id, "quantity": 1}
            for line_id in line_ids
        ],
    }


def test_exact_local_remote_mapping_is_ready_for_create() -> None:
    package = build_shipping_fulfillment_payload(
        [("line-1", 1)],
        shipping_carrier_code="RoyalMail",
        tracking_number="AA123456789GB",
    )
    result = evaluate_shipping_fulfillment_preview(
        ebay_order_id=ORDER,
        owner_id=OWNER,
        payload=package,
        local_rows=[local_row("line-1", "00000000-0000-0000-0000-000000000101")],
        remote_order=remote_order("line-1"),
        remote_fulfillments=[],
    )
    assert result["ready_for_create"] is True
    assert result["idempotent_existing"] is False
    assert result["blockers"] == ()


def test_exact_existing_package_is_idempotent_not_create_ready() -> None:
    package = build_shipping_fulfillment_payload(
        [("line-1", 1)],
        shipping_carrier_code="RoyalMail",
        tracking_number="AA123456789GB",
    )
    result = evaluate_shipping_fulfillment_preview(
        ebay_order_id=ORDER,
        owner_id=OWNER,
        payload=package,
        local_rows=[local_row("line-1", "00000000-0000-0000-0000-000000000101")],
        remote_order=remote_order("line-1", status="FULFILLED"),
        remote_fulfillments=[{
            "fulfillmentId": "ful-1",
            "lineItems": [{"lineItemId": "line-1", "quantity": 1}],
            "shippingCarrierCode": "RoyalMail",
            "trackingNumber": "AA123456789GB",
        }],
    )
    assert result["ready_for_create"] is False
    assert result["idempotent_existing"] is True
    assert result["existing_fulfillment_id"] == "ful-1"
    assert result["blockers"] == ()


def test_line_already_in_different_remote_package_fails_closed() -> None:
    package = build_shipping_fulfillment_payload(
        [("line-1", 1)],
        shipping_carrier_code="RoyalMail",
        tracking_number="AA123456789GB",
    )
    result = evaluate_shipping_fulfillment_preview(
        ebay_order_id=ORDER,
        owner_id=OWNER,
        payload=package,
        local_rows=[local_row("line-1", "00000000-0000-0000-0000-000000000101")],
        remote_order=remote_order("line-1", status="IN_PROGRESS"),
        remote_fulfillments=[{
            "fulfillmentId": "ful-other",
            "lineItems": [{"lineItemId": "line-1", "quantity": 1}],
            "shippingCarrierCode": "RoyalMail",
            "trackingNumber": "DIFFERENT123",
        }],
    )
    assert result["ready_for_create"] is False
    assert "LINE_ALREADY_ASSIGNED_TO_OTHER_FULFILLMENT" in result["blockers"]


def test_remote_extra_line_or_owner_mismatch_blocks_preview() -> None:
    row = local_row("line-1", "00000000-0000-0000-0000-000000000101")
    row["inventory_owner_id"] = "00000000-0000-0000-0000-000000000999"
    package = build_shipping_fulfillment_payload(
        [("line-1", 1)],
        shipping_carrier_code="RoyalMail",
        tracking_number="AA123456789GB",
    )
    result = evaluate_shipping_fulfillment_preview(
        ebay_order_id=ORDER,
        owner_id=OWNER,
        payload=package,
        local_rows=[row],
        remote_order=remote_order("line-1", "unexpected-line"),
        remote_fulfillments=[],
    )
    assert result["ready_for_create"] is False
    assert "INVENTORY_OWNER_MISMATCH" in result["blockers"]
    assert "REMOTE_LOCAL_ORDER_LINES_MISMATCH" in result["blockers"]
