"""Shipping transparency reads exact Shopify checkout and ledger, never guessed labels."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.seller_shipping_charges import (
    ShippingCostReviewRequired,
    shipping_charge_breakdown,
)
from app import owner_fulfillment as portal


ORDER_ID = "gid://shopify/Order/8506160775515"


def shopify_order(
    *,
    amount="3.95", refunded="0.00",
    title="Royal Mail Tracked 48", code="GBP", original=None,
):
    try:
        retained = str(Decimal(amount) - Decimal(refunded))
    except Exception:
        retained = amount
    return {
        "id": ORDER_ID,
        "cancelledAt": None,
        "fullyPaid": True,
        "displayFinancialStatus": "PAID",
        # A free-delivery discount can leave the ORIGINAL rate as £3.95,
        # while the actual customer checkout payment is £0.
        "totalShippingPriceSet": {
            "shopMoney": {"amount": original if original is not None else amount,
                          "currencyCode": code}
        },
        "currentShippingPriceSet": {
            "shopMoney": {"amount": retained, "currencyCode": code}
        },
        "totalRefundedShippingSet": {
            "shopMoney": {"amount": refunded, "currencyCode": code}
        },
        "shippingLines": {
            "nodes": [{
                "title": title,
                "discountedPriceSet": {"shopMoney": {
                    "amount": amount, "currencyCode": code,
                }},
                "currentDiscountedPriceSet": {"shopMoney": {
                    "amount": retained, "currencyCode": code,
                }},
            }],
            "pageInfo": {"hasNextPage": False},
        },
        "buyer_details": {
            "name": "Private buyer", "address": "Sensitive location",
        },
    }


def ledger(*, owner_share=395, owner_refund=0, postage=0, verified=False):
    return {
        "owner_items": 1,
        "shipping_revenue_minor": owner_share,
        "shipping_refund_minor": owner_refund,
        "postage_cost_minor": postage,
        "postage_reconciled": verified,
    }


def breakdown(order=None, account=None):
    return shipping_charge_breakdown(
        remote_order=order if order is not None else shopify_order(),
        source_reference_gid=ORDER_ID,
        owner_ledger=account if account is not None else ledger(),
    )


def test_paid_uk_tracked_48_no_duplicate_charge_and_no_guessed_postage():
    value=breakdown()
    assert value["buyer_shipping_retained_minor"] == 395
    assert value["owner_allocated_shipping_minor"] == 395
    assert value["verified_postage_cost_minor"] is None
    assert value["seller_additional_shipping_charge_minor"] is None
    assert value["postage_verification"] == "PENDING_VERIFIED_CARRIER_COST"
    assert value["carrier_quote_minor"] is None
    assert value["purchase_allowed"] is False
    assert value["service_names"] == ["Royal Mail Tracked 48"]
    assert "Private buyer" not in repr(value)
    assert "Sensitive location" not in repr(value)


def test_free_uk_50_still_has_unknown_real_carrier_cost():
    value=breakdown(shopify_order(amount="0.00", original="3.95"), ledger(owner_share=0))
    assert value["buyer_shipping_retained_minor"] == 0
    assert value["owner_allocated_shipping_minor"] == 0
    assert value["verified_postage_cost_minor"] is None
    assert value["seller_additional_shipping_charge_minor"] is None
    assert value["purchase_allowed"] is False


def test_free_shipping_discount_never_uses_undiscounted_395_original_rate():
    order = shopify_order(amount="0.00", original="3.95")
    assert order["totalShippingPriceSet"]["shopMoney"]["amount"] == "3.95"
    assert order["currentShippingPriceSet"]["shopMoney"]["amount"] == "0.00"
    value = breakdown(order, ledger(owner_share=0))
    assert value["buyer_shipping_charged_minor"] == 0
    assert value["buyer_shipping_retained_minor"] == 0
    assert value["owner_allocated_shipping_minor"] == 0
    assert value["seller_additional_shipping_charge_minor"] is None


def test_shopify_shipping_line_total_mismatch_blocks_unverified_amounts():
    order = shopify_order()
    order["currentShippingPriceSet"]["shopMoney"]["amount"] = "0.00"
    with pytest.raises(ShippingCostReviewRequired):
        breakdown(order)
    order = shopify_order()
    order["shippingLines"]["nodes"][0]["currentDiscountedPriceSet"]["shopMoney"]["amount"] = "0.00"
    with pytest.raises(ShippingCostReviewRequired):
        breakdown(order)


def test_express_order_over_50_must_still_show_customer_paid_495():
    # The checkout method is authoritative: do not apply £50 to Tracked 24.
    value=breakdown(
        shopify_order(amount="4.95",title="Royal Mail Tracked 24"),
        ledger(owner_share=495),
    )
    assert value["buyer_shipping_retained_minor"] == 495
    assert value["service_names"] == ["Royal Mail Tracked 24"]


@pytest.mark.parametrize("country_rate,title,minor", [
    ("14.99","Royal Mail International Tracked",1499),
    ("23.99","Royal Mail International Tracked",2399),
])
def test_international_paid_shipping_remains_independent_of_uk_50(country_rate,title,minor):
    value=breakdown(
        shopify_order(amount=country_rate,title=title),
        ledger(owner_share=minor),
    )
    assert value["buyer_shipping_retained_minor"] == minor
    assert value["owner_allocated_shipping_minor"] == minor
    assert value["carrier_quote_minor"] is None


def test_two_sellers_split_one_checkout_charge_not_each_awarded_full_total():
    a=breakdown(shopify_order(), ledger(owner_share=158))
    b=breakdown(shopify_order(), ledger(owner_share=237))
    assert a["owner_allocated_shipping_minor"] + b["owner_allocated_shipping_minor"] == 395
    assert a["buyer_shipping_retained_minor"] == 395
    assert b["buyer_shipping_retained_minor"] == 395
    for row in (a,b):
        assert row["seller_additional_shipping_charge_minor"] is None


def test_verified_actual_postage_offset_returns_credit_or_a_charge():
    credit=breakdown(shopify_order(),ledger(owner_share=395,postage=295,verified=True))
    assert credit["verified_postage_cost_minor"] == 295
    assert credit["seller_additional_shipping_charge_minor"] == 0
    assert credit["seller_shipping_credit_after_postage_minor"] == 100
    charge=breakdown(shopify_order(),ledger(owner_share=158,postage=672,verified=True))
    assert charge["verified_postage_cost_minor"] == 672
    assert charge["seller_additional_shipping_charge_minor"] == 514
    assert charge["seller_shipping_credit_after_postage_minor"] == 0
    assert charge["purchase_allowed"] is False


def test_postage_ledger_value_without_reconciliation_is_not_presented_as_actual():
    value=breakdown(shopify_order(),ledger(owner_share=395,postage=10000,verified=False))
    assert value["verified_postage_cost_minor"] is None
    assert value["seller_additional_shipping_charge_minor"] is None


@pytest.mark.parametrize("mutation", [
    {"cancelledAt": "2026-10-11T10:00:00Z"},
    {"fullyPaid": False},
    {"displayFinancialStatus": "PARTIALLY_REFUNDED"},
    {"displayFinancialStatus": "REFUNDED"},
    {"id": "gid://shopify/Order/other"},
])
def test_refund_cancel_unknown_payment_and_wrong_order_are_blocked(mutation):
    current=shopify_order()
    current.update(mutation)
    with pytest.raises(ShippingCostReviewRequired):
        breakdown(current)


@pytest.mark.parametrize("change", [
    {"amount": "not-money"},
    {"amount": "-1.00"},
    {"amount": "3.955"},
    {"amount": "NaN"},
    {"amount": "Infinity"},
    {"code": "USD"},
    {"amount": "0.00", "refunded": "0.01"},
    {"amount": "3.95", "refunded": "4.95"},
])
def test_unverifiable_money_never_fabricates_seller_deduction(change):
    with pytest.raises(ShippingCostReviewRequired):
        breakdown(shopify_order(**change))


def test_shipping_lines_truncation_and_bad_ledger_are_blocked():
    order=shopify_order()
    order["shippingLines"]["pageInfo"]["hasNextPage"]=True
    with pytest.raises(ShippingCostReviewRequired):
        breakdown(order)
    for row in (
        ledger(owner_share=396),
        ledger(owner_share=-1),
        ledger(owner_share=50,owner_refund=51),
        ledger(owner_share=395,postage=-1,verified=True),
    ):
        with pytest.raises(ShippingCostReviewRequired):
            breakdown(shopify_order(),row)


def test_customer_shipping_refund_offsets_only_existing_owner_shipping_credit():
    result=breakdown(
        shopify_order(amount="3.95",refunded="1.00"),
        ledger(owner_share=395,owner_refund=100),
    )
    assert result["buyer_shipping_charged_minor"] == 395
    assert result["buyer_shipping_refunded_minor"] == 100
    assert result["buyer_shipping_retained_minor"] == 295
    assert result["owner_allocated_shipping_minor"] == 295


def test_owner_scoped_http_endpoint_proves_order_and_ledger_before_shopify(monkeypatch):
    user_id=uuid4()
    item_id=uuid4()
    local_id=uuid4()
    seen=[]
    class FakeConn:
        async def fetchrow(self,sql,*args):
            if "select o.id as local_order_id" in sql:
                assert args == (user_id,item_id)
                assert "sol.owner_id=$1" in sql
                assert "i.owner_id=$1" in sql
                assert "oi.id=$2 and oi.owner_id=$1" in sql
                seen.append("selected")
                return {"local_order_id":local_id,"source_reference":"8506160775515",
                        "local_order_status":"PAID"}
            assert args == (user_id,local_id)
            assert "where oi.order_id=$2 and oi.owner_id=$1" in sql
            assert "le.owner_id=$1" in sql
            assert "rec.owner_id=$1" in sql
            seen.append("ledger")
            return ledger(owner_share=158)
    @asynccontextmanager
    async def fake_connection(pool,uid,request_id):
        assert uid==user_id
        yield FakeConn()
    async def fake_access(conn):
        return {"owner_id":user_id,"access_role":"OWNER"}
    class FakeShopify:
        async def graphql(self,*,query,variables):
            assert variables == {"orderId":ORDER_ID}
            assert "shippingLines" in query
            assert "currentShippingPriceSet" in query
            assert "discountedPriceSet" in query
            assert "currentDiscountedPriceSet" in query
            assert "shippingAddress" not in query
            seen.append("shopify")
            return {"order":shopify_order()}
    monkeypatch.setattr(portal,"user_connection",fake_connection)
    monkeypatch.setattr(portal,"current_access_context",fake_access)
    monkeypatch.setattr(portal,"_shipping_admin_client",lambda:FakeShopify())
    req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                        state=SimpleNamespace(request_id="fee-preview"))
    result=asyncio.run(portal.owner_shopify_shipping_cost_preview(
        item_id,req,SimpleNamespace(user_id=user_id)
    ))
    assert result["owner_item_count"] == 1
    assert result["owner_allocated_shipping_minor"] == 158
    assert result["buyer_shipping_retained_minor"] == 395
    assert result["purchase_allowed"] is False
    assert seen == ["selected","ledger","shopify"]
    assert "Private buyer" not in repr(result)


def test_wrong_owner_returns_404_without_shopify_request(monkeypatch):
    user_id=uuid4()
    @asynccontextmanager
    async def fake_connection(pool,uid,request_id):
        class FakeConn:
            async def fetchrow(self,sql,*args):
                return None
        yield FakeConn()
    async def fake_access(conn):return {"owner_id":user_id,"access_role":"OWNER"}
    monkeypatch.setattr(portal,"user_connection",fake_connection)
    monkeypatch.setattr(portal,"current_access_context",fake_access)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                            state=SimpleNamespace(request_id="fee-preview"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(portal.owner_shopify_shipping_cost_preview(
            uuid4(),request,SimpleNamespace(user_id=user_id)
        ))
    assert exc.value.status_code == 404
