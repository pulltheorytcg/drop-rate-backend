"""Dispatch review v1: owner-scoped Shopify allocations, zero customer PII."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import owner_fulfillment as dispatch


ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "backend/app/main.py"


def _record(**overrides):
    row = {
        "order_status": "PAID",
        "physical_status": "SOLD",
        "shopify_order_id": "8506160775515",
        "source_reference": "8506160775515",
        "shopify_line_item_id": "20106310025563",
        "shopify_variant_gid": "gid://shopify/ProductVariant/12345",
    }
    row.update(overrides)
    return row


def test_clean_paid_allocation_still_requires_verified_shipper_and_label():
    status = dispatch.evaluate_dispatch_review(_record())
    assert status["state"] == "AWAITING_DISPATCH_SETUP"
    assert status["can_buy_label"] is False
    assert status["can_confirm_dispatched"] is False
    assert status["blockers"] == [
        "PHYSICAL_SHIPPER_UNVERIFIED",
        "CARRIER_AND_SHOPIFY_FULFILMENT_NOT_CONNECTED",
    ]


@pytest.mark.parametrize("bad", [
    {"order_status": "PARTIALLY_REFUNDED"},
    {"order_status": "CANCELLED"},
    {"physical_status": "APPROVED"},
    {"shopify_line_item_id": None},
    {"shopify_variant_gid": None},
    {"shopify_order_id": "another-order"},
])
def test_unsafe_order_is_not_presented_as_ready_for_dispatch(bad):
    review = dispatch.evaluate_dispatch_review(_record(**bad))
    assert review["state"] == "REVIEW_REQUIRED"
    assert not review["can_buy_label"]
    assert not review["can_confirm_dispatched"]


def test_missing_or_spoofed_order_allocation_is_blocked():
    for row in [
        _record(shopify_order_id=None),
        _record(source_reference="different-order"),
        _record(shopify_line_item_id=""),
    ]:
        assert "SHOPIFY_ALLOCATION_INCOMPLETE" in dispatch.evaluate_dispatch_review(row)["blockers"]


def test_router_is_registered_and_has_no_mutation_or_customer_address():
    main = SHELL.read_text()
    source = (ROOT / "backend/app/owner_fulfillment.py").read_text()
    assert "app.include_router(owner_fulfillment_router)" in main
    assert 'router = APIRouter(prefix="/api/v1/fulfilment"' in source
    assert '@router.get("/to-ship")' in source
    for method in ("post", "patch", "put", "delete"):
        assert f"@router.{method}(" not in source
    assert "where oi.owner_id=$1" in source
    assert "i.owner_id=$1" in source
    assert "sol.owner_id=$1" in source
    assert "current_access_context(connection)" in source
    for forbidden in ("customer_email", "shipping_address", "billing_address", "shipping_address1", "customer_phone"):
        assert forbidden not in source


def test_all_capabilities_explicitly_restrict_dispatch_and_addresses():
    assert dispatch.CAPABILITIES == {
        "shopify_order_allocation": True,
        "carrier_label_purchase": False,
        "dispatch_confirmation": False,
        "shopify_tracking_sync": False,
        "buyer_address_access": False,
    }


def test_live_like_paged_query_never_leaks_other_owner_or_address(monkeypatch):
    owner = uuid4()
    other_owner = uuid4()
    item_id = uuid4()
    captured = []

    class FakeConnection:
        async def fetchval(self, statement, *params):
            captured.append(("count", statement, params))
            assert params == (owner,)
            assert "where oi.owner_id=$1" in statement
            return 1

        async def fetch(self, statement, *params):
            captured.append(("page", statement, params))
            assert params == (owner, 25, 0)
            assert "sol.owner_id=$1" in statement
            assert "where oi.owner_id=$1" in statement
            return [{
                "order_item_id": item_id,
                "order_number": "#1009",
                "source_reference": "8506160775515",
                "order_status": "PAID",
                "placed_at": "2026-10-10T14:00:00+00:00",
                "inventory_code": "INV-EXAMPLE",
                "physical_status": "SOLD",
                "card_name": "Illustrative card",
                "game": "One Piece",
                "set_name": "Illustrative set",
                "card_number": "001",
                "net_sale_minor": 1250,
                "shopify_order_id": "8506160775515",
                "shopify_line_item_id": "20106310025563",
                "shopify_variant_gid": "gid://shopify/ProductVariant/12345",
                "customer_email": "must-never-return@example.com",
                "shipping_address": "must never be returned",
                "owner_id": other_owner,
            }]

    @asynccontextmanager
    async def fake_connection(pool, user_id, request_id):
        assert user_id == owner
        yield FakeConnection()

    async def fake_access(connection):
        return {"owner_id": owner, "access_role": "OWNER"}

    monkeypatch.setattr(dispatch, "user_connection", fake_connection)
    monkeypatch.setattr(dispatch, "current_access_context", fake_access)

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
        state=SimpleNamespace(request_id="test-owner-dispatch"),
    )
    user = SimpleNamespace(user_id=owner)
    response = asyncio.run(dispatch.owner_to_ship(request, user, 25, 0))
    assert response["total"] == 1 and len(response["items"]) == 1
    assert response["items"][0]["order_item_id"] == str(item_id)
    assert response["items"][0]["can_confirm_dispatched"] is False
    assert "customer_email" not in str(response)
    assert "shipping_address" not in str(response)
    assert str(other_owner) not in str(response)
    assert [kind for kind, *_ in captured] == ["count", "page"]
