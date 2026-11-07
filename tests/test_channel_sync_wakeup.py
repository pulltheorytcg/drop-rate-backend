import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import api, catalogue_maintenance as jobs
from app.channel_sync_wakeup import request_shopify_sync
from app.schemas import InventoryApproval


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_error", [False, True])
async def test_approval_wakes_only_after_commit(monkeypatch, commit_error):
    event = asyncio.Event()
    item_id, owner_id = uuid4(), uuid4()
    row = dict(id=item_id, owner_id=owner_id, product_type="CARD", version=1,
               status="DRAFT", condition="Near Mint", seal_status=None,
               grading_company=None, grade=None, certificate_number=None,
               acquisition_cost_minor=100, storage_location_id=uuid4(),
               store_price_minor=200, language="English", identity_confirmed=True)

    class Connection:
        async def fetchrow(self, sql, *args):
            if "update tcg.inventory_items" in sql:
                return dict(row, status="APPROVED", version=2)
            return row

    @asynccontextmanager
    async def connection(*args):
        yield Connection()
        assert not event.is_set(), "Worker woke before the inventory commit"
        if commit_error:
            raise RuntimeError("Commit failed")

    async def owner(_):return {"id": owner_id}
    monkeypatch.setattr(api, "user_connection", connection)
    monkeypatch.setattr(api, "_owner", owner)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=None, shopify_sync_wakeup=event)),
                              state=SimpleNamespace(request_id="test"))
    call = api.approve_inventory(item_id, InventoryApproval(version=1), request, SimpleNamespace(user_id=uuid4()))
    if commit_error:
        with pytest.raises(RuntimeError, match="Commit failed"):await call
        assert not event.is_set()
    else:
        assert (await call)["status"] == "APPROVED"
        assert event.is_set()


@pytest.mark.asyncio
async def test_worker_wakes_from_idle_and_preserves_signal_during_pass(monkeypatch):
    wakeup, first, second, release, third = (asyncio.Event() for _ in range(5))
    calls = 0

    async def scan(*args):
        nonlocal calls
        calls += 1
        if calls == 1:first.set()
        if calls == 2:
            second.set()
            await release.wait()
        if calls == 3:third.set()

    monkeypatch.setattr(jobs, "shopify_pass", scan)
    task = asyncio.create_task(jobs.run_loop(None, None, shopify=True, wakeup=wakeup))
    try:
        await asyncio.wait_for(first.wait(), 1)
        wakeup.set()
        await asyncio.wait_for(second.wait(), 1)
        wakeup.set()  # A second approval arrives during the current scan.
        release.set()
        await asyncio.wait_for(third.wait(), 1)
        assert calls == 3
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task


def test_disabled_worker_has_no_signal_and_duplicate_signals_coalesce():
    state = SimpleNamespace()
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    assert not request_shopify_sync(request)
    state.shopify_sync_wakeup = asyncio.Event()
    assert request_shopify_sync(request) and request_shopify_sync(request)
    assert state.shopify_sync_wakeup.is_set()
