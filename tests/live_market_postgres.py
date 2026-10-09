"""Network-isolated pricing persistence check; refuses nonlocal/nonempty DBs."""
import asyncio
import os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg

from app.db import _init_connection,user_connection
from app import live_market_refresh as market
from app.ebay_sold_pricing import TrawlApiError
from app.inventory_intelligence import inventory_intelligence
from app import cardmarket_valuations as cardmarket


async def main():
    dsn=os.environ['LIVE_MARKET_TEST_DSN']
    url=urlsplit(dsn)
    assert url.hostname in {'localhost','127.0.0.1'} and url.path=='/live_market_test'
    db=await asyncpg.connect(dsn)
    assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
    await db.execute('''
      create role tcg_api nologin nobypassrls; create role anon; create role authenticated; create role service_role;
      create schema tcg;
      create function tcg.current_user_id() returns uuid language sql stable as
       $$ select nullif(current_setting('tcg.user_id',true),'')::uuid $$;
      create table tcg.owners(id uuid primary key,display_name text,owner_type text,founder_slot int,active boolean,commission_bps int default 0);
      create table tcg.owner_memberships(id uuid,user_id uuid,owner_id uuid,role text,active boolean,created_at timestamptz default now());
      create function tcg.is_platform_admin() returns boolean language sql stable as
       $$select exists(select 1 from tcg.owner_memberships where user_id=tcg.current_user_id() and active and role='PLATFORM_ADMIN')$$;
      create table tcg.catalogue_products(id uuid primary key,product_type text,game text,name text,set_name text,card_number text,variant text,rarity text,language text);
      create table tcg.catalogue_product_profiles(catalogue_id uuid,set_code text,identity_status text);
      create table tcg.sealed_product_details(catalogue_id uuid,identity_status text);
      create table tcg.catalogue_taxonomy_assignments(catalogue_id uuid,value_code text,scope_kind text,dimension_code text,verification_status text,created_at timestamptz);
      create table tcg.inventory_items(id uuid primary key,owner_id uuid,inventory_code text,catalogue_id uuid,version int,status text,identity_confirmed boolean,
       condition text,grading_company text,grade text,language text,seal_status text,store_price_minor bigint,market_value_minor bigint,
       recommended_retail_minor bigint,latest_pricing_snapshot_id uuid,pricing_updated_at timestamptz,updated_at timestamptz);
      create table tcg.pricing_policies(owner_id uuid);
      create table tcg.catalogue_job_runs(id uuid primary key default gen_random_uuid(),job text constraint catalogue_job_runs_job_check
       check(job in ('REFERENCE_PRICES')),actor_user_id uuid,status text,report jsonb,started_at timestamptz default now(),finished_at timestamptz);
      create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,set_id text,name text,card_number text,rarity text);
      create table tcg.reference_sets(provider text,system_code text,language text,set_id text,name text,release_date date);
      create table tcg.reference_market_prices(provider text,system_code text,language text,provider_id text,quotes jsonb);
      create table tcg.provider_catalogue_mappings(catalogue_id uuid,source_provider text,provider_language text,match_status text);
      create table tcg.market_source_mappings(catalogue_id uuid,source text,match_status text);
      create table tcg.pricing_snapshots(id uuid primary key default gen_random_uuid(),inventory_id uuid,catalogue_id uuid,owner_id uuid,
       market_value_minor bigint,recommended_retail_minor bigint,quick_sale_minor bigint,target_acquisition_minor bigint,confidence numeric,
       source_count int,observation_count int,sold_observation_count int,volatility_pct numeric,newest_observation_at timestamptz,algorithm_version text,
       evidence jsonb,auto_publish_eligible boolean,block_reasons jsonb,calculated_at timestamptz default now());
      create table tcg.market_observations(id uuid primary key default gen_random_uuid(),catalogue_id uuid,source text,source_record_key text,
       observation_type text,observed_at timestamptz,price_minor bigint,shipping_minor bigint,currency text,price_gbp_minor bigint,shipping_gbp_minor bigint,
       fx_rate_to_gbp numeric,condition text,grading_company text,grade text,language text,seal_status text,source_country text,sample_size int,evidence_quality numeric,
       metadata jsonb,unique(source,source_record_key));
      create function tcg.audit_market_change() returns trigger language plpgsql as $$begin return new; end$$;
      grant usage on schema tcg to tcg_api; grant select,insert,update on all tables in schema tcg to tcg_api;
      alter table tcg.inventory_items enable row level security;
      create policy owner_access on tcg.inventory_items to tcg_api using(tcg.is_platform_admin() or owner_id=tcg.current_user_id());
      alter table tcg.pricing_snapshots enable row level security;
      create policy owner_access on tcg.pricing_snapshots to tcg_api using(tcg.is_platform_admin() or owner_id=tcg.current_user_id());
    ''')
    root=Path(__file__).parents[1]
    await db.execute((root/'database/migrations/202609230014_market_ingestion_runs.sql').read_text())
    await db.execute((root/'database/migrations/20261009073244_current_ebay_reference_values.sql').read_text())
    await db.execute((root/'database/migrations/20261009184349_independent_catalogue_valuations.sql').read_text())
    await db.execute((root/'database/migrations/20261009193333_cardmarket_valuation_fallback.sql').read_text())
    actor,other,cat,a,b= [uuid4() for _ in range(5)]
    for owner in (actor,other):
        await db.execute("insert into tcg.owners(id,display_name,owner_type,founder_slot,active) values($1,'Fixture','FOUNDER',1,true)",owner)
    await db.execute("insert into tcg.owner_memberships(id,user_id,owner_id,role,active) values($1,$1,$1,'PLATFORM_ADMIN',true)",actor)
    await db.execute("insert into tcg.catalogue_products values($1,'CARD','Pokemon','Seel','Phantasmal Flames','021/094','Normal','Common',null)",cat)
    for ident,owner in ((a,actor),(b,other)):
        await db.execute("""insert into tcg.inventory_items(id,owner_id,inventory_code,catalogue_id,version,status,identity_confirmed,condition,language,store_price_minor)
         values($1::uuid,$2,$1::uuid::text,$3,1,'APPROVED',true,'Near Mint','English',9000)""",ident,owner,cat)
    async def setup(conn): await conn.execute('set role tcg_api')
    pool=await asyncpg.create_pool(dsn,min_size=1,max_size=5,init=_init_connection,setup=setup)
    calls=[]
    class Client:
        def __init__(self,**kwargs): pass
        async def sold(self,**kwargs):
            calls.append(kwargs)
            now=datetime.now(timezone.utc)
            return {'site':'EBAY_GB','currency':'GBP','results':[{'item_id':str(i),'title':'Seel 021/094 Phantasmal Flames NM',
             'sale_price':i+2,'currency':'GBP','condition_raw':'Near Mint','date_sold':(now-timedelta(days=i)).isoformat()} for i in range(1,6)]}
    market.TrawlEbaySoldClient=Client
    settings=SimpleNamespace(ebay_market_refresh_actor_user_id=str(actor),ebay_market_refresh_max_groups=10,trawl_api_key='isolated-fixture')
    try:
        result=await market.refresh_pass(pool,settings)
        assert result['updated']==2 and len(calls)==1
        assert await db.fetchval('select count(*) from tcg.market_observations')==5
        assert await db.fetchval('select count(*) from tcg.pricing_snapshots')==2
        assert await db.fetchval('select bool_and(store_price_minor=9000 and market_value_minor>0) from tcg.inventory_items')
        async with user_connection(pool,actor,'fixture') as conn:
            assert await conn.fetchval('select market_value_minor from tcg.recognition_catalogue_reference_value($1,$2)',cat,'English')>0
        await market.refresh_pass(pool,settings)
        assert len(calls)==1, 'Durable retry clock failed'
        assert await db.fetchval('select count(*) from tcg.pricing_snapshots')==2
        # Refreshing imported benchmarks must not manufacture weekly movement.
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)),state=SimpleNamespace(request_id='fixture-intelligence'))
        user=SimpleNamespace(user_id=actor)
        async def history(owner,algorithm,source,sold,days,value):
            return await db.fetchval("""insert into tcg.pricing_snapshots(inventory_id,catalogue_id,owner_id,algorithm_version,
             evidence,sold_observation_count,market_value_minor,calculated_at)
             values($1,$2,$3,$4,jsonb_build_object('sources',jsonb_build_array(jsonb_build_object('source',$5::text))),$6,$7,
              clock_timestamp()-make_interval(days=>$8)) returning id""",a,cat,owner,algorithm,source,sold,value,days)
        floor=await history(actor,'store-price-floor-v1','EBAY',5,8,9999)
        await history(actor,'collectr-import-provisional-v2-usd-gbp','EBAY',5,8,9999)
        await history(actor,'drop-rate-market-v4','CARDMARKET',5,8,9999)
        await history(actor,'drop-rate-market-v4','EBAY',4,8,9999)
        await history(other,'drop-rate-market-v4','EBAY',5,8,9999)
        report=await inventory_intelligence(request,user,top_limit=5,window_days=7)
        assert report['totals']['active_inventory_count']==1 and report['totals']['market_valued_item_count']==1
        assert not report['weekly_movers']['history_ready']
        assert not report['weekly_movers']['gainers'] and not report['weekly_movers']['decliners']
        await history(actor,'drop-rate-market-v4','EBAY',5,10,100)
        report=await inventory_intelligence(request,user,top_limit=5,window_days=7)
        assert report['weekly_movers']['history_ready']
        assert report['weekly_movers']['gainers'][0]['prior_market_value_minor']==100
        assert not report['weekly_movers']['decliners']
        # Five input sales remain a valid baseline when v4 removes one outlier.
        filtered=await history(actor,'drop-rate-market-v4','EBAY',4,9,200)
        await db.execute("""update tcg.pricing_snapshots set evidence=evidence ||
          '{"method":"LIVE_EBAY_MARKET_V1","comps":[{},{},{},{},{}]}'::jsonb where id=$1""",filtered)
        report=await inventory_intelligence(request,user,top_limit=5,window_days=7)
        assert report['weekly_movers']['gainers'][0]['prior_market_value_minor']==200
        await db.execute('update tcg.inventory_items set latest_pricing_snapshot_id=$1 where id=$2',floor,a)
        report=await inventory_intelligence(request,user,top_limit=5,window_days=7)
        assert not report['weekly_movers']['history_ready'], 'Non-eBay current snapshot became a weekly mover'
        # History survives while clearing the current price; the helper must not resurrect it.
        await db.execute('update tcg.inventory_items set market_value_minor=null')
        async with user_connection(pool,actor,'fixture') as conn:
            assert await conn.fetchval('select market_value_minor from tcg.recognition_catalogue_reference_value($1,$2)',cat,'English') is None
        # Wrong actor cannot invoke the task even though it knows an inventory id.
        settings.ebay_market_refresh_actor_user_id=str(other)
        try:
            await market.refresh_pass(pool,settings)
            raise AssertionError('Unauthorized actor accepted')
        except Exception as exc:
            assert getattr(exc,'status_code',None)==403
        # A concurrent task cannot take the same session lock.
        assert await db.fetchval('select pg_try_advisory_lock($1)',market.LOCK)
        assert (await market.refresh_pass(pool,settings))['status']=='ALREADY_RUNNING'
        await db.execute('select pg_advisory_unlock($1)',market.LOCK)

        # Exact public Cardmarket guides cover an unowned product and the same
        # raw printing, without overwriting a current owner's eBay value.
        await _init_connection(db)
        unowned=uuid4()
        await db.execute("insert into tcg.catalogue_products values($1,'CARD','Pokemon','Absol','Phantasmal Flames','063/094','Normal','Common',null)",unowned)
        await db.execute("insert into tcg.reference_sets values('TCGdex','POKEMON_TCG','English','me02','Phantasmal Flames',current_date-1)")
        now=datetime.now(timezone.utc);observed=now-timedelta(hours=3)
        quote={'source':'TCGDEX_CARDMARKET','finish':'Normal','variant_id':'exact-normal','product_id':'857638',
            'original_currency':'EUR','original_minor':200,'price_gbp_minor':170,'fx_rate_to_gbp':'0.85',
            'source_field':'trend','fx_source':'ECB_EURO_REFERENCE_RATES','observed_at':observed.isoformat(),
            'fx_effective_at':observed.isoformat(),'fx_retrieved_at':now.isoformat()}
        for ident,name,number in [('me02-021','Seel','021/94'),('me02-063','Absol','063/94')]:
            await db.execute("insert into tcg.reference_cards values('TCGdex','POKEMON_TCG','English',$1,'me02',$2,$3,'Common')",ident,name,number)
            await db.execute("insert into tcg.reference_market_prices values('TCGdex','POKEMON_TCG','English',$1,$2::jsonb)",ident,[quote])
        await db.execute('''update tcg.inventory_items i set latest_pricing_snapshot_id=s.id,
          market_value_minor=s.market_value_minor,pricing_updated_at=s.calculated_at from tcg.pricing_snapshots s
          where i.id=$1 and s.inventory_id=i.id and s.algorithm_version='drop-rate-market-v4' and s.sold_observation_count=5''',b)
        b_before=await db.fetchrow('select market_value_minor,latest_pricing_snapshot_id from tcg.inventory_items where id=$1',b)
        result=await cardmarket.refresh_cardmarket_values(pool,actor)
        assert result['catalogue_products_checked']==2 and result['guide_bases']==2
        assert result['inventory_updated']==1 and result['provider_calls']==0
        assert await db.fetchval('select market_value_minor from tcg.inventory_items where id=$1',a)==170
        assert await db.fetchrow('select market_value_minor,latest_pricing_snapshot_id from tcg.inventory_items where id=$1',b)==b_before
        assert await db.fetchval('select bool_and(store_price_minor=9000) from tcg.inventory_items')
        assert await db.fetchval("select count(*) from tcg.market_observations where source='CARDMARKET' and observation_type='PRICE_GUIDE' and language is null and condition is null")==2
        snapshots=await db.fetchval('select count(*) from tcg.pricing_snapshots')
        assert (await cardmarket.refresh_cardmarket_values(pool,actor))['inventory_updated']==0
        assert await db.fetchval('select count(*) from tcg.pricing_snapshots')==snapshots
        assert await db.fetchval('select count(*) from tcg.catalogue_market_snapshots')==2
        # Intake/manual recalculation reuses the saved quote without any request.
        await db.execute('update tcg.inventory_items set market_value_minor=null where id=$1',a)
        async with user_connection(pool,actor,'cached-guide') as conn:
            applied=await cardmarket.apply_cached_inventory_guide(conn,a,actor,cat)
            assert applied['evidence']['method']=='CARDMARKET_GUIDE_V1' and applied['market_value_minor']==170
            count=await conn.fetchval('select count(*) from tcg.pricing_snapshots')
            assert await cardmarket.apply_cached_inventory_guide(conn,a,actor,cat)
            assert await conn.fetchval('select count(*) from tcg.pricing_snapshots')==count
            item=dict((await conn.fetch(cardmarket.INVENTORY_SQL,cat))[0])
            # Select the intended owner copy regardless of random UUID ordering.
            item=next(dict(r) for r in await conn.fetch(cardmarket.INVENTORY_SQL,cat) if r['id']==a)
            guide=await conn.fetchrow("select * from tcg.catalogue_market_snapshots where catalogue_id=$1",cat)
            value={'language':'English','identity_digest':guide['identity_digest'],'snapshot_id':guide['id'],
                'evidence':guide['evidence'],'evidence_checked_at':guide['evidence_checked_at'],
                'result':SimpleNamespace(market_value_minor=170)}
            item.update(version=item['version']-1,current_evidence={})
            try:
                async with conn.transaction():await cardmarket.apply_inventory_guide(conn,item,value,now=now)
                raise AssertionError('Stale inventory version accepted')
            except ValueError:pass
            assert await conn.fetchval('select count(*) from tcg.pricing_snapshots')==count,'Failed update left an orphan snapshot'
        async with user_connection(pool,actor,'guide-fixture') as conn:
            assert await conn.fetchval('select valuation_source from tcg.catalogue_reference_value_v2($1,$2)',unowned,'English')=='CARDMARKET_ESTIMATE'
            assert await conn.fetchval('select market_value_minor from tcg.catalogue_reference_value_v2($1,$2)',unowned,'Japanese') is None
        await db.execute("insert into tcg.market_source_mappings values($1,'CARDMARKET','REVIEW')",unowned)
        async with user_connection(pool,actor,'reviewed-guide') as conn:
            assert await conn.fetchval('select market_value_minor from tcg.catalogue_reference_value_v2($1,$2)',unowned,'English') is None
        assert (await cardmarket.refresh_cardmarket_values(pool,actor))['guide_bases']==1
        await db.execute("update tcg.market_source_mappings set match_status='VERIFIED' where catalogue_id=$1",unowned)
        settings.ebay_market_refresh_actor_user_id=str(actor)
        await market.refresh_pass(pool,settings)
        assert await db.fetchval('select market_value_minor from tcg.inventory_items where id=$1',a)==170,'eBay cleanup erased the authorized guide'
        try:
            await cardmarket.refresh_cardmarket_values(pool,other)
            raise AssertionError('Non-founder ran catalogue/owner writes')
        except Exception as exc:assert getattr(exc,'status_code',None)==403
        async with user_connection(pool,other,'wrong-owner') as conn:
            assert await conn.fetchval('select count(*) from tcg.inventory_items where id=$1',a)==0
            # Earlier weekly-history fixtures deliberately include an old row
            # owned by this actor against another copy. New guide rows must
            # remain isolated; do not confuse that historical fixture with a leak.
            assert await conn.fetchval("select count(*) from tcg.pricing_snapshots where inventory_id=$1 and evidence->>'method'='CARDMARKET_GUIDE_V1'",a)==0
            assert await cardmarket.apply_cached_inventory_guide(conn,a,other,cat) is None
            try:
                async with conn.transaction():await conn.execute('delete from tcg.catalogue_market_snapshots')
                raise AssertionError('API could delete guide history')
            except asyncpg.InsufficientPrivilegeError:pass
        await db.execute("update tcg.catalogue_products set name='Wrong print' where id=$1",unowned)
        async with user_connection(pool,actor,'changed-print') as conn:
            assert await conn.fetchval('select market_value_minor from tcg.catalogue_reference_value_v2($1,$2)',unowned,'English') is None
        assert not await db.fetchval("select has_function_privilege('anon','tcg.catalogue_reference_value_v2(uuid,text)','execute')")
    finally:
        await pool.close(); await db.close()
    print('PASS: eBay and Cardmarket persistence, unowned catalogue guides, source priority, immutable evidence, retries, owner isolation and unchanged Store Prices')


asyncio.run(main())
