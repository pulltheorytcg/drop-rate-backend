"""Cold Railway workers must not mistake competing verified reads for bad R2 data."""
import asyncio
from contextlib import asynccontextmanager
import threading
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app import catalogue_r2_cache as cache, catalogue_r2_live as live, catalogue_r2_market as market
from test_catalogue_r2_live import fixture as live_fixture
from test_catalogue_r2_market import fixture as market_fixture


@pytest.mark.asyncio
async def test_parallel_catalogue_and_market_downloads_wait_for_shared_read_capacity(monkeypatch):
    catalogue_manifest, catalogue_raw = live_fixture()
    market_manifest, market_raw = market_fixture()
    catalogue_sha = catalogue_manifest['parts'][0]['sha256']
    market_sha = market_manifest['parts'][0]['sha256']
    assert catalogue_sha != market_sha
    objects = {catalogue_sha: catalogue_raw, market_sha: market_raw}
    first_started, release_first = threading.Event(), threading.Event()
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(cache, '_read_slots', slots)

    class Storage:
        def read_verified_reference_snapshot(self, digest):
            if digest == catalogue_sha:
                first_started.set()
                assert release_first.wait(2), 'Fixture must release the occupied read'
            return objects[digest]

    storage = Storage()
    first = asyncio.create_task(live.download(catalogue_manifest, storage))
    try:
        for _ in range(100):
            if first_started.is_set():
                break
            await asyncio.sleep(0.01)
        assert first_started.is_set()
        second = asyncio.create_task(market.download(market_manifest, storage))
        await asyncio.sleep(0.08)
        assert not second.done(), 'A full-market load must wait instead of failing fast'
    finally:
        release_first.set()
    catalogue = await asyncio.wait_for(first, 5)
    for _ in range(100):
        if second.done():
            break
        await asyncio.sleep(0.05)
    assert second.done(), 'The queued market read did not complete after capacity freed'
    prices = await second
    assert catalogue.generation == prices.generation == 1
    assert len(catalogue.rows['reference_cards']) == 1
    assert len(prices.rows['reference_market_prices']) == 1
    assert slots.acquire(blocking=False), 'All real read threads released capacity'
    slots.release()


@pytest.mark.asyncio
@pytest.mark.parametrize('module,fixture', [(live, live_fixture), (market, market_fixture)])
async def test_published_generation_skips_redundant_startup_publication_download(
    monkeypatch, module, fixture,
):
    manifest, _ = fixture()
    state = dict(generation=1, published_generation=1, manifest=manifest)
    calls = []

    class Connection:
        async def fetchval(self, sql, *args):
            assert 'pg_try_advisory_lock' in sql
            return True

        async def fetchrow(self, sql):
            calls.append('state')
            return state

        async def execute(self, sql, *args):
            assert 'pg_advisory_unlock' in sql
            calls.append('unlock')

    connection = Connection()

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield connection

    @asynccontextmanager
    async def scoped_connection(pool, actor, request_id, readonly_snapshot=False):
        assert readonly_snapshot and pool.__class__ is Pool
        yield connection

    async def forbidden_download(*args):
        raise AssertionError('An already-published generation must not download again')

    monkeypatch.setattr(module, '_current', None)
    monkeypatch.setattr(module, 'user_connection', scoped_connection)
    monkeypatch.setattr(module, 'require_platform_admin', AsyncMock())
    monkeypatch.setattr(module, 'download', forbidden_download)
    result = await module.publish(Pool(), uuid4(), storage=object())
    assert result == {'status': 'CURRENT', 'generation': 1, 'counts': manifest['counts']}
    assert calls == ['state', 'unlock']
