import asyncio
import copy
import hashlib
import json
from contextlib import asynccontextmanager

import pytest

from app import catalogue_r2_market as market
from app.object_storage import ObjectStorageError


def fixture():
    table='reference_market_prices'
    row={name:None for name,_ in market.RELATIONS[table]}
    row.update(provider='TCGdex',system_code='POKEMON_TCG',language='English',provider_id='one',
               quotes=[{'source':'SYNTHETIC','price_gbp_minor':123}],market_value_minor=123,refresh_revision=3)
    raw=json.dumps([row]).encode()
    part=dict(relation=table,sha256=hashlib.sha256(raw).hexdigest(),raw_bytes=len(raw),rows=1)
    counts=dict.fromkeys(market.RELATIONS,0);counts[table]=1
    manifest=dict(schema=market.SCHEMA,generation=1,counts=counts,parts=[part],raw_bytes=len(raw))
    return manifest,raw


@pytest.mark.parametrize('change',[
    lambda m:m['counts'].update(reference_market_prices=2),
    lambda m:m['parts'][0].update(sha256='../escape'),
    lambda m:m['parts'][0].update(rows=market.CHUNK_ROWS+1),
    lambda m:m['parts'].append(copy.deepcopy(m['parts'][0])),
    lambda m:m.update(generation=2),lambda m:m.update(raw_bytes=market.MAX_BYTES+1),
])
def test_incomplete_or_corrupt_publications_are_rejected(change):
    manifest,_=fixture();change(manifest)
    with pytest.raises(ObjectStorageError):market.validate_manifest(manifest,1)


@pytest.mark.parametrize('field',['owner_id','inventory_id','store_price_minor','private_notes'])
def test_physical_copy_fields_never_enter_a_market_part(field):
    manifest,raw=fixture();rows=json.loads(raw);rows[0][field]='excluded'
    raw=json.dumps(rows).encode();part=manifest['parts'][0]
    part.update(sha256=hashlib.sha256(raw).hexdigest(),raw_bytes=len(raw))
    with pytest.raises(ObjectStorageError):market.parse_part(raw,part)


def test_bounded_delivery_keeps_identity_expiry_and_ownership_predicates():
    manifest,raw=fixture();snapshot=market.assemble(manifest,[raw])
    entry=dict(provider='TCGdex',system_code='POKEMON_TCG',language='Japanese',provider_id='one')
    query='\nwith static_page as (select 1) select * from tcg.reference_market_prices m where m.expires_at>now() and m.language=$1'
    sql,args=snapshot.sql(query,['Japanese'],[entry])
    assert 'm.expires_at>now() and m.language=$1' in sql
    assert json.loads(args[1])==[] # another language never inherits the quote
    entry['language']='English'
    sql,args=snapshot.sql(query,['English'],[entry])
    assert json.loads(args[1])[0]['market_value_minor']==123
    assert 'from tcg.reference_market_prices' not in sql
    with pytest.raises(ValueError):snapshot.sql(query,[],[entry]*2001)


@pytest.mark.asyncio
async def test_changed_generation_falls_back_immediately(monkeypatch):
    manifest,raw=fixture();snapshot=market.assemble(manifest,[raw])
    monkeypatch.setenv('TCG_R2_MARKET_DELIVERY_ENABLED','true')
    monkeypatch.setattr(market,'_current',snapshot)
    class Connection:
        state=dict(generation=1,published_generation=1,manifest=manifest)
        @asynccontextmanager
        async def transaction(self):yield
        async def fetchrow(self,sql):return self.state
    connection=Connection()
    assert await market.read(connection) is snapshot
    connection.state={**connection.state,'generation':2}
    assert await market.read(connection) is None


@pytest.mark.asyncio
async def test_startup_prewarm_uses_existing_rls_actor_and_never_waits_for_r2(monkeypatch):
    from uuid import uuid4
    manifest, raw = fixture()
    actor = str(uuid4())
    state = dict(generation=1, published_generation=1, manifest=manifest)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    @asynccontextmanager
    async def scoped_connection(pool, user_id, request_id, *, readonly_snapshot=False):
        assert pool == 'existing-api-pool'
        assert user_id == actor
        assert request_id == 'market-startup-prewarm'
        assert readonly_snapshot is True
        calls.append('rls')
        class Connection:
            @asynccontextmanager
            async def transaction(self):
                yield
            async def fetchrow(self, sql):
                assert sql == market.STATE_SQL
                return state
        yield Connection()

    async def slow_r2_download(*args):
        started.set()
        await release.wait()
        return market.assemble(manifest, [raw])

    monkeypatch.setenv('TCG_R2_MARKET_DELIVERY_ENABLED', 'true')
    monkeypatch.setattr(market, '_current', None)
    monkeypatch.setattr(market, '_loading', None)
    monkeypatch.setattr(market, 'user_connection', scoped_connection)
    monkeypatch.setattr(market, 'configured_object_storage', lambda: object())
    monkeypatch.setattr(market, 'download', slow_r2_download)
    assert await market.prewarm('existing-api-pool', actor) is True
    await asyncio.wait_for(started.wait(), 1)
    assert calls == ['rls']
    assert market._current is None, 'Startup must not wait for R2 downloads'
    release.set()
    await market._loading
    assert market._current.generation == 1


@pytest.mark.asyncio
async def test_startup_prewarm_optional_and_fail_open_to_live_sql(monkeypatch):
    monkeypatch.setenv('TCG_R2_MARKET_DELIVERY_ENABLED', 'false')
    async def forbidden_connection(*args, **kwargs):
        raise AssertionError('Disabled cache must not open database connections')
    monkeypatch.setattr(market, 'user_connection', forbidden_connection)
    assert await market.prewarm(object(), 'maintenance-actor') is False
    monkeypatch.setenv('TCG_R2_MARKET_DELIVERY_ENABLED', 'true')
    assert await market.prewarm(object(), None) is False

    @asynccontextmanager
    async def unavailable_connection(*args, **kwargs):
        raise OSError('Network temporarily unavailable')
        yield
    monkeypatch.setattr(market, 'user_connection', unavailable_connection)
    assert await market.prewarm(object(), 'maintenance-actor') is False


def test_api_boot_requests_optional_market_prewarm_without_holding_readiness():
    from pathlib import Path
    main = (Path(__file__).resolve().parents[1] / 'backend/app/main.py').read_text()
    assert "catalogue_r2_market.enabled('DELIVERY')" in main
    assert 'settings.catalogue_maintenance_actor_user_id' in main
    assert 'maintenance_tasks.append(asyncio.create_task(' in main
    assert 'catalogue_r2_market.prewarm(' in main


def test_duplicate_rows_across_verified_parts_are_rejected():
    manifest,raw=fixture()
    other=raw+b' '
    part={**manifest['parts'][0],'sha256':hashlib.sha256(other).hexdigest(),'raw_bytes':len(other)}
    manifest['parts'].append(part);manifest['counts']['reference_market_prices']=2
    manifest['raw_bytes']+=len(other)
    with pytest.raises(ObjectStorageError,match='Duplicate'):market.assemble(manifest,[raw,other])
