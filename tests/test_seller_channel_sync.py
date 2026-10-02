from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import seller_channel_sync as sync
from app import ebay_sales, ebay_seller_connection


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,status", [("allowed", 200), ("foreign", 404), ("draft", 409),
    ("personal", 409), ("stale", 409), ("disabled", 409), ("founder", 403)])
async def test_seller_sync_cannot_publish_foreign_unapproved_or_stale_inventory(monkeypatch, scenario, status):
    owner, user_id, item_id = uuid4(), uuid4(), uuid4()
    class Connection:
        async def fetch(self, sql):
            return [{"role": "PLATFORM_ADMIN" if scenario == "founder" else "OWNER", "owner_id": owner,
                     "user_id": user_id, "display_name": "Seller", "owner_type": "CONSIGNOR", "founder_slot": None,
                     "founder_authorized": True}]
        async def fetchrow(self, sql, *args):
            assert "owner_id=$2" in sql and args == (item_id, owner)
            return None if scenario == "foreign" else {
                "id": item_id, "version": 2 if scenario == "stale" else 1,
                "status": "DRAFT" if scenario == "draft" else "APPROVED",
                "sale_intent": "PERSONAL_COLLECTION" if scenario == "personal" else "FOR_SALE"}
    @asynccontextmanager
    async def connection(*args):
        yield Connection()
    monkeypatch.setattr(sync, "user_connection", connection)
    monkeypatch.setattr(sync, "get_settings", lambda: SimpleNamespace(shopify_seller_sync_enabled=scenario != "disabled", shopify_publish_enabled=True))
    publish = AsyncMock(return_value={"status": "PUBLISHED", "internal_plan": "private"})
    monkeypatch.setattr(sync, "publish_inventory_to_shopify", publish)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())), state=SimpleNamespace(request_id="test"))
    if status == 200:
        result = await sync.sync_inventory(item_id, "shopify", sync.SyncRequest(version=1), request, SimpleNamespace(user_id=user_id))
        assert result == {"inventory_id": str(item_id), "channel": "SHOPIFY", "status": "PUBLISHED"}
        assert publish.call_args.kwargs["owner_id"] == owner
        assert publish.call_args.kwargs["test_mode"] is False
    else:
        with pytest.raises(HTTPException) as error:
            await sync.sync_inventory(item_id, "shopify", sync.SyncRequest(version=1), request, SimpleNamespace(user_id=user_id))
        assert error.value.status_code == status
        publish.assert_not_called()


@pytest.mark.asyncio
async def test_shared_ebay_uses_store_binding_instead_of_inventory_owner(monkeypatch):
    store, seller = uuid4(), uuid4()
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(ebay_seller_connection, "_load_connection_row", lookup)
    with pytest.raises(RuntimeError, match="not connected"):
        await ebay_seller_connection.load_effective_seller_config(object(), SimpleNamespace(ebay_shared_store_owner_id=str(store)), owner_id=seller)
    assert lookup.call_args.kwargs["owner_id"] == store


@pytest.mark.asyncio
async def test_shared_store_ignores_legacy_global_token_and_policies(monkeypatch):
    store = uuid4()
    row = {"id": uuid4(), "owner_id": store, "status": "READY", "refresh_token_ciphertext": "encrypted",
           "granted_scopes": [], "payment_policy_id": "shared-payment", "fulfillment_policy_id": "shared-shipping",
           "return_policy_id": "shared-returns", "merchant_location_key": "shared-location",
           "notification_destination_id": None, "notification_subscription_id": None}
    monkeypatch.setattr(ebay_seller_connection, "_load_connection_row", AsyncMock(return_value=row))
    monkeypatch.setattr(ebay_seller_connection, "decrypt_refresh_token", lambda *_: "shared-token")
    settings = SimpleNamespace(ebay_shared_store_owner_id=str(store), ebay_user_refresh_token="other-store-token",
        ebay_payment_policy_id="other-payment", ebay_fulfillment_policy_id="other-shipping",
        ebay_return_policy_id="other-returns", ebay_merchant_location_key="other-location")
    config = await ebay_seller_connection.load_effective_seller_config(object(), settings, owner_id=uuid4())
    assert config.refresh_token == "shared-token"
    assert config.payment_policy_id == "shared-payment"
    assert config.fulfillment_policy_id == "shared-shipping"
    assert config.return_policy_id == "shared-returns"
    assert config.merchant_location_key == "shared-location"


@pytest.mark.asyncio
async def test_shared_order_passes_exact_allocations_to_atomic_database_handler(monkeypatch):
    import json
    monkeypatch.setattr(ebay_sales, "get_settings", lambda: SimpleNamespace(ebay_shared_store_owner_id=str(uuid4())))
    result = {"action": "EBAY_ORDER_RECORDED", "inventory_ids": ["one", "two"]}
    conn = SimpleNamespace(fetchval=AsyncMock(return_value=result))
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield conn
    order = {"orderId": "mixed-owner", "creationDate": "2026-10-02T12:00:00Z", "pricingSummary": {"deliveryCost": {"value": "4.99", "currency": "GBP"}},
             "lineItems": [{"legacyItemId": "listing-a", "lineItemId": "a", "quantity": 1, "lineItemCost": {"value": "10.00", "currency": "GBP"}},
                           {"legacyItemId": "listing-b", "lineItemId": "b", "quantity": 1, "lineItemCost": {"value": "20.00", "currency": "GBP"}}]}
    assert await ebay_sales._record_ebay_order(Pool(), order) == result
    lines = json.loads(conn.fetchval.call_args.args[3])
    assert sum(line["shipping_minor"] for line in lines) == 499
    assert sum(line["sale_price_minor"] for line in lines) == 3000
    assert all("owner_id" not in line for line in lines)


@pytest.mark.asyncio
async def test_parallel_ebay_publishes_leave_capacity_for_their_own_queries(monkeypatch):
    import asyncio
    slots = asyncio.Semaphore(2)
    class Connection:
        async def fetchval(self, *args):
            await asyncio.sleep(0)
            return True
    class Pool:
        def get_max_size(self):
            return 2
        @asynccontextmanager
        async def acquire(self):
            async with slots:
                yield Connection()
    pool = Pool()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
    async def publish(*args):
        async with pool.acquire():
            await asyncio.sleep(0)
            return {"status": "LIVE"}
    monkeypatch.setattr(ebay_sales, "_ebay_publish_slots", asyncio.Semaphore(1))
    monkeypatch.setattr(ebay_sales, "_publish_inventory_to_ebay", publish)
    results = await asyncio.wait_for(asyncio.gather(*[
        ebay_sales.publish_inventory_to_ebay(uuid4(), ebay_sales.EbayListRequest(version=1), request, object())
        for _ in range(5)
    ]), timeout=1)
    assert len(results) == 5
    assert all(result["status"] == "LIVE" for result in results)
