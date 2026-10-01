from __future__ import annotations

from pathlib import Path

import pytest

from app.ebay_fulfillment import (
    build_shipping_fulfillment_payload,
    existing_shipping_fulfillment,
    shipping_fulfillment_matches,
)


ROOT = Path(__file__).parents[1]
CLIENT = ROOT / "backend" / "app" / "ebay_sell_client.py"


def test_build_shipping_fulfillment_payload_requires_tracking_and_carrier() -> None:
    payload = build_shipping_fulfillment_payload(
        [("line-1", 1)],
        shipping_carrier_code="RoyalMail",
        tracking_number="AA123456789GB",
    )
    assert payload == {
        "lineItems": [{"lineItemId": "line-1", "quantity": 1}],
        "shippingCarrierCode": "RoyalMail",
        "trackingNumber": "AA123456789GB",
    }

    with pytest.raises(ValueError, match="shipping_carrier_code"):
        build_shipping_fulfillment_payload(
            [("line-1", 1)],
            shipping_carrier_code="",
            tracking_number="AA123456789GB",
        )
    with pytest.raises(ValueError, match="tracking_number"):
        build_shipping_fulfillment_payload(
            [("line-1", 1)],
            shipping_carrier_code="RoyalMail",
            tracking_number="",
        )


def test_tracking_number_must_be_ascii_alphanumeric() -> None:
    for invalid in ("TRACK-1", "TRACK 1", "TRACK/1", "TRÄCK1"):
        with pytest.raises(ValueError, match="ASCII alphanumeric"):
            build_shipping_fulfillment_payload(
                [("line-1", 1)],
                shipping_carrier_code="RoyalMail",
                tracking_number=invalid,
            )


def test_payload_rejects_duplicate_or_invalid_line_items() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        build_shipping_fulfillment_payload(
            [("line-1", 1), ("line-1", 1)],
            shipping_carrier_code="RoyalMail",
            tracking_number="TRACK",
        )
    with pytest.raises(ValueError, match="positive"):
        build_shipping_fulfillment_payload(
            [("line-1", 0)],
            shipping_carrier_code="RoyalMail",
            tracking_number="TRACK",
        )


def test_existing_fulfillment_match_is_exact_and_retry_safe() -> None:
    payload = build_shipping_fulfillment_payload(
        [("line-2", 1), ("line-1", 1)],
        shipping_carrier_code="RoyalMail",
        tracking_number="TRACK1",
    )
    existing = {
        "fulfillmentId": "fulfillment-1",
        "lineItems": [
            {"lineItemId": "line-1", "quantity": 1},
            {"lineItemId": "line-2", "quantity": 1},
        ],
        "shippingCarrierCode": "RoyalMail",
        "trackingNumber": "TRACK1",
    }

    assert shipping_fulfillment_matches(existing, payload=payload) is True
    assert existing_shipping_fulfillment([existing], payload=payload) is existing

    wrong_tracking = {**existing, "trackingNumber": "TRACK2"}
    assert shipping_fulfillment_matches(wrong_tracking, payload=payload) is False


def test_multiple_identical_remote_fulfillments_fail_closed() -> None:
    payload = build_shipping_fulfillment_payload(
        [("line-1", 1)],
        shipping_carrier_code="RoyalMail",
        tracking_number="TRACK",
    )
    fulfillment = {
        "lineItems": [{"lineItemId": "line-1", "quantity": 1}],
        "shippingCarrierCode": "RoyalMail",
        "trackingNumber": "TRACK",
    }
    with pytest.raises(ValueError, match="multiple"):
        existing_shipping_fulfillment(
            [fulfillment, dict(fulfillment)],
            payload=payload,
        )


def test_client_exposes_read_only_shipping_fulfillment_reads_only() -> None:
    source = CLIENT.read_text()
    assert "async def get_shipping_fulfillments(" in source
    assert "async def get_shipping_fulfillment(" in source
    assert (
        'f"/sell/fulfillment/v1/order/{quote(order_id, safe=\'\')}/'
        'shipping_fulfillment"'
    ) in source
    assert "async def create_shipping_fulfillment(" not in source
