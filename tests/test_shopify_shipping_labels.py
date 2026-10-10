"""Official Shopify Shipping 2026-07 adapter: exact owner/FO and no-charge gates."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app import shopify_shipping_labels as label
from app.shopify_client import ShopifyApiError


NUMERIC_ORDER = "8506160775515"
LINE = "gid://shopify/LineItem/20106310025563"
FO = "gid://shopify/FulfillmentOrder/9346133393755"
RESULT_GID = "gid://shopify/ShippingLabelPurchaseResult/9012"


def local_copy(line="20106310025563", **updates):
    item = {
        "shopify_order_id": NUMERIC_ORDER,
        "shopify_line_item_id": line,
        "physical_status": "SOLD",
    }
    item.update(updates)
    return item


def fulfillment_line(line_gid=LINE, remaining=1, requires_shipping=True):
    return {
        "id": "gid://shopify/FulfillmentOrderLineItem/123",
        "lineItem": {"id": line_gid},
        "remainingQuantity": remaining,
        "totalQuantity": remaining,
        "requiresShipping": requires_shipping,
    }


def order_example(**updates):
    order = {
        "id": label.canonical_shopify_order_gid(NUMERIC_ORDER),
        "name": "#1009",
        "cancelledAt": None,
        "fullyPaid": True,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "UNFULFILLED",
        "lineItems": {"nodes": [{"id": LINE}], "pageInfo": {"hasNextPage": False}},
        "fulfillmentOrders": {
            "nodes": [{
                "id": FO, "orderId": label.canonical_shopify_order_gid(NUMERIC_ORDER),
                "status": "OPEN", "requestStatus": "UNSUBMITTED",
                "assignedLocation": {
                    "location": {"id": "gid://shopify/Location/123"}, "countryCode": "GB",
                },
                "destination": {"countryCode": "GB"},
                "lineItems": {"nodes": [fulfillment_line()], "pageInfo": {"hasNextPage": False}},
            }],
            "pageInfo": {"hasNextPage": False},
        },
    }
    order.update(updates)
    return order


def review(order=None, local=None, target=LINE):
    return label.evaluate_remote_shipping(
        order=order if order is not None else order_example(),
        local_allocations=local if local is not None else [local_copy()],
        target_line_gid=target,
    )


def test_exact_shopify_order_line_ids_are_not_user_specified_gids():
    assert label.canonical_shopify_order_gid(NUMERIC_ORDER) == f"gid://shopify/Order/{NUMERIC_ORDER}"
    assert label.canonical_shopify_line_gid("20106310025563") == LINE
    for bad in ("", "gid://shopify/Order/42", "42 extra", "0' OR 1=1", "123;" ):
        with pytest.raises(ValueError):
            label.canonical_shopify_order_gid(bad)


def test_clean_live_shopify_order_still_cannot_buy_a_label():
    result = review()
    assert result["shopify_connected"] is True
    assert result["state"] == "AWAITING_DISPATCH_SETUP"
    assert result["fulfillment_order_id"] == FO
    assert result["destination_country"] == "GB"
    assert result["blockers"] == [
        "PHYSICAL_SHIPPER_UNVERIFIED",
        "SHOPIFY_LABEL_QUOTE_AND_PURCHASE_JOURNAL_PENDING",
    ]
    assert result["can_buy_label"] is False
    assert result["can_confirm_dispatched"] is False


@pytest.mark.parametrize("order_patch, expected", [
    ({"cancelledAt": "2026-10-11T00:00:00Z"}, "SHOPIFY_ORDER_CANCELLED"),
    ({"fullyPaid": False}, "SHOPIFY_ORDER_PAYMENT_NOT_VERIFIED"),
    ({"displayFinancialStatus": "PARTIALLY_REFUNDED"}, "SHOPIFY_ORDER_PAYMENT_NOT_VERIFIED"),
    ({"displayFulfillmentStatus": "FULFILLED"}, "SHOPIFY_ORDER_ALREADY_FULFILLED"),
])
def test_cancelled_refunded_paid_and_fulfilled_are_locked(order_patch, expected):
    state = review(order=order_example(**order_patch))
    assert expected in state["blockers"]
    assert state["state"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("bad_local", [
    [{"shopify_order_id": "other", "shopify_line_item_id": "20106310025563", "physical_status": "SOLD"}],
    [local_copy(physical_status="APPROVED")],
    [local_copy(shopify_line_item_id=None)],
    [],
])
def test_bad_local_identity_or_status_blocks_all_remote_labels(bad_local):
    state = review(local=bad_local)
    assert "LOCAL_OWNER_ALLOCATION_MISMATCH" in state["blockers"]
    assert not state["can_buy_label"]


def test_mixed_owner_same_shopify_variant_quantity_two_blocks_single_label():
    parent = order_example()
    parent["fulfillmentOrders"]["nodes"][0]["lineItems"]["nodes"] = [
        fulfillment_line(remaining=2)
    ]
    state = review(order=parent,local=[local_copy()])
    assert "FULFILMENT_MIXED_OWNER_OR_QUANTITY_SPLIT_REQUIRED" in state["blockers"]


def test_other_owner_line_in_same_fulfillment_order_blocks_purchase():
    parent = order_example()
    parent["fulfillmentOrders"]["nodes"][0]["lineItems"]["nodes"].append(
        fulfillment_line("gid://shopify/LineItem/99999")
    )
    state = review(order=parent)
    assert "FULFILMENT_MIXED_OWNER_OR_QUANTITY_SPLIT_REQUIRED" in state["blockers"]


def test_broken_shopify_pagination_is_fail_closed():
    parent = order_example()
    parent["fulfillmentOrders"]["pageInfo"]["hasNextPage"] = True
    state = review(order=parent)
    assert "SHOPIFY_FULFILMENT_ORDERS_TRUNCATED" in state["blockers"]
    parent = order_example()
    parent["lineItems"]["pageInfo"]["hasNextPage"] = True
    assert "SHOPIFY_LINE_ITEMS_TRUNCATED" in review(order=parent)["blockers"]


@pytest.mark.parametrize("field,value,code", [
    ("status", "CLOSED", "FULFILMENT_ORDER_NOT_OPEN"),
    ("requestStatus", "SUBMITTED", "FULFILMENT_ORDER_NOT_OPEN"),
    ("destination", None, "FULFILMENT_SHIPPING_ORIGIN_OR_DESTINATION_MISSING"),
])
def test_invalid_shopify_fulfillment_is_not_ready(field, value, code):
    parent = order_example()
    parent["fulfillmentOrders"]["nodes"][0][field] = value
    assert code in review(order=parent)["blockers"]


def test_non_shipping_or_zero_quantity_and_overseas_customs():
    parent = order_example()
    parent["fulfillmentOrders"]["nodes"][0]["lineItems"]["nodes"][0]["remainingQuantity"] = 0
    assert "FULFILMENT_ALREADY_DISPATCHED_OR_RESERVED" in review(order=parent)["blockers"]
    parent = order_example()
    parent["fulfillmentOrders"]["nodes"][0]["lineItems"]["nodes"][0]["requiresShipping"] = False
    assert "FULFILMENT_NON_SHIPPING_OR_INVALID_QUANTITY" in review(order=parent)["blockers"]
    parent = order_example()
    parent["fulfillmentOrders"]["nodes"][0]["destination"]["countryCode"] = "US"
    assert "INTERNATIONAL_CUSTOMS_AND_INSURANCE_REVIEW" in review(order=parent)["blockers"]


def confirmed_shipment(**changes):
    values = {
        "fulfillment_order_gid": FO,
        "shipping_datetime": datetime.now(timezone.utc) + timedelta(hours=24),
        "total_packed_weight_grams": 90.0,
        "length_cm": 15.0,
        "width_cm": 11.0,
        "height_cm": 2.0,
        "package_empty_weight_grams": 27.0,
        "origin_address": {
            "address1": "Some approved London ship-from",
            "city": "London", "zip": "E1 1AA", "countryCode": "GB",
            "firstName": "Test", "lastName": "Sender",
        },
        "carrier_code": "royal_mail",
        "service_code": "tracked_48",
        "confirmed_charge_minor": 295,
        "purchase_journal_reserved": True,
        "physical_custody_verified": True,
    }
    values.update(changes)
    return label.ConfirmedShipment(**values)


def test_official_2026_07_label_payload_measured_and_custom_origin():
    result = label.build_confirmed_label_input(confirmed_shipment())
    assert result["fulfillmentOrderId"] == FO
    assert result["totalWeight"] == {"value": 90.0, "unit": "GRAMS"}
    assert result["packageInfo"]["customPackage"]["weight"]["value"] == 27
    assert result["packageInfo"]["customPackage"]["dimensions"]["unit"] == "CENTIMETERS"
    assert result["preferredRateSelection"] == {
        "carrierCode": "royal_mail", "serviceCode": "tracked_48",
    }
    assert result["originAddress"]["countryCode"] == "GB"
    assert result["notifyCustomer"] is False


@pytest.mark.parametrize("change", [
    {"purchase_journal_reserved": False},
    {"physical_custody_verified": False},
    {"confirmed_charge_minor": 0},
    {"total_packed_weight_grams": 25.0},
    {"length_cm": 0.0},
    {"package_type": "TINY_CUP"},
    {"height_cm": -1.0},
    {"shipping_datetime": datetime.now(timezone.utc) - timedelta(minutes=1)},
    {"shipping_datetime": datetime.now(timezone.utc) + timedelta(days=35)},
    {"shipping_datetime": datetime.now(timezone.utc).replace(tzinfo=None)},
    {"carrier_code": "invalid\nGraphQL"},
    {"origin_address": {"city": "London"}},
    {"fulfillment_order_gid": "gid://shopify/FulfillmentOrder/123;bad"},
])
def test_label_purchase_input_refuses_unverified_or_ambiguous_charges(change):
    with pytest.raises(ValueError):
        label.build_confirmed_label_input(confirmed_shipment(**change))


def test_older_shopify_versions_refused():
    for version in ("2026-01", "2026-04", "invalid", ""):
        with pytest.raises(ValueError):
            label.ensure_label_api_version(version)
    label.ensure_label_api_version("2026-07")


def test_light_card_envelope_uses_measured_envelope_profile_not_box_guess():
    entry = confirmed_shipment(
        package_type="ENVELOPE",
        total_packed_weight_grams=57.5,
        package_empty_weight_grams=15.0,
    )
    result = label.build_confirmed_label_input(entry)
    assert result["packageInfo"]["customPackage"]["type"] == "ENVELOPE"
    assert result["totalWeight"]["value"] == 57.5


def test_shopify_purchase_uses_server_only_graphql_and_no_browser_action():
    class FakeShopify:
        api_version = "2026-07"
        def __init__(self):
            self.calls = []
        async def graphql(self, *, query, variables=None):
            self.calls.append((query, variables))
            return {"shippingLabelPurchase": {
                "shippingLabelPurchaseResult": {
                    "id": RESULT_GID, "status": "PENDING_PURCHASE",
                },
                "userErrors": [],
            }}
    instance = FakeShopify()
    job_gid = asyncio.run(label.purchase_confirmed_shopify_label(
        instance, confirmed_shipment()
    ))
    assert job_gid == RESULT_GID
    assert len(instance.calls) == 1
    assert "shippingLabelPurchase" in instance.calls[0][0]
    assert instance.calls[0][1]["shippingLabelPurchase"]["notifyCustomer"] is False


def test_shopify_shipping_label_response_must_be_nonambiguous():
    class FakeShopify:
        api_version = "2026-07"
        async def graphql(self, *, query, variables=None):
            return {"shippingLabelPurchase": {
                "shippingLabelPurchaseResult": None,
                "userErrors": [{"message": "confidential buyer address", "code": "RATES_NOT_FOUND"}],
            }}
    with pytest.raises(ShopifyApiError) as info:
        asyncio.run(label.purchase_confirmed_shopify_label(FakeShopify(), confirmed_shipment()))
    assert "confidential buyer address" not in str(info.value)


def test_label_poll_masks_document_urls_and_does_not_fabricate_cost():
    class FakeShopify:
        api_version = "2026-07"
        async def graphql(self, *, query, variables=None):
            assert variables == {"id": RESULT_GID}
            return {"node": {
                "id": RESULT_GID, "status": "PURCHASED", "done": True,
                "errors": [],
                "shippingLabels": [{
                    "id": "gid://shopify/ShippingLabel/3456",
                    "trackingInfo": {"number": "RJ123456789GB", "company": "Royal Mail", "url": "https://secret.url"},
                    "shippingDocuments": [
                        {"documentType": "LABEL", "format": "PDF", "url": "https://private.label.url"}
                    ],
                }],
            }}
    info = asyncio.run(label.poll_shopify_label_result(FakeShopify(), RESULT_GID))
    assert info["status"] == "PURCHASED"
    assert info["has_label_document"] is True
    assert info["verified_cost_minor"] is None
    assert info["tracking"] == [{"number": "RJ123456789GB", "company": "Royal Mail"}]
    assert "private.label.url" not in repr(info)
    assert "secret.url" not in repr(info)


def test_failed_async_label_returns_codes_not_private_messages():
    class FakeShopify:
        api_version = "2026-07"
        async def graphql(self, *, query, variables=None):
            return {"node": {
                "id": RESULT_GID, "status": "PURCHASE_FAILED", "done": True,
                "errors": [{"code": "CARRIER_NOT_AVAILABLE", "message": "secret buyer data"}],
                "shippingLabels": [],
            }}
    info = asyncio.run(label.poll_shopify_label_result(FakeShopify(), RESULT_GID))
    assert info["error_codes"] == ["CARRIER_NOT_AVAILABLE"]
    assert "secret buyer data" not in repr(info)
    assert info["verified_cost_minor"] is None
