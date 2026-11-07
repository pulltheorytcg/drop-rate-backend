"""Deterministic invoice journal and seller ledger integration (no Shopify purchase)."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import finance


def setup(monkeypatch, policy, *, order_status="PAID", consignor=False):
    founder = uuid4()
    owner = uuid4() if consignor else founder
    oid, item = uuid4(), uuid4()
    state = {"reconciled": False, "source": None, "events": []}

    class Conn:
        async def execute(self, sql, *args):
            if "pg_advisory_xact_lock" in sql:
                state["events"].append(("lock", args))
                return "SELECT 1"
            if "insert into tcg.shopify_postage_actual_costs" in sql:
                state["events"].append(("receipt", args))
                assert args[0] == oid
                assert args[1] == owner
                assert args[3] == 295
                assert args[4] == (295 if policy == "AUTOMATIC_FREE_UK_TRACKED_48" else 0)
                return "INSERT 0 1"
            if "insert into tcg.financial_ledger_entries" in sql:
                state["events"].append(("ledger", args))
                assert args[0] == owner
                assert args[1] == oid
                assert args[2] == item
                assert args[3] == -295
                return "INSERT 0 1"
            if "insert into tcg.order_item_reconciliations" in sql:
                state["events"].append(("reconciled", args))
                assert args[0] == item
                assert args[1] == oid
                assert args[2] == owner
                state["source"] = args[3]
                state["reconciled"] = True
                return "INSERT 0 1"
            raise AssertionError(sql)

        async def fetch(self, sql, *args):
            assert "from tcg.orders o" in sql
            assert args == (oid, owner)
            return [{
                "source": "SHOPIFY", "order_number": "#1009",
                "order_status": order_status,
                "order_item_id": item, "net_sale_minor": 15000,
                "product_type": "CARD", "grading_company": None,
                "grade": None,
                "shipping_cost_reconciled_at": (
                    datetime.now(timezone.utc) if state["reconciled"] else None
                ),
                "shipping_cost_source": state["source"],
            }]

        async def fetchrow(self, sql, *args):
            assert "from tcg.shopify_delivery_accounts" in sql
            assert args == (oid,)
            return {"charge_policy": policy}

    @asynccontextmanager
    async def conn(pool, uid, request_id):
        assert uid == founder
        yield Conn()

    async def founder_info(c):
        return {"id": founder, "owner_type": "FOUNDER"}

    monkeypatch.setattr(finance, "user_connection", conn)
    monkeypatch.setattr(finance, "_owner", founder_info)
    req = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="postage-policy"),
        url=SimpleNamespace(path="/api/v1/finance/shopify/orders/" + str(oid) + "/postage"),
    )
    payload = finance.ShopifyPostageReconcile(
        amount_minor=295, reference="TRACKED-UK-0001",
        owner_id=owner if consignor else None,
    )
    user = SimpleNamespace(user_id=founder)
    return oid, payload, req, user, state


def test_customer_paid_postage_records_real_carrier_cost_but_no_seller_debit(monkeypatch):
    oid, payload, req, user, state = setup(
        monkeypatch, "COMPANY_FUNDED_CUSTOMER_PAID", consignor=True,
    )
    value = asyncio.run(finance.reconcile_shopify_postage(oid, payload, req, user))
    assert value["verified_carrier_cost_minor"] == 295
    assert value["seller_net_shipping_charge_minor"] == 0
    assert value["shipping_cost_minor"] == 0
    assert value["replayed"] is False
    assert [event[0] for event in state["events"]] == ["lock", "receipt", "reconciled"]


def test_free_uk_tracked48_posts_exact_automatic_verified_seller_charge(monkeypatch):
    oid, payload, req, user, state = setup(
        monkeypatch, "AUTOMATIC_FREE_UK_TRACKED_48",
    )
    value = asyncio.run(finance.reconcile_shopify_postage(oid, payload, req, user))
    assert value["verified_carrier_cost_minor"] == 295
    assert value["seller_net_shipping_charge_minor"] == 295
    assert value["shipping_cost_minor"] == 295
    assert value["replayed"] is False
    assert [event[0] for event in state["events"]] == [
        "lock", "receipt", "ledger", "reconciled"
    ]


def test_same_invoice_replay_does_not_post_second_label_or_owner_charge(monkeypatch):
    oid, payload, req, user, state = setup(monkeypatch, "AUTOMATIC_FREE_UK_TRACKED_48")
    first = asyncio.run(finance.reconcile_shopify_postage(oid, payload, req, user))
    second = asyncio.run(finance.reconcile_shopify_postage(oid, payload, req, user))
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert [kind for kind, _ in state["events"]].count("receipt") == 1
    assert [kind for kind, _ in state["events"]].count("ledger") == 1


@pytest.mark.parametrize("status", ["PARTIALLY_REFUNDED", "REFUNDED", "CANCELLED"])
def test_refunded_or_cancelled_order_cannot_create_new_seller_postage_debit(monkeypatch,status):
    oid, payload, req, user, state = setup(
        monkeypatch, "AUTOMATIC_FREE_UK_TRACKED_48", order_status=status,
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(finance.reconcile_shopify_postage(oid, payload, req, user))
    assert error.value.status_code == 409
    assert not [x for x in state["events"] if x[0] in ("receipt","ledger")]
