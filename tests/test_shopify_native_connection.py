"""Live Shopify Shipping connection (read-only) is bound to exact owner allocations."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import owner_fulfillment as portal
from app import shopify_shipping_labels as shipping


ORDER_NUM = "8506160775515"
LINE_NUM = "20106310025563"


def example_shopify_order(*, status="OPEN", financial="PAID"):
    order_gid = shipping.canonical_shopify_order_gid(ORDER_NUM)
    return {
        "id": order_gid, "name": "#1009",
        "fullyPaid": financial == "PAID", "cancelledAt": None,
        "displayFinancialStatus": financial, "displayFulfillmentStatus": "UNFULFILLED",
        "lineItems": {"nodes": [{"id": shipping.canonical_shopify_line_gid(LINE_NUM)}],
                      "pageInfo": {"hasNextPage": False}},
        "fulfillmentOrders": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [{
                "id": "gid://shopify/FulfillmentOrder/100",
                "orderId": order_gid,
                "status": status,
                "requestStatus": "UNSUBMITTED",
                "assignedLocation": {
                    "location": {"id": "gid://shopify/Location/12"},
                    "countryCode": "GB",
                },
                "destination": {
                    "countryCode": "GB", "address1": "should never be returned",
                    "email": "secret@example.test",
                },
                "lineItems": {"nodes": [{
                    "id": "gid://shopify/FulfillmentOrderLineItem/321",
                    "remainingQuantity": 1, "totalQuantity": 1, "requiresShipping": True,
                    "lineItem": {"id": shipping.canonical_shopify_line_gid(LINE_NUM)},
                }], "pageInfo": {"hasNextPage": False}},
            }],
        },
        "shippingAddress": "secret should never be fetched",
    }


def setup(monkeypatch, *, owner=None, local_status="PAID", existing=True, remote_status="OPEN"):
    user_id = owner or uuid4()
    item_id = uuid4()
    order_id = uuid4()
    inv_id = uuid4()
    events = []

    class FakeConn:
        async def fetchrow(self, sql, *params):
            assert params == (user_id, item_id)
            assert "where oi.id=$2 and oi.owner_id=$1" in sql
            assert "i.owner_id=$1" in sql
            events.append("fetchrow")
            if not existing:
                return None
            return {
                "local_order_id": order_id,
                "source_reference": ORDER_NUM,
                "order_status": local_status,
                "physical_status": "SOLD",
                "shopify_order_id": ORDER_NUM,
                "shopify_line_item_id": LINE_NUM,
                "shopify_variant_gid": "gid://shopify/ProductVariant/900",
            }

        async def fetch(self, sql, *params):
            assert params == (user_id, order_id)
            assert "where oi.order_id=$2 and oi.owner_id=$1" in sql
            assert "i.owner_id=$1" in sql
            events.append("fetch")
            return [{
                "physical_status": "SOLD",
                "shopify_order_id": ORDER_NUM,
                "shopify_line_item_id": LINE_NUM,
                "shopify_variant_gid": "gid://shopify/ProductVariant/900",
                "customer_email": "private user field must be dropped",
            }]

    @asynccontextmanager
    async def fake_connection(pool, user, request_id):
        assert user == user_id
        yield FakeConn()

    async def fake_access(conn):
        return {"owner_id": user_id, "access_role": "OWNER"}

    class FakeShopify:
        api_version = "2026-07"
        shop_domain = "fqu56y-hm.myshopify.com"
        async def graphql(self, *, query, variables=None):
            assert variables == {"orderId": shipping.canonical_shopify_order_gid(ORDER_NUM)}
            assert "destination { countryCode }" in query
            assert "shippingAddress" not in query
            events.append("shopify_graphql")
            return {"order": example_shopify_order(status=remote_status)}
        async def probe_shop(self):
            events.append("shopify_probe")
            return {"name": "Drop Rate"}
        async def access_scopes(self):
            events.append("shopify_scopes")
            return {
                "read_orders", "read_merchant_managed_fulfillment_orders",
                "write_orders", "write_merchant_managed_fulfillment_orders",
            }

    monkeypatch.setattr(portal, "user_connection", fake_connection)
    monkeypatch.setattr(portal, "current_access_context", fake_access)
    monkeypatch.setattr(portal, "_shipping_admin_client", FakeShopify)
    req = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="dr-test"),
    )
    user = SimpleNamespace(user_id=user_id)
    return req, user, item_id, events


def test_shopify_native_preflight_exact_owner_item_only(monkeypatch):
    req, user, item_id, events = setup(monkeypatch)
    value = asyncio.run(portal.owner_shopify_preflight(item_id, req, user))
    assert value["source"] == "DIRECT_SHOPIFY_ADMIN_API"
    assert value["state"] == "AWAITING_DISPATCH_SETUP"
    assert value["shopify_connected"] is True
    assert value["fulfillment_order_id"] == "gid://shopify/FulfillmentOrder/100"
    assert value["can_buy_label"] is False
    assert events == ["fetchrow", "fetch", "shopify_graphql"]
    assert "secret@example.test" not in repr(value)
    assert "should never be" not in repr(value)
    assert "customer_email" not in repr(value)


def test_wrong_owner_order_item_returns_404_without_contacting_shopify(monkeypatch):
    req, user, item_id, events = setup(monkeypatch, existing=False)
    with pytest.raises(HTTPException) as error:
        asyncio.run(portal.owner_shopify_preflight(item_id, req, user))
    assert error.value.status_code == 404
    assert events == ["fetchrow"]


def test_refunded_order_cannot_contact_shopify_or_purchase(monkeypatch):
    req, user, item_id, events = setup(monkeypatch, local_status="REFUNDED")
    with pytest.raises(HTTPException) as error:
        asyncio.run(portal.owner_shopify_preflight(item_id, req, user))
    assert error.value.status_code == 409
    assert "shopify_graphql" not in events


def test_partial_refund_local_order_is_blocked_even_when_remote_paid(monkeypatch):
    req, user, item_id, events = setup(monkeypatch, local_status="PARTIALLY_REFUNDED")
    review = asyncio.run(portal.owner_shopify_preflight(item_id, req, user))
    assert review["state"] == "REVIEW_REQUIRED"
    assert "LOCAL_PARTIAL_REFUND_REVIEW_REQUIRED" in review["blockers"]
    assert review["can_buy_label"] is False


def test_remote_closed_order_blocks_label_readiness(monkeypatch):
    req, user, item_id, events = setup(monkeypatch, remote_status="CLOSED")
    review = asyncio.run(portal.owner_shopify_preflight(item_id, req, user))
    assert "FULFILMENT_ORDER_NOT_OPEN" in review["blockers"]
    assert review["state"] == "REVIEW_REQUIRED"


def test_connection_status_checks_native_api_without_buying_labels(monkeypatch):
    req, user, item_id, events = setup(monkeypatch)
    status = asyncio.run(portal.owner_shopify_shipping_status(req, user))
    assert status["store_connected"] is True
    assert status["shop"] == "Drop Rate"
    assert status["api_version"] == "2026-07"
    assert status["shopify_fulfilment_read_access"] is True
    assert status["shopify_label_write_scopes_present"] is True
    assert status["carrier_label_purchase"] is False
    assert status["dispatch_confirmation"] is False
    assert events == ["shopify_probe", "shopify_scopes"]


def test_no_post_mutations_or_direct_origin_leak_in_seller_router():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "backend/app/owner_fulfillment.py").read_text()
    assert '@router.get("/shopify-status")' in source
    assert '@router.get("/to-ship/{order_item_id}/shopify")' in source
    assert "@router.post(" not in source
    assert "shippingLabelPurchase(" not in source
    for value in ("customer_email", "shipping_address", "billing_address"):
        assert value not in source
