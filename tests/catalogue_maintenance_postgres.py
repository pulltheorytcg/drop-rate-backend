"""Real catalogue query, publication selection and migration/RLS integration.

Refuses remote/nonempty databases. All records are disposable fixtures.
"""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID,uuid4

import asyncpg

from app.catalogue_browser import GAMES_SQL,SETS_SQL,product_query
from app.catalogue_maintenance import SHOPIFY_CANDIDATES
from app.db import _init_connection
from app.reference_sealed import save_sealed_set


async def main():
    dsn=os.environ['CATALOGUE_TEST_DSN'];url=urlsplit(dsn)
    assert url.hostname in {'localhost','127.0.0.1'} and url.path=='/catalogue_test'
    db=await asyncpg.connect(dsn);await _init_connection(db)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute('''create schema tcg;create role tcg_api nologin nobypassrls;create role anon;create role authenticated;
          create function tcg.current_user_id() returns uuid language sql stable as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          create function tcg.is_platform_admin() returns boolean language sql stable as $$select tcg.current_user_id()='00000000-0000-0000-0000-000000000001'::uuid$$;
          create table tcg.collectible_systems(code text primary key);
          insert into tcg.collectible_systems values('POKEMON_TCG');
          create table tcg.reference_sets(provider text,system_code text,language text,set_id text,name text,release_date date,
            declared_card_count int,source_url text,refreshed_at timestamptz,primary key(provider,system_code,language,set_id));
          create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,set_id text,name text,
            card_number text,number_key text,finish text,rarity text,image_url text,source_url text,evidence jsonb,refreshed_at timestamptz,
            primary key(provider,system_code,language,provider_id));
          create table tcg.provider_catalogue_mappings(source_provider text,system_code text,provider_language text,provider_id text,
            catalogue_id uuid,provider_entity_type text,provider_variant_key text,match_status text);
          create table tcg.catalogue_products(id uuid,product_type text,game text,name text,set_name text,card_number text,variant text,rarity text,language text);
          create table tcg.catalogue_product_profiles(catalogue_id uuid,system_code text,set_code text,release_date date,collectible_type text);
          create table tcg.inventory_items(id uuid,owner_id uuid,catalogue_id uuid,status text,sale_intent text,version int,market_value_minor bigint,updated_at timestamptz default now());
          create table tcg.owners(id uuid,active boolean);
          create table tcg.shopify_inventory_links(id uuid,inventory_id uuid,test_mode boolean,sync_state text);
          create table tcg.reference_market_prices(provider text,system_code text,language text,provider_id text,market_value_minor bigint,
            market_value_high_minor bigint,pricing_updated_at timestamptz,quotes jsonb,expires_at timestamptz);
          create table tcg.media_assets(catalogue_id uuid,shopify_cdn_url text,public_source_url text,scope text,side text,media_kind text,
            approval_status text,rights_status text,rights_tier text,source_status text,revoked_at timestamptz,approved_at timestamptz,created_at timestamptz,id uuid);
          create function tcg.recognition_catalogue_reference_value(uuid,text) returns table(market_value_minor bigint,basis_condition text,pricing_updated_at timestamptz)
            language sql stable as $$select null::bigint,null::text,null::timestamptz where false$$;
          grant usage on schema tcg to tcg_api;grant select,insert,update on all tables in schema tcg to tcg_api;
        ''')
        await db.execute((Path(__file__).parents[1]/'database/migrations/20261009144903_catalogue_daily_maintenance.sql').read_text())
        actor=UUID('00000000-0000-0000-0000-000000000001');owner=uuid4()
        await db.execute("set role tcg_api")
        await db.execute("select set_config('tcg.user_id',$1,false)",str(actor))
        record=dict(provider='CardTrader',system_code='POKEMON_TCG',language='Unknown',set_id='10',name='Set',source_url='https://api.cardtrader.com/fixture')
        product=dict(record,provider_id='12',name='Booster box',product_type='BOOSTER_BOX',image_url='https://cardtrader.com/uploads/blueprints/image/12/box.jpg',evidence={'retrieval_only':True})
        await save_sealed_set(db,record,[product]);await save_sealed_set(db,record,[product])
        assert await db.fetchval('select count(*) from tcg.reference_sealed_products')==1
        assert await db.fetchval('select count(*) from tcg.catalogue_products')==0
        sql,args=product_query(owner_id=owner,product_type='SEALED')
        rows=await db.fetch(sql,*args)
        assert len(rows)==1 and rows[0]['key'].startswith('s:') and rows[0]['source_kind']=='SEALED_REFERENCE'
        assert rows[0]['owned_quantity']==0 and rows[0]['market_value_minor'] is None
        sql,args=product_query(owner_id=owner,product_type='CARD');assert not await db.fetch(sql,*args)
        sql,args=product_query(owner_id=owner,product_type='SEALED',language='English');assert not await db.fetch(sql,*args)
        sets=await db.fetch(SETS_SQL,owner,['POKEMON_TCG'],'Unknown','',41,0)
        assert len(sets)==1 and sets[0]['image_url']==product['image_url'] and sets[0]['indexed_count']==1
        assert (await db.fetch(GAMES_SQL,owner))[0]['products']==1
        await db.execute("insert into tcg.owners values($1,true)",owner)
        ids=[uuid4() for _ in range(6)]
        for i,(status,intent) in enumerate([('APPROVED','FOR_SALE'),('DRAFT','FOR_SALE'),('APPROVED','PERSONAL_COLLECTION'),('SOLD','FOR_SALE'),('APPROVED','FOR_SALE'),('APPROVED','FOR_SALE')]):
            await db.execute('insert into tcg.inventory_items(id,owner_id,status,sale_intent,version) values($1,$2,$3,$4,1)',ids[i],owner,status,intent)
        await db.execute("insert into tcg.shopify_inventory_links values($1,$2,false,'PUBLISHED'),($3,$4,true,'DRAFT')",uuid4(),ids[4],uuid4(),ids[5])
        assert [r['id'] for r in await db.fetch(SHOPIFY_CANDIDATES)]==[ids[0]]
        await db.execute("insert into tcg.catalogue_job_runs(job,actor_user_id,status,report) values('SHOPIFY_SYNC',$1,'INCOMPLETE',$2::jsonb)",actor,{'inventory_id':str(ids[0]),'version':1})
        assert not await db.fetch(SHOPIFY_CANDIDATES),'Blocked version did not back off'
        await db.execute('update tcg.inventory_items set version=2 where id=$1',ids[0])
        assert len(await db.fetch(SHOPIFY_CANDIDATES))==1,'Corrected inventory was not retried'
        await db.execute("select set_config('tcg.user_id',$1,false)",str(owner))
        assert await db.fetchval('select count(*) from tcg.reference_sealed_products')==1
        assert await db.fetchval('select count(*) from tcg.catalogue_job_runs')==0
        try:
            await db.execute("insert into tcg.catalogue_job_runs(job,actor_user_id,status) values('SHOPIFY_SYNC',$1,'RUNNING')",owner)
            raise AssertionError('Non-admin created an operational receipt')
        except asyncpg.InsufficientPrivilegeError:pass
        await db.execute("select set_config('tcg.user_id','',false)")
        assert await db.fetchval('select count(*) from tcg.reference_sealed_products')==0
    finally:await db.close()
    print('PASS: real sealed query, replay, set previews, publication gating/backoff, migration and RLS')


asyncio.run(main())
