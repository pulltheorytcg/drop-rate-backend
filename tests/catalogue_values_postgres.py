"""Real owner-independent catalogue valuation persistence in a disposable DB."""
import asyncio
from datetime import datetime,timedelta,timezone
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID,uuid4

import asyncpg

from app.catalogue_valuations import TARGET_SQL,OBSERVATIONS_SQL,WRITE_SQL,catalogue_values
from app.db import _init_connection


async def main():
    dsn=os.environ['CATALOGUE_VALUES_TEST_DSN'];url=urlsplit(dsn)
    assert url.hostname in {'localhost','127.0.0.1'} and url.path=='/catalogue_values_test'
    db=await asyncpg.connect(dsn);await _init_connection(db)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute('''create schema tcg;create role tcg_api nologin nobypassrls;create role anon;
          create role authenticated;create role service_role;
          create function tcg.current_user_id() returns uuid language sql stable as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          create function tcg.is_platform_admin() returns boolean language sql stable as $$select tcg.current_user_id()='00000000-0000-0000-0000-000000000001'::uuid$$;
          create table tcg.catalogue_products(id uuid primary key,product_type text,game text,name text,set_name text,card_number text,variant text,rarity text,language text);
          create table tcg.catalogue_product_profiles(catalogue_id uuid,set_code text,identity_status text);
          create table tcg.sealed_product_details(catalogue_id uuid,identity_status text);
          create table tcg.catalogue_taxonomy_assignments(catalogue_id uuid,value_code text,scope_kind text,dimension_code text,verification_status text,created_at timestamptz);
          create table tcg.catalogue_job_runs(job text constraint catalogue_job_runs_job_check check(job in ('REFERENCE_PRICES')));
          create table tcg.market_observations(id uuid primary key default gen_random_uuid(),catalogue_id uuid,source text,observation_type text,
            source_country text,currency text,observed_at timestamptz,ingested_at timestamptz,condition text,grading_company text,grade text,language text,
            seal_status text,price_gbp_minor bigint,shipping_gbp_minor bigint,metadata jsonb);
          grant usage on schema tcg to tcg_api;grant select,insert,update on all tables in schema tcg to tcg_api;
        ''')
        await db.execute((Path(__file__).parents[1]/'database/migrations/20261009184349_independent_catalogue_valuations.sql').read_text())
        await db.execute((Path(__file__).parents[1]/'database/migrations/20261009185130_activate_catalogue_reference_values.sql').read_text())
        actor=UUID('00000000-0000-0000-0000-000000000001');cat=uuid4();other=uuid4()
        now=datetime.now(timezone.utc)
        await db.execute("set role tcg_api")
        await db.execute("select set_config('tcg.user_id',$1,false)",str(actor))
        await db.execute("insert into tcg.catalogue_products values($1,'CARD','Pokemon','Seel','Phantasmal Flames','021/094','Normal','Common','English')",cat)
        for n in range(1,6):
            await db.execute('''insert into tcg.market_observations(catalogue_id,source,observation_type,source_country,currency,
              observed_at,ingested_at,condition,language,price_gbp_minor,metadata)
              values($1,'EBAY','SOLD','GB','GBP',$2,$3,'Near Mint','English',$4,$5::jsonb)''',cat,now-timedelta(days=n),now-timedelta(hours=2),n*100,
              {'selection_rule':'FIVE_NEWEST_EXACT_COMPARABLE_SALES','marketplace':'EBAY_GB','provider_item_id':str(n),'title':'Seel 021/094 Phantasmal Flames English NM'})
        product=dict((await db.fetch(TARGET_SQL,None))[0])
        rows=[dict(row) for row in await db.fetch(OBSERVATIONS_SQL,[cat],now-timedelta(days=90),now)]
        value=catalogue_values(product,rows,now=now)[0];result=value['result']
        args=(cat,product['identity_digest'],value['basis_key'],value['condition'],value['language'],None,None,None,
          result.market_value_minor,result.recommended_retail_minor,result.confidence,result.algorithm_version,
          value['oldest_sale_at'],value['evidence_checked_at'],now.date(),value['evidence_digest'],value['evidence'])
        assert await db.fetchval(WRITE_SQL,*args)
        assert await db.fetchval(WRITE_SQL,*args) is None
        assert await db.fetchval('select count(*) from tcg.catalogue_market_snapshots')==1
        assert await db.fetchval("select to_regclass('tcg.inventory_items')") is None,'Test must have no inventory table'
        query='select market_value_minor from tcg.recognition_catalogue_reference_value($1,$2)'
        assert await db.fetchval(query,cat,'English')==result.market_value_minor
        assert await db.fetchval(query,cat,'Japanese') is None
        await db.execute("update tcg.catalogue_products set name='Dewgong' where id=$1",cat)
        assert await db.fetchval(query,cat,'English') is None
        assert await db.fetchval(WRITE_SQL,*args) is None,'Changed identity accepted stale result'
        await db.execute("update tcg.catalogue_products set name='Seel' where id=$1",cat)
        await db.execute("insert into tcg.catalogue_products select $1,product_type,game,name,set_name,card_number,variant,rarity,language from tcg.catalogue_products where id=$2",other,cat)
        old=list(args);old[0]=other;old[13]=now-timedelta(days=8)
        assert await db.fetchval(WRITE_SQL,*old)
        assert await db.fetchval(query,other,'English') is None,'Recalculation revived stale provider evidence'
        await db.execute("select set_config('tcg.user_id',$1,false)",str(uuid4()))
        assert await db.fetchval(query,cat,'English')==result.market_value_minor,'Public catalogue value depended on owner'
        try:
            await db.fetchval(WRITE_SQL,*args)
            raise AssertionError('Non-founder wrote market evidence')
        except asyncpg.InsufficientPrivilegeError:pass
        try:
            await db.execute('delete from tcg.catalogue_market_snapshots')
            raise AssertionError('API deleted immutable market evidence')
        except asyncpg.InsufficientPrivilegeError:pass
        await db.execute("select set_config('tcg.user_id','',false)")
        assert await db.fetchval(query,cat,'English') is None
        assert await db.fetchval('select count(*) from tcg.catalogue_market_snapshots')==0
        await db.execute('reset role')
        assert await db.fetchval("select relforcerowsecurity from pg_class where oid='tcg.catalogue_market_snapshots'::regclass")
        assert not await db.fetchval("select has_function_privilege('anon','tcg.recognition_catalogue_reference_value(uuid,text)','execute')")
    finally:await db.close()
    print('PASS: catalogue valuation with no inventory table, exact identity, language, dates, retries and forced RLS')


asyncio.run(main())
