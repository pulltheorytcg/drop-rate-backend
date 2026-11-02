import asyncio
from contextlib import asynccontextmanager
import copy
import hashlib
import json
from unittest.mock import patch

import pytest

from app import catalogue_r2_live as live
from app.object_storage import ObjectStorageError


def fixture():
    row={key:None for key,_ in live.RELATIONS['reference_cards']}
    row.update(provider='Test',system_code='POKEMON_TCG',language='English',provider_id='one',set_id='set',name='Test')
    raw=json.dumps([row]).encode()
    part=dict(relation='reference_cards',sha256=hashlib.sha256(raw).hexdigest(),raw_bytes=len(raw),rows=1)
    counts=dict.fromkeys(live.RELATIONS,0); counts['reference_cards']=1
    manifest=dict(schema=live.SCHEMA,generation=1,counts=counts,parts=[part],raw_bytes=len(raw))
    return manifest,raw


@pytest.mark.parametrize('change',[
    lambda m:m['counts'].update(reference_cards=2),
    lambda m:m.update(raw_bytes=live.MAX_BYTES+1),
    lambda m:m['parts'][0].update(sha256='../private'),
    lambda m:m['parts'][0].update(rows=live.CHUNK_ROWS+1),
    lambda m:m['parts'].append(copy.deepcopy(m['parts'][0])),
    lambda m:m.update(generation=2),
    lambda m:m.update(private_owner='excluded'),
])
def test_incomplete_wrong_generation_or_unbounded_manifests_are_rejected(change):
    manifest,_=fixture();change(manifest)
    with pytest.raises(ObjectStorageError):live.validate_manifest(manifest,1)


@pytest.mark.parametrize('field',['owner_id','store_price_minor','attributes','evidence'])
def test_even_content_hashed_parts_cannot_add_private_columns(field):
    manifest,raw=fixture()
    rows=json.loads(raw);rows[0][field]='private'
    raw=json.dumps(rows).encode()
    with pytest.raises(ObjectStorageError):
        live.parse_part(raw,'reference_cards',hashlib.sha256(raw).hexdigest(),len(raw),1)


def test_corrupt_or_missing_parts_never_assemble():
    manifest,raw=fixture()
    with pytest.raises(ObjectStorageError):live.assemble(manifest,[raw+b' '])
    with pytest.raises(ValueError):live.assemble(manifest,[])


class Connection:
    def __init__(self,state):self.state=state;self.queries=[];self.rolled_back=False
    @asynccontextmanager
    async def transaction(self):
        try:yield
        except Exception:self.rolled_back=True;raise
    async def fetchrow(self,sql):
        return dict(nestloop='on',mergejoin='on',jit='on') if 'current_setting' in sql else self.state
    async def execute(self,sql,*args):pass
    async def fetch(self,sql,*args):
        self.queries.append(sql)
        if 'live_r2_' in sql:raise RuntimeError('invalid typed data')
        return ['original']


@pytest.mark.asyncio
async def test_failed_live_catalogue_load_backs_off_and_recovers(monkeypatch):
    manifest,raw=fixture()
    connection=Connection(dict(generation=1,published_generation=1,manifest=manifest))
    attempts=[]

    async def missing_part(*_):
        attempts.append('attempt')
        raise ObjectStorageError('synthetic missing R2 part')

    async def repaired_part(*_):
        attempts.append('repaired')
        return live.assemble(manifest,[raw])

    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED','true')
    monkeypatch.setattr(live,'_current',None)
    monkeypatch.setattr(live,'_loading',None)
    monkeypatch.setattr(live,'_load_failure',None)
    monkeypatch.setattr(live,'configured_object_storage',lambda:object())
    monkeypatch.setattr(live,'download',missing_part)

    assert await live.read(connection) is None
    first=live._loading
    await first
    assert attempts==['attempt']
    assert live._load_failure is not None
    assert live._load_failure[0]==(1,live.manifest_digest(manifest))
    for _ in range(8):
        assert await live.read(connection) is None
    assert live._loading is first, 'Do not hammer 161 R2 parts on every browse'
    assert await live.fetch(connection,'select 1',[],None)==['original']

    # An operator repairs the missing part: same generation retries after
    # bounded cooldown, without a fresh deploy or changing SQL source rows.
    monkeypatch.setattr(live,'download',repaired_part)
    monkeypatch.setattr(live,'_load_failure',(live._load_failure[0],0.0))
    assert await live.read(connection) is None
    await live._loading
    assert attempts==['attempt','repaired']
    assert live._load_failure is None
    assert await live.read(connection) is live._current


@pytest.mark.asyncio
async def test_new_live_catalogue_publication_ignores_old_failure_cooldown(monkeypatch):
    manifest,_=fixture()
    connection=Connection(dict(generation=1,published_generation=1,manifest=manifest))
    attempts=[]

    async def unavailable(*_):
        attempts.append('download')
        raise ObjectStorageError('synthetic R2 outage')

    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED','true')
    monkeypatch.setattr(live,'_current',None)
    monkeypatch.setattr(live,'_loading',None)
    monkeypatch.setattr(live,'_load_failure',None)
    monkeypatch.setattr(live,'configured_object_storage',lambda:object())
    monkeypatch.setattr(live,'download',unavailable)
    assert await live.read(connection) is None
    await live._loading
    manifest2={**manifest,'generation':2}
    connection.state=dict(generation=2,published_generation=2,manifest=manifest2)
    assert await live.read(connection) is None
    await live._loading
    assert len(attempts)==2, 'New verified generation must not inherit old cooldown'


@pytest.mark.asyncio
async def test_startup_prewarm_uses_existing_rls_actor_and_never_waits_for_r2(monkeypatch):
    from uuid import uuid4
    manifest, raw = fixture()
    state = dict(generation=1, published_generation=1, manifest=manifest)
    started = asyncio.Event()
    release = asyncio.Event()
    actor = str(uuid4())
    calls = []

    @asynccontextmanager
    async def scoped_connection(pool, user_id, request_id, *, readonly_snapshot=False):
        assert pool == 'existing-api-pool'
        assert user_id == actor
        assert request_id == 'catalogue-startup-prewarm'
        assert readonly_snapshot is True
        calls.append('rls')
        yield Connection(state)

    async def slow_r2_download(*args):
        started.set()
        await release.wait()
        return live.assemble(manifest, [raw])

    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED','true')
    monkeypatch.setattr(live,'_current',None)
    monkeypatch.setattr(live,'_loading',None)
    monkeypatch.setattr(live,'user_connection',scoped_connection)
    monkeypatch.setattr(live,'configured_object_storage',lambda: object())
    monkeypatch.setattr(live,'download',slow_r2_download)
    assert await live.prewarm('existing-api-pool',actor) is True
    await asyncio.wait_for(started.wait(),1)
    assert calls == ['rls']
    assert live._current is None, 'Startup must not wait for R2 downloads'
    release.set()
    await live._loading
    assert live._current.generation == 1
    assert (1,live.datetime.now(live.timezone.utc).date()) in live._browse_cache


@pytest.mark.asyncio
async def test_startup_prewarm_is_optional_and_fails_open_to_authorised_sql(monkeypatch):
    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED','false')
    async def forbidden_connection(*args,**kwargs):
        raise AssertionError('Disabled cache must not open database connections')
    monkeypatch.setattr(live,'user_connection',forbidden_connection)
    assert await live.prewarm(object(),'maintenance-actor') is False
    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED','true')
    assert await live.prewarm(object(),None) is False

    @asynccontextmanager
    async def unavailable_connection(*args,**kwargs):
        raise OSError('Network temporarily unavailable')
        yield
    monkeypatch.setattr(live,'user_connection',unavailable_connection)
    assert await live.prewarm(object(),'maintenance-actor') is False


def test_api_boot_requests_optional_prewarm_without_holding_readiness():
    from pathlib import Path
    main=(Path(__file__).resolve().parents[1]/'backend/app/main.py').read_text()
    assert "catalogue_r2_live.enabled('DELIVERY')" in main
    assert 'settings.catalogue_maintenance_actor_user_id' in main
    assert 'maintenance_tasks.append(asyncio.create_task(' in main
    assert 'catalogue_r2_live.prewarm(' in main


@pytest.mark.asyncio
async def test_full_value_sort_keeps_live_sql_without_a_whole_catalogue_bind():
    from app.catalogue_browser import product_query
    from uuid import uuid4
    query,args=product_query(owner_id=uuid4(),sort='value_desc')
    connection=Connection(None)
    # An object without sql()/rows proves the value path never serializes R2.
    assert await live.fetch(connection,query,args,object())==['original']
    assert connection.queries==[query]


@pytest.mark.asyncio
async def test_cold_read_returns_immediately_and_rechecks_generation_after_download(monkeypatch):
    manifest,raw=fixture()
    state=dict(generation=1,published_generation=1,manifest=manifest)
    connection=Connection(state)
    started=asyncio.Event();release=asyncio.Event()
    async def download(*args):
        started.set();await release.wait();return live.assemble(manifest,[raw])
    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED','true')
    monkeypatch.setattr(live,'_current',None);monkeypatch.setattr(live,'_loading',None)
    monkeypatch.setattr(live,'configured_object_storage',lambda:object())
    monkeypatch.setattr(live,'download',download)
    assert await live.read(connection) is None
    await started.wait()
    first=live._loading
    assert await live.read(connection) is None and live._loading is first
    state['generation']=2
    release.set();await first
    assert await live.read(connection) is None
    state['generation']=1
    assert (await live.read(connection)).generation==1
    assert (1,live.datetime.now(live.timezone.utc).date()) in live._browse_cache


@pytest.mark.asyncio
async def test_system_filtered_value_sort_uses_complete_r2_candidate_set(monkeypatch):
    from datetime import date
    from uuid import uuid4
    from app.catalogue_browser import product_query
    from app.catalogue_r2_browse import build_browse_index
    from test_catalogue_r2_browse import fixture as browse_fixture

    idx=build_browse_index(browse_fixture(),today=date(2026,10,30))
    query,args=product_query(owner_id=uuid4(),sort='value_desc',
                             system_code='ONE_PIECE_CARD_GAME',limit=1)
    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_EXTENDED_BROWSE_ENABLED','true')
    monkeypatch.setattr(live,'browse_for',lambda _:idx)

    class Conn:
        def __init__(self):self.query=None;self.params=None
        @asynccontextmanager
        async def transaction(self):yield
        async def fetchval(self,*args):return False
        async def fetch(self,sql,*params):
            self.query=sql;self.params=params
            return ['bounded']

    connection=Conn()
    assert await live.fetch(connection,query,args,object())==['bounded']
    # Without a verified, current price generation, no price-based
    # shortlist is safe: use full authorised SQL, never stale cached rank.
    assert connection.query == query
    assert connection.params == tuple(args)


@pytest.mark.asyncio
async def test_r2_query_error_rolls_back_savepoint_before_original_query():
    manifest,raw=fixture();snapshot=live.assemble(manifest,[raw]);connection=Connection({})
    query='\nwith reference_base as not materialized (select * from tcg.reference_cards r) select * from reference_base'
    assert await live.fetch(connection,query,[],snapshot)==['original']
    assert connection.rolled_back and len(connection.queries)==2


@pytest.mark.asyncio
async def test_missing_migration_or_manifest_never_prevents_fallback(monkeypatch):
    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED','true')
    connection=Connection(None)
    assert await live.read(connection) is None
    connection.state=dict(generation=1,published_generation=1,manifest={})
    assert await live.read(connection) is None
