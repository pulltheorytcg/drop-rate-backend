"""Shopify-source packing slip is exact-owner only, paid and printable."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.shopify_packing_slip import (
    PackingSlipNotReady, build_shopify_owner_packing_slip,
)
from app import owner_fulfillment as routes


ORDER = "8506160775515"
SHOPIFY_GID = "gid://shopify/Order/" + ORDER
LINE = "gid://shopify/LineItem/20106310025563"
OTHER_LINE = "gid://shopify/LineItem/20106310025564"


def allocation(line_id="20106310025563", *, code="INV-OWNER-COPY", **kw):
    row = dict(
        order_item_id=str(uuid4()),
        inventory_code=code,
        physical_status="SOLD",
        order_status="PAID",
        shopify_order_id=ORDER,
        shopify_line_item_id=line_id,
    )
    row.update(kw)
    return row


def remote_order(*, cancelled=False, full=True, state="PAID", remaining=2,
                 other_seller=True, partial=False):
    lines = [{
        "id": LINE, "title": "Booster Pack OP17",
        "sku": "DR-OP17-JP", "quantity": 2,
        "currentQuantity": remaining,
    }]
    fos = [{
        "id": "gid://shopify/FulfillmentOrder/300",
        "status": "OPEN", "requestStatus": "UNSUBMITTED",
        "lineItems": {
            "nodes": [{
                "lineItem": {"id": LINE},
                "remainingQuantity": remaining,
                "requiresShipping": True,
            }],
            "pageInfo": {"hasNextPage": False},
        },
    }]
    if other_seller:
        lines.append({
            "id": OTHER_LINE, "title": "Other seller secret card",
            "sku": "OTHER-SECRET", "quantity": 1, "currentQuantity": 1,
        })
        fos[0]["lineItems"]["nodes"].append({
            "lineItem": {"id": OTHER_LINE},
            "remainingQuantity": 1,
            "requiresShipping": True,
        })
    return {
        "id": SHOPIFY_GID, "name": "#1009",
        "cancelledAt": "2026-10-11T00:00:00Z" if cancelled else None,
        "fullyPaid": full, "displayFinancialStatus": state,
        "displayFulfillmentStatus": "PARTIALLY_FULFILLED" if partial else "UNFULFILLED",
        "lineItems": {"nodes": lines, "pageInfo": {"hasNextPage": False}},
        "fulfillmentOrders": {
            "nodes": fos, "pageInfo": {"hasNextPage": False},
        },
        "shippingAddress": {
            "name": "Private Name", "address1": "Private Location",
            "email": "buyer-private@example.com",
        },
    }


def make_slip(remote=None, owned=None):
    return build_shopify_owner_packing_slip(
        remote_order=remote if remote is not None else remote_order(),
        source_reference=ORDER,
        owner_allocations=owned if owned is not None else [allocation()],
    )


def test_shopify_derived_slip_contains_exact_seller_copy_only():
    slip = make_slip()
    assert slip["source"] == "SHOPIFY_ADMIN_ORDER"
    assert slip["document_type"] == "OWNER_PACKING_SLIP"
    assert slip["order_number"] == "#1009"
    assert slip["item_count"] == 1
    assert slip["items"][0]["title"] == "Booster Pack OP17"
    assert slip["items"][0]["inventory_id"] == "INV-OWNER-COPY"
    assert slip["items"][0]["sku"] == "DR-OP17-JP"
    assert slip["items"][0]["quantity"] == "1"
    assert slip["ship_to"] is None
    assert slip["is_shopify_native_print_template"] is False
    assert slip["customer_personal_data_included"] is False
    assert "Other seller secret" not in str(slip)
    assert "OTHER-SECRET" not in str(slip)
    assert "buyer-private@example.com" not in str(slip)
    assert "Private Location" not in str(slip)


def test_one_owner_can_print_exact_one_of_two_pooled_variant_copies():
    slip = make_slip(remote=remote_order(other_seller=False,remaining=2),
                     owned=[allocation(code="INV-ONE")])
    assert slip["item_count"] == 1
    assert [x["inventory_id"] for x in slip["items"]] == ["INV-ONE"]
    assert not slip["can_purchase_label"] and not slip["can_confirm_dispatched"]


def test_two_owned_copies_are_individually_identified_and_no_duplicated_sku():
    result = make_slip(
        remote=remote_order(other_seller=False),
        owned=[allocation(code="INV-COPY-A"), allocation(code="INV-COPY-B")],
    )
    assert result["item_count"] == 2
    assert [x["inventory_id"] for x in result["items"]] == ["INV-COPY-A", "INV-COPY-B"]


@pytest.mark.parametrize("change", [
    {"cancelled": True},
    {"full": False},
    {"state": "PARTIALLY_REFUNDED"},
    {"remaining": 0},
])
def test_cancelled_unpaid_refunded_or_no_quantities_never_print(change):
    with pytest.raises(PackingSlipNotReady):
        make_slip(remote=remote_order(**change))


@pytest.mark.parametrize("bad", [
    [allocation(shopify_order_id="99888777")],
    [allocation(physical_status="APPROVED")],
    [allocation(order_status="PARTIALLY_REFUNDED")],
    [allocation(shopify_line_item_id="00000")],
    [allocation(inventory_code="")],
    [],
])
def test_invalid_local_ownership_or_unpaid_copies_block_slip(bad):
    with pytest.raises(PackingSlipNotReady):
        make_slip(owned=bad)


def test_duplicate_same_physical_order_item_id_is_not_printed_twice():
    own = allocation()
    with pytest.raises(PackingSlipNotReady):
        make_slip(owned=[own, dict(own)])


def test_finished_fulfillment_or_truncated_orders_are_not_printable():
    remote = remote_order()
    remote["fulfillmentOrders"]["nodes"][0]["status"] = "CLOSED"
    with pytest.raises(PackingSlipNotReady):
        make_slip(remote=remote)
    remote = remote_order()
    remote["fulfillmentOrders"]["pageInfo"]["hasNextPage"] = True
    with pytest.raises(PackingSlipNotReady):
        make_slip(remote=remote)
    remote = remote_order()
    remote["lineItems"]["pageInfo"]["hasNextPage"] = True
    with pytest.raises(PackingSlipNotReady):
        make_slip(remote=remote)


def test_order_id_forgery_or_missing_order_blocks_slip():
    with pytest.raises(PackingSlipNotReady):
        make_slip(remote={"id":"gid://shopify/Order/999"})
    with pytest.raises(PackingSlipNotReady):
        make_slip(remote={})


def test_official_order_title_used_not_local_untrusted_card_title():
    slip = make_slip(owned=[allocation(code="INV-EXACT")])
    assert slip["items"][0]["title"] == "Booster Pack OP17"
    assert "shopify" in slip["source"].lower()


def test_seller_http_route_scopes_queries_and_never_returns_customer_pii(monkeypatch):
    owner = uuid4()
    selected = uuid4()
    order_id = uuid4()
    calls=[]

    class Conn:
        async def fetchrow(self, sql, *args):
            calls.append("selected")
            assert args == (owner, selected)
            assert "i.owner_id=$1" in sql
            assert "sol.owner_id=$1" in sql
            assert "oi.id=$2 and oi.owner_id=$1" in sql
            return {"local_order_id":order_id, "source_reference":ORDER,"order_status":"PAID"}

        async def fetch(self, sql, *args):
            calls.append("owned")
            assert args == (owner, order_id)
            assert "oi.owner_id=$1" in sql
            assert "sol.owner_id=$1" in sql
            return [allocation()]

    @asynccontextmanager
    async def fake_conn(pool, uid, request_id):
        assert uid == owner
        yield Conn()

    async def fake_access(conn):
        return {"owner_id":owner,"access_role":"OWNER"}

    class Shopify:
        async def graphql(self, *, query, variables):
            calls.append("shopify")
            assert variables == {"orderId":SHOPIFY_GID}
            assert "title sku" in query
            assert "shippingAddress" not in query
            return {"order":remote_order()}

    monkeypatch.setattr(routes,"user_connection",fake_conn)
    monkeypatch.setattr(routes,"current_access_context",fake_access)
    monkeypatch.setattr(routes,"_shipping_admin_client",lambda:Shopify())
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                            state=SimpleNamespace(request_id="test-pack"))
    response=asyncio.run(routes.owner_shopify_packing_slip(
        selected,request,SimpleNamespace(user_id=owner)
    ))
    assert response["item_count"] == 1
    assert calls == ["selected","owned","shopify"]
    assert "Private Name" not in str(response)
    assert "buyer-private" not in str(response)


def test_not_paid_local_order_does_not_even_call_shopify(monkeypatch):
    owner=uuid4()
    selected=uuid4()
    @asynccontextmanager
    async def fake_conn(*args,**kwargs):
        class Conn:
            async def fetchrow(self,sql,*args):
                return {"local_order_id":uuid4(),"source_reference":ORDER,
                        "order_status":"PARTIALLY_REFUNDED"}
        yield Conn()
    async def fake_access(conn):return {"owner_id":owner}
    monkeypatch.setattr(routes,"user_connection",fake_conn)
    monkeypatch.setattr(routes,"current_access_context",fake_access)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                            state=SimpleNamespace(request_id="test-pack"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.owner_shopify_packing_slip(
            selected,request,SimpleNamespace(user_id=owner)
        ))
    assert exc.value.status_code == 409
