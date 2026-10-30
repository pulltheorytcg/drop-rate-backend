import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

import pytest

from app import r2_reference_images as worker
ACTOR=UUID('20000000-0000-0000-0000-000000000001')


class Pool:
    def __init__(self, acquired=True):
        self.acquired=acquired
        self.unlocked=False
    @asynccontextmanager
    async def acquire(self):
        yield self
    async def fetchval(self, sql, *args):
        return self.acquired
    async def execute(self, sql, *args):
        assert 'pg_advisory_unlock' in sql
        self.unlocked=True


def test_worker_requires_both_explicit_gates(monkeypatch):
    monkeypatch.setenv('TCG_R2_REFERENCE_CACHE_WORKER_ENABLED','true')
    monkeypatch.delenv('TCG_R2_REFERENCE_CACHE_APPLY_ENABLED',raising=False)
    assert not worker.worker_enabled()
    monkeypatch.setenv('TCG_R2_REFERENCE_CACHE_APPLY_ENABLED','true')
    assert worker.worker_enabled()


@pytest.mark.asyncio
@pytest.mark.parametrize('acquired,failed,expected_calls,delay',[
    (True,0,1,2),(True,12,1,60),(False,0,0,30)])
async def test_bounded_worker_lock_and_provider_backoff(monkeypatch,acquired,failed,expected_calls,delay):
    pool=Pool(acquired)
    calls=[]
    async def mirror(received,*,limit,request_id):
        assert received.pool is pool and received.actor==ACTOR and limit==20
        calls.append(request_id)
        return dict(examined=20,mirrored=20-failed,failed=failed,skipped=0,remaining_possible=True)
    async def sleep(seconds):
        assert seconds==delay
        raise asyncio.CancelledError
    monkeypatch.setattr(worker,'worker_enabled',lambda:True)
    monkeypatch.setattr(worker,'mirror_reference_images',mirror)
    monkeypatch.setattr(worker.asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_reference_mirror_loop(pool,ACTOR)
    assert len(calls)==expected_calls
    assert pool.unlocked is acquired


@pytest.mark.asyncio
async def test_cancelled_mirror_releases_publication_lock(monkeypatch):
    pool=Pool()
    async def cancel(*args,**kwargs):
        raise asyncio.CancelledError
    monkeypatch.setattr(worker,'worker_enabled',lambda:True)
    monkeypatch.setattr(worker,'mirror_reference_images',cancel)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_reference_mirror_loop(pool,ACTOR)
    assert pool.unlocked


@pytest.mark.asyncio
async def test_every_source_and_receipt_connection_has_existing_admin_context(monkeypatch):
    pool,connection=object(),object()
    active=[]
    @asynccontextmanager
    async def user_connection(received,actor,request_id):
        assert received is pool and actor==ACTOR
        active.append('context')
        try:yield connection
        finally:active.pop()
    async def admin(received):
        assert received is connection and active==['context']
    monkeypatch.setattr(worker,'user_connection',user_connection)
    monkeypatch.setattr(worker,'require_platform_admin',admin)
    wrapped=worker.ReferenceActorPool(pool,ACTOR)
    for _ in range(3):
        async with wrapped.acquire() as received:
            assert received is connection and active==['context']
        assert not active
