"""Real SQL parity, invalidation and publication failures; disposable DB only."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import asyncpg

from app import catalogue_r2_market as market, catalogue_r2_live as live
from app.catalogue_browser import product_query
from app.catalogue_r2_browse import build_browse_index, indexed_catalogue_query
from app.catalogue_r2_navigation import owned_navigation
from app.db import _init_connection
from app import r2_reference_images as images
from catalogue_r2_cache_postgres import PGliteConnection,seed,authorized,ACTOR_A,ACTOR_B,OWNER_A,OWNER_B,PRIVATE
from catalogue_r2_live_postgres import Storage

ROOT=Path(__file__).resolve().parents[1]


async def check(db):
    if not await db.fetchval("select to_regclass('tcg.reference_cards') is not null"):
        await seed(db)
    await db.execute('''create or replace function tcg.current_access_role() returns text language sql stable as
      $$select role from tcg.owner_memberships where user_id=tcg.current_user_id() and active limit 1$$;
      alter table tcg.reference_sealed_market_prices add column if not exists checked_at timestamptz;
      alter table tcg.reference_sealed_market_prices add column if not exists expires_at timestamptz;''')
    fields=','.join(f'{n} {kind}' for n,kind in market.RELATIONS['reference_asking_prices'])
    await db.execute(f'create table tcg.reference_asking_prices({fields},primary key(provider,system_code,language,provider_id)); grant select on tcg.reference_asking_prices to tcg_api')
    await db.execute("update tcg.owner_memberships set role='PLATFORM_ADMIN' where user_id=$1",ACTOR_A)
    await db.execute((ROOT/'database/migrations/20261030141054_r2_live_market_data.sql').read_text())
    inventory=await db.fetchval('select jsonb_agg(to_jsonb(i) order by id)::text from tcg.inventory_items i')
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield db
    @asynccontextmanager
    async def user_connection(pool,actor,request_id,readonly_snapshot=False):
        async with db.transaction(isolation='repeatable_read' if readonly_snapshot else None,readonly=readonly_snapshot):
            await db.execute('set local role tcg_api')
            await db.execute("select set_config('tcg.user_id',$1,true)",str(actor))
            yield db
    async def admin(connection):
        assert await connection.fetchval('select tcg.is_platform_admin()')
    storage=Storage()
    with patch.object(market,'user_connection',user_connection),patch.object(market,'require_platform_admin',admin),patch.dict(os.environ,TCG_R2_MARKET_DELIVERY_ENABLED='true'):
        result=await market.publish(Pool(),ACTOR_A,storage=storage)
        assert result['status']=='PUBLISHED',result
        snapshot=market._current
        assert result['counts']['reference_market_prices']==await db.fetchval('select count(*) from tcg.reference_market_prices')
        assert all(PRIVATE.encode() not in raw for raw in storage.objects.values())
        # Use the complete R2 identity index, including the 70k-card CI fixture.
        rows={}
        for table in live.RELATIONS:
            rows[table]=[]
            offset=0
            while True:
                part=json.loads(await db.fetchval(live.chunk_sql(table),live.CHUNK_ROWS,offset))
                rows[table].extend(part);offset+=len(part)
                if len(part)<live.CHUNK_ROWS:break
        verified=[dict(r) for r in await db.fetch("select catalogue_id::text,source_provider,system_code,provider_language,provider_id,provider_entity_type,provider_variant_key,match_status from tcg.provider_catalogue_mappings where match_status='VERIFIED'")]
        index=build_browse_index(rows,verified_mappings=verified)
        for actor,owner in ((ACTOR_A,OWNER_A),(ACTOR_B,OWNER_B)):
            async with authorized(db,actor):
                assert await market.read(db) is snapshot
                owned=await owned_navigation(db,owner)
                for options in ({},{'q':'Alpha'},{'product_type':'SEALED'},{'product_type':'COMIC'},{'owned':'owned'}):
                    query,args=product_query(owner_id=owner,limit=9,**options)
                    original=[dict(r) for r in await db.fetch(query,*args)]
                    sql,params,_=indexed_catalogue_query(query,args,index,owned=owned,market=snapshot)
                    assert 'tcg.reference_market_prices' not in sql
                    actual=[dict(r) for r in await db.fetch(sql,*params)]
                    assert original==actual,(actor,options,original,actual)
        generation=snapshot.generation
        await db.execute('update tcg.reference_market_prices set checked_at=checked_at')
        assert (await db.fetchrow(market.STATE_SQL))['generation']==generation
        await db.execute("update tcg.reference_market_prices set market_value_minor=market_value_minor+1 where provider_id='fixture-001'")
        assert (await db.fetchrow(market.STATE_SQL))['generation']>generation
        async with authorized(db,ACTOR_A):assert await market.read(db) is None
        before=dict(await db.fetchrow(market.STATE_SQL))
        storage.fail=True
        try:await market.publish(Pool(),ACTOR_A,storage=storage)
        except RuntimeError:pass
        else:raise AssertionError('failed upload published')
        assert dict(await db.fetchrow(market.STATE_SQL))==before
        storage.fail=False
        original_download=market.download
        async def changed(manifest,storage):
            candidate=await original_download(manifest,storage)
            await db.execute("update tcg.reference_market_prices set checked_at=clock_timestamp() where provider_id='fixture-001'")
            return candidate
        with patch.object(market,'download',changed):
            assert (await market.publish(Pool(),ACTOR_A,storage=storage))['status']=='SOURCE_CHANGED'
        assert (await market.publish(Pool(),ACTOR_A,storage=storage))['status']=='PUBLISHED'
        async with authorized(db,None):assert await market.read(db) is None
        async with user_connection(Pool(),ACTOR_B,'non-admin'):
            assert await db.fetchval('update tcg_private.live_catalogue_r2_market_publication set manifest=null,published_generation=null returning generation') is None
            assert not await db.fetchval("select has_function_privilege('tcg_api','tcg_private.invalidate_live_catalogue_r2_market()','EXECUTE')")
        # Every independent price source invalidates atomically, including an
        # empty asking cache gaining its first row; rolled-back writes do not.
        current=(await db.fetchrow(market.STATE_SQL))['generation']
        for table in market.RELATIONS:
            try:
                async with db.transaction():
                    await db.execute(f'truncate tcg.{table}')
                    assert (await db.fetchrow(market.STATE_SQL))['generation']==current+1
                    await db.execute(f"insert into tcg.{table}(provider,system_code,language,provider_id) values('Test','POKEMON_TCG','English','one')")
                    assert (await db.fetchrow(market.STATE_SQL))['generation']==current+2
                    await db.execute(f"delete from tcg.{table} where provider='Test'")
                    assert (await db.fetchrow(market.STATE_SQL))['generation']==current+3
                    raise RuntimeError('rollback test')
            except RuntimeError:pass
            assert (await db.fetchrow(market.STATE_SQL))['generation']==current
        assert inventory==await db.fetchval('select jsonb_agg(to_jsonb(i) order by id)::text from tcg.inventory_items i')
    print('PASS: R2 market bytes/counts, two-owner page parity, expiry/identity rules, source changes, failed upload, RLS and unchanged inventory',flush=True)
    # Exercise actual image RLS with the worker's authenticated connection
    # wrapper, not a superuser source read or a mocked empty candidate list.
    await db.execute('alter table tcg.reference_image_mirrors rename to reference_image_mirrors_empty_fixture')
    await db.execute((ROOT/'database/migrations/20261025232125_r2_reference_image_cache.sql').read_text())
    await db.execute((ROOT/'database/migrations/20261030141056_r2_remaining_reference_artwork_hosts.sql').read_text())
    await db.execute(next((ROOT/'database/migrations').glob('*_r2_cardtrader_image_filenames.sql')).read_text())
    for provider,system,url in (
        ('Naruto Card Game Archive','NARUTO_KAYOU','https://narutocardgame.gg/images/kayou/SP-001.webp'),
        ('Naruto Card Game Archive','NARUTO_BANDAI_LEGACY','https://narutocardgame.gg/images/classic/j387.jpg'),
        ('TCGdex','POKEMON_TCG','https://cardtrader.com/uploads/blueprints/image/123/preview_one(2).jpg')):
        await db.execute('''insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,name,image_url)
          values($1,$2,'English','r2-art-test','fixture','Fixture',$3)''',provider,system,url)
        item=dict(provider=provider,system_code=system,language='English',provider_id='r2-art-test',image_url=url)
        assert images.accepted_reference_url(url,provider,system)
        with patch.object(images,'user_connection',user_connection),patch.object(images,'require_platform_admin',admin):
            async with images.ReferenceActorPool(Pool(),ACTOR_A).acquire() as connection:
                candidates=await connection.fetch(images.PENDING_REFERENCE_IMAGES_SQL,20)
                assert any(r['image_url']==url for r in candidates)
                saved=await connection.fetchval(images.RECORD_REFERENCE_IMAGE_SQL,
                    *(item[k] for k in ('provider','system_code','language','provider_id','image_url')),
                    'drop-rate/private-media/'+'a'*64+'.webp','a'*64,123)
                assert saved=='r2-art-test'
                stale=await connection.fetchval(images.RECORD_REFERENCE_IMAGE_SQL,
                    provider,system,'English','r2-art-test',url+'?changed',
                    'drop-rate/private-media/'+'b'*64+'.webp','b'*64,123)
                assert stale is None
    async with authorized(db,None):
        assert not await db.fetch(images.PENDING_REFERENCE_IMAGES_SQL,20)
    print('PASS: authenticated reference worker and exact-source Naruto/CardTrader RLS receipts',flush=True)


async def main(pglite):
    if pglite:db=await PGliteConnection.open()
    else:
        dsn=os.environ['CATALOGUE_R2_CACHE_TEST_DSN'];parsed=urlsplit(dsn)
        assert parsed.hostname in ('localhost','127.0.0.1') and parsed.path=='/catalogue_r2_cache_test'
        db=await asyncpg.connect(dsn,server_settings={'statement_timeout':'15000','TimeZone':'UTC'})
        await _init_connection(db)
    try:await check(db)
    finally:await db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pglite',action='store_true')
    asyncio.run(main(parser.parse_args().pglite))
