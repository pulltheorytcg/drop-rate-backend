"""Real SQL parity and generation/privilege contracts for whole-catalogue R2.

Native mode follows catalogue_r2_cache_postgres.py in the same disposable DB;
local PGlite starts its own empty database. No production DSN is accepted.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg

from app import catalogue_r2_live as live
from app.catalogue_browser import GAMES_SQL, SETS_SQL, product_query
from app.db import _init_connection
from catalogue_r2_cache_postgres import (PGliteConnection, seed, authorized,
    ACTOR_A, ACTOR_B, OWNER_A, OWNER_B, CANONICAL, PRIVATE)

ROOT=Path(__file__).resolve().parents[1]


class Storage:
    config=SimpleNamespace(prefix='drop-rate')
    def __init__(self):
        self.objects={}
        self.fail=False
    def put_verified_reference_snapshot(self,raw):
        if self.fail:
            raise RuntimeError('synthetic upload failure')
        digest=hashlib.sha256(raw).hexdigest()
        self.objects[digest]=raw
        return dict(verified=True,sha256=digest,
            key=f'drop-rate/catalogue-reference-inputs/{digest}.json.gz')
    def read_verified_reference_snapshot(self,digest):
        return self.objects[digest]


async def check(db):
    print('PostgreSQL engine:',await db.fetchval('select version()'),flush=True)
    if not await db.fetchval("select to_regclass('tcg.reference_cards') is not null"):
        await seed(db)
    await db.execute('''create or replace function tcg.current_access_role() returns text language sql stable as
      $$select role from tcg.owner_memberships where user_id=tcg.current_user_id() and active limit 1$$''')
    await db.execute("update tcg.owner_memberships set role='PLATFORM_ADMIN' where user_id=$1",ACTOR_A)
    # Books and an unreleased identity ensure that full catalogue scope and
    # runtime date predicates survive the storage change.
    await db.execute("""insert into tcg.catalogue_products
      (id,product_type,game,name,set_name,card_number,variant,rarity,language)
      values('30000000-0000-0000-0000-000000000020','COMIC','Manga','Fixture Volume','Fixture Series','1','First','Standard','English'),
      ('30000000-0000-0000-0000-000000000021','COMIC','DC Comics','Future Issue','Future Series','2','First','Standard','English');
      insert into tcg.catalogue_product_profiles(catalogue_id,system_code,collectible_type,set_code,release_date)
      values('30000000-0000-0000-0000-000000000020','MANGA','COMIC','Fixture Series',current_date-1),
      ('30000000-0000-0000-0000-000000000021','DC_COMICS','COMIC','Future Series',current_date+1)""")
    await db.execute((ROOT/'database/migrations/20261030002930_live_catalogue_r2_publication.sql').read_text())
    inventory=await db.fetchval('select jsonb_agg(to_jsonb(i) order by id)::text from tcg.inventory_items i')

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield db
    @asynccontextmanager
    async def user_connection(pool,actor,request_id,readonly_snapshot=False):
        async with db.transaction(isolation='repeatable_read' if readonly_snapshot else None,readonly=readonly_snapshot):
            await db.execute('set local role tcg_api')
            await db.execute("select set_config('tcg.user_id',$1,true)",str(actor))
            yield db
    async def admin(connection):
        assert await connection.fetchval('select tcg.is_platform_admin()'), 'admin required'
        return {'owner_id':OWNER_A}

    storage=Storage()
    with patch.object(live,'user_connection',user_connection),patch.object(live,'require_platform_admin',admin),patch.dict(os.environ,TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED='true'):
        report=await live.publish(Pool(),ACTOR_A,storage=storage)
        assert report['status']=='PUBLISHED'
        snapshot=live._current
        for raw in storage.objects.values():
            assert PRIVATE.encode() not in raw
            for field in ('created_by_user_id','acquisition_cost_minor','store_price_minor','owned_quantity','private_notes','attributes','evidence'):
                assert ('"'+field+'"').encode() not in raw
        assert (await live.publish(Pool(),ACTOR_A,storage=storage))['status']=='CURRENT'
        cases=[{},dict(q='Alpha'),dict(q="' % _"),dict(q='BT1-001'),dict(q='001/100'),
            dict(owned='owned'),dict(owned='not_owned'),dict(product_type='SEALED'),dict(product_type='COMIC'),
            dict(system_code='COMICS'),dict(system_code='MANGA'),dict(language='Japanese'),
            dict(keys=[]),dict(keys=['c:30000000-0000-0000-0000-000000000020']),
            dict(provider='TCGdex',system_code='POKEMON_TCG',language='English',set_id='cache-fixture')]
        for actor,owner in ((ACTOR_A,OWNER_A),(ACTOR_B,OWNER_B)):
            for options in cases:
                for sort in ('name','number','newest','value_desc','value_asc'):
                    query,args=product_query(owner_id=owner,sort=sort,limit=3,offset=0,**options)
                    async with authorized(db,actor):
                        assert await live.read(db) is snapshot
                        original=[dict(r) for r in await db.fetch(query,*args)]
                        sql,params=snapshot.sql(query,args)
                        assert 'from tcg.reference_cards ' not in sql
                        assert 'from tcg.catalogue_products ' not in sql
                        cached=[dict(r) for r in await db.fetch(sql,*params)]
                        assert original==cached,(actor,options,sort,original,cached)
                        if options.get('provider'):
                            sql,params=snapshot.sql(query,args,systems=[options['system_code']],language=options['language'],provider=options['provider'],set_id=options['set_id'])
                            assert original==[dict(r) for r in await db.fetch(sql,*params)]
            for query,args in ((GAMES_SQL,[owner]),(SETS_SQL,[owner,['POKEMON_TCG'],'','',80,0]),(SETS_SQL,[owner,['MANGA'],'','',80,0])):
                async with authorized(db,actor):
                    original=[dict(r) for r in await db.fetch(query,*args)]
                    sql,params=snapshot.sql(query,args)
                    assert original==[dict(r) for r in await db.fetch(sql,*params)]
        # Prices and ownership are intentionally live; neither needs a rebuild.
        await db.execute("update tcg.reference_market_prices set market_value_minor=321 where provider_id='fixture-001'")
        assert (await db.fetchrow(live.STATE_SQL))['generation']==snapshot.generation
        query,args=product_query(owner_id=OWNER_A,sort='name')
        async with authorized(db):
            sql,params=snapshot.sql(query,args)
            assert [dict(r) for r in await db.fetch(query,*args)]==[dict(r) for r in await db.fetch(sql,*params)]
        # Every shared source write invalidates atomically, even unchanged timestamps.
        for table,statement in (
            ('reference_cards',"update tcg.reference_cards set name=name||' changed' where provider_id='fixture-001'"),
            ('reference_sets',"update tcg.reference_sets set declared_card_count=111"),
            ('reference_sealed_products',"update tcg.reference_sealed_products set name=name||' changed'"),
            ('catalogue_products',"update tcg.catalogue_products set name=name||' changed'"),
            ('catalogue_product_profiles',"update tcg.catalogue_product_profiles set release_date=current_date-1")):
            await db.execute('begin')
            await db.execute(statement)
            assert (await db.fetchrow(live.STATE_SQL))['generation']>snapshot.generation,table
            await db.execute('rollback')
            assert (await db.fetchrow(live.STATE_SQL))['generation']==snapshot.generation
        # A nonmember sees no publication, and ordinary members cannot publish.
        async with authorized(db,UUID('20000000-0000-0000-0000-000000000099')):
            assert await db.fetchrow(live.STATE_SQL) is None
            assert await live.read(db) is None
        async with authorized(db,ACTOR_B):
            assert await db.fetchval("select has_table_privilege('tcg_api','tcg_private.live_catalogue_r2_publication','DELETE')") is False
            assert not await db.fetchval("select has_function_privilege('tcg_api','tcg_private.invalidate_live_catalogue_r2()','EXECUTE')")
        async with user_connection(Pool(),ACTOR_B,'test'):
            assert await db.fetchval('update tcg_private.live_catalogue_r2_publication set manifest=null,published_generation=null returning generation') is None
        # Changed source cannot use old snapshots; failed uploads cannot publish.
        await db.execute("update tcg.reference_cards set name=name||' new' where provider_id='fixture-001'")
        async with authorized(db):
            assert await live.read(db) is None
        before=dict(await db.fetchrow(live.STATE_SQL))
        storage.fail=True
        try:
            await live.publish(Pool(),ACTOR_A,storage=storage)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Failed upload published')
        assert dict(await db.fetchrow(live.STATE_SQL))==before
        storage.fail=False
        assert (await live.publish(Pool(),ACTOR_A,storage=storage))['status']=='PUBLISHED'
        # Simulate an update after R2 verification but before the publication CAS.
        original_download=live.download
        async def change_during_download(manifest,store):
            result=await original_download(manifest,store)
            await db.execute('update tcg.reference_sets set declared_card_count=112')
            return result
        await db.execute('update tcg.reference_sets set declared_card_count=113')
        with patch.object(live,'download',change_during_download):
            assert (await live.publish(Pool(),ACTOR_A,storage=storage))['status']=='SOURCE_CHANGED'
        async with authorized(db):
            assert await live.read(db) is None
        assert inventory==await db.fetchval('select jsonb_agg(to_jsonb(i) order by id)::text from tcg.inventory_items i')
    print('PASS: complete catalogue SQL parity for two owners, search/filter/sort, books/sealed, live prices, RLS, atomic invalidation, partial failure, concurrent source change and unchanged inventory')
    # Production-sized joins expose the 100-row JSON cardinality estimate that
    # tiny fixtures cannot. Synthetic records only, in the disposable database.
    await db.execute("""insert into tcg.reference_sets(provider,system_code,language,set_id,name)
      select 'Scale','POKEMON_TCG','English','set-'||n,'Set '||n from generate_series(1,1400) n;
      insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,name,card_number,rarity,image_url,source_url)
      select 'Scale','POKEMON_TCG','English','card-'||n,'set-'||((n-1)/50+1),
        'Card '||n,(n%50)::text,'Common','https://assets.fixture.invalid/cards/card-'||n||'.webp',
        'https://fixture.invalid/cards/printings/card-'||n||'?language=en' from generate_series(1,70000) n;
      insert into tcg.reference_sealed_products(provider,system_code,language,provider_id,set_id,name,product_type)
      select 'Scale','POKEMON_TCG','English','sealed-'||n,'set-'||(n%1400+1),'Box '||n,'Booster Box'
      from generate_series(1,4000) n;
      insert into tcg.catalogue_products(id,product_type,game,name,set_name,card_number,variant,rarity,language)
      select md5(n::text)::uuid,'CARD','Pokemon','Card '||n,'Set '||((n-1)/50+1),
        (n%50)::text,'card-'||n,'Common','English' from generate_series(1,2000) n;
      insert into tcg.catalogue_product_profiles(catalogue_id,system_code,collectible_type)
      select md5(n::text)::uuid,'POKEMON_TCG','CARD' from generate_series(1,2000) n;
      insert into tcg.reference_market_prices(provider,system_code,language,provider_id,
        market_value_minor,market_value_high_minor,pricing_updated_at,quotes)
      select 'Scale','POKEMON_TCG','English','card-'||n,n,n,now(),
        '[{"source":"SYNTHETIC_ONLY"}]'::jsonb from generate_series(1,50000) n;
      analyze;""")
    with patch.object(live,'user_connection',user_connection),patch.object(live,'require_platform_admin',admin):
        report=await live.publish(Pool(),ACTOR_A,storage=Storage())
        assert report['status']=='PUBLISHED',report
        assert report['counts']['reference_cards']>=70000
        assert len(report['query_parity']['cases'])==8
        assert all(case['r2_ms']<15000 and case['equal'] for case in report['query_parity']['cases'])
        settings_sql="select current_setting('enable_nestloop') as nestloop,current_setting('enable_mergejoin') as mergejoin,current_setting('jit') as jit"
        before=await db.fetchrow(settings_sql)
        async with authorized(db):
            await live.fetch_snapshot(db,GAMES_SQL,[OWNER_A],live._current)
            after=await db.fetchrow(settings_sql)
            assert before==after,'planner settings escaped R2 statement'
            try:
                await live.fetch_snapshot(db,GAMES_SQL+' invalid syntax',[OWNER_A],live._current)
            except Exception:
                pass
            else:
                raise AssertionError('synthetic invalid SQL unexpectedly succeeded')
            after=await db.fetchrow(settings_sql)
            assert before==after,'failed R2 statement leaked settings or aborted transaction'
    print('PASS: 70k cards, 4k sealed, 2k canonical and 50k live prices; eight query shapes, bounded runtime and planner restoration')


async def main(pglite):
    if pglite:
        db=await PGliteConnection.open()
    else:
        dsn=os.environ['CATALOGUE_R2_CACHE_TEST_DSN']
        parsed=urlsplit(dsn)
        assert parsed.hostname in ('localhost','127.0.0.1') and parsed.path=='/catalogue_r2_cache_test'
        db=await asyncpg.connect(dsn,server_settings={'statement_timeout':'15000','TimeZone':'UTC'})
        await _init_connection(db)
    try:
        await check(db)
    finally:
        await db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--pglite',action='store_true')
    asyncio.run(main(parser.parse_args().pglite))
