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


def test_duplicate_rows_across_verified_parts_are_rejected():
    manifest,raw=fixture()
    other=raw+b' '
    part={**manifest['parts'][0],'sha256':hashlib.sha256(other).hexdigest(),'raw_bytes':len(other)}
    manifest['parts'].append(part);manifest['counts']['reference_market_prices']=2
    manifest['raw_bytes']+=len(other)
    with pytest.raises(ObjectStorageError,match='Duplicate'):market.assemble(manifest,[raw,other])
