"""The user-facing coverage report is shared, short-lived and single-flight."""
import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app import catalogue_coverage as coverage


@pytest.mark.asyncio
async def test_shared_coverage_reuses_result_until_ttl_then_rechecks():
    now = [100.0]
    cache = coverage.SharedCoverageCache(ttl_seconds=120, clock=lambda: now[0])
    queries = 0

    async def load():
        nonlocal queries
        queries += 1
        return {'prices': queries}

    first = await cache.get(load)
    assert first == {'prices': 1}
    assert await cache.get(load) is first
    assert queries == 1
    now[0] += 119
    assert await cache.get(load) is first
    now[0] += 1
    assert await cache.get(load) == {'prices': 2}
    assert queries == 2


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_query_even_after_request_cancel():
    cache = coverage.SharedCoverageCache()
    started = asyncio.Event()
    release = asyncio.Event()
    queries = 0

    async def load():
        nonlocal queries
        queries += 1
        started.set()
        await release.wait()
        return {'shared': True}

    first = asyncio.create_task(cache.get(load))
    await asyncio.wait_for(started.wait(), 1)
    second = asyncio.create_task(cache.get(load))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await asyncio.wait_for(second, 1) == {'shared': True}
    assert queries == 1
    assert await cache.get(load) == {'shared': True}


@pytest.mark.asyncio
async def test_failed_refresh_is_not_cached():
    cache = coverage.SharedCoverageCache()
    queries = 0

    async def load():
        nonlocal queries
        queries += 1
        if queries == 1:
            raise RuntimeError('database unavailable')
        return 42

    with pytest.raises(RuntimeError, match='database unavailable'):
        await cache.get(load)
    assert await cache.get(load) == 42
    assert queries == 2


@pytest.mark.asyncio
async def test_global_coverage_response_keeps_shape_and_never_reads_inventory(monkeypatch):
    cache = coverage.SharedCoverageCache()
    monkeypatch.setattr(coverage, '_shared_coverage_cache', cache)
    fetched = []

    class Connection:
        async def fetchrow(self, sql):
            assert 'pg_database_size' in sql
            return {'database_bytes': 430000000, 'default_read_only': 'off'}

        async def fetch(self, sql):
            assert sql is coverage.COVERAGE_SQL
            assert 'physical_inventory' not in sql
            fetched.append(sql)
            return [dict(kind='CARD', system_code='POKEMON_TCG', language='English',
                         status='REFERENCE_AVAILABLE', products=2, oldest_check=None,
                         asking_estimates=0, incomplete_references=0)]

    @asynccontextmanager
    async def connection(pool, user_id, request_id):
        assert pool is not None and user_id and request_id
        yield Connection()

    monkeypatch.setattr(coverage, 'user_connection', connection)
    first = await coverage.shared_price_coverage(object(), uuid4(), 'test-a')
    second = await coverage.shared_price_coverage(object(), uuid4(), 'test-b')
    assert second is first
    assert len(fetched) == 1
    assert first['scope'] == 'SQL_REFERENCE_CARDS_AND_SEALED_PRODUCTS'
    assert first['automatic_price_refresh']['status'] == 'PAUSED'
    assert first['catalogue']['stored_physical_tcg_references'] is None
    assert first['items'][0]['products'] == 2
    assert first['summary']['physical_cards']['priced'] == 2
    assert first['total'] == 2

