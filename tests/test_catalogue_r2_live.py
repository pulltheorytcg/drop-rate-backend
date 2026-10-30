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
        return dict(nestloop='on',jit='on') if 'current_setting' in sql else self.state
    async def execute(self,sql,*args):pass
    async def fetch(self,sql,*args):
        self.queries.append(sql)
        if 'live_r2_' in sql:raise RuntimeError('invalid typed data')
        return ['original']


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
