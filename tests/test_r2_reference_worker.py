import asyncio
import json
from contextlib import asynccontextmanager
from uuid import UUID

import pytest

from app import r2_reference_images as worker
from app.database_capacity import CAPACITY_SQL
ACTOR=UUID('20000000-0000-0000-0000-000000000001')


class Pool:
    def __init__(self, acquired=True, database_bytes=378_000_000, read_only='off'):
        self.acquired=acquired
        self.unlocked=False
        self.database_bytes=database_bytes
        self.read_only=read_only
        self.capacity_checks=0
    @asynccontextmanager
    async def acquire(self):
        yield self
    async def fetchval(self, sql, *args):
        return self.acquired
    async def fetchrow(self, sql):
        assert sql==CAPACITY_SQL
        self.capacity_checks+=1
        return {'database_bytes':self.database_bytes,'default_read_only':self.read_only}
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
    assert pool.capacity_checks==int(acquired)


@pytest.mark.asyncio
@pytest.mark.parametrize('database_bytes,read_only,reason',[
    (400_000_000,'off','BULK_REFRESH_DEFERRED_CAPACITY'),
    (450_000_000,'off','FREE_DATABASE_CAPACITY_URGENT'),
    (378_000_000,'on','DATABASE_READ_ONLY'),
])
async def test_worker_defers_remote_work_until_capacity_recovers(monkeypatch,caplog,database_bytes,read_only,reason):
    pool=Pool(database_bytes=database_bytes,read_only=read_only)
    calls=[]
    pauses=[]
    async def mirror(*args,**kwargs):
        assert pool.capacity_checks==2
        assert pauses==[300]
        calls.append(kwargs['limit'])
        return dict(examined=20,mirrored=20,failed=0,skipped=0,remaining_possible=True)
    async def sleep(seconds):
        assert pool.unlocked
        pauses.append(seconds)
        if len(pauses)==1:
            assert seconds==300 and not calls
            pool.database_bytes=399_999_999
            pool.read_only='off'
            pool.unlocked=False
        else:
            raise asyncio.CancelledError
    monkeypatch.setattr(worker,'worker_enabled',lambda:True)
    monkeypatch.setattr(worker,'mirror_reference_images',mirror)
    monkeypatch.setattr(worker.asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_reference_mirror_loop(pool,ACTOR)
    assert pauses==[300,2] and calls==[20] and pool.unlocked
    deferred=next(r.message for r in caplog.records if 'MEDIA_DEFERRED' in r.message)
    evidence=json.loads(deferred.split(' ',1)[1])
    assert evidence['reason']==reason and evidence['database_bytes']==database_bytes
    batch=next(r.message for r in caplog.records if 'MEDIA_BATCH' in r.message)
    assert json.loads(batch.split(' ',1)[1])['database_bytes']==399_999_999


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['missing','malformed','unavailable'])
async def test_worker_fails_closed_when_capacity_cannot_be_verified(monkeypatch,failure):
    pool=Pool()
    async def fetchrow(sql):
        if failure=='unavailable':
            raise RuntimeError('database unavailable')
        return None if failure=='missing' else {'database_bytes':None,'default_read_only':'off'}
    async def mirror(*args,**kwargs):
        pytest.fail('No provider requests or uploads before capacity is verified')
    async def sleep(seconds):
        assert seconds==60 and pool.unlocked
        raise asyncio.CancelledError
    monkeypatch.setattr(pool,'fetchrow',fetchrow)
    monkeypatch.setattr(worker,'worker_enabled',lambda:True)
    monkeypatch.setattr(worker,'mirror_reference_images',mirror)
    monkeypatch.setattr(worker.asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_reference_mirror_loop(pool,ACTOR)


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
