"""Real disposable PostgreSQL: shared replica budget, leases and immutable dates."""
import asyncio,json,os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from datetime import datetime,timedelta,timezone
import asyncpg
from app.db import _init_connection,user_connection
from app import regional_catalogue_prices as regional
ROOT=Path(__file__).resolve().parents[1]
async def main():
    dsn=os.environ['REGIONAL_CONTEXT_TEST_DSN'];url=urlsplit(dsn)
    assert url.hostname in ('localhost','127.0.0.1') and url.path=='/regional_context_test'
    admin=await asyncpg.connect(dsn);await _init_connection(admin)
    pools=[]
    try:
        await admin.execute("""create schema tcg;
          create role tcg_api nologin nosuperuser nobypassrls;
          create role anon;create role authenticated;create role service_role;
          create function tcg.current_user_id() returns uuid language sql stable as
          $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          grant usage on schema tcg to tcg_api;
          create table tcg.reference_market_prices(id integer primary key,quotes jsonb,market_value_minor integer,checked_at timestamptz,expires_at timestamptz);
          insert into tcg.reference_market_prices values(1,'[{"original_sold_evidence":true}]',432,'2026-01-01','2026-01-02');
        """)
        original=await admin.fetchval('select row_to_json(p)::text from tcg.reference_market_prices p')
        await admin.execute((ROOT/'database/migrations/20261112120000_regional_catalogue_context.sql').read_text())
        async def init(c):
            await _init_connection(c);await c.execute('set role tcg_api')
        pools=[await asyncpg.create_pool(dsn,min_size=1,max_size=1,init=init) for _ in range(2)]
        actor=uuid4();other=uuid4()
        os.environ['DROP_RATE_REGIONAL_TCGDEX_DAILY_LIMIT']='2'
        regional.display_permissions=lambda:{'TCGDEX_CARDMARKET'}
        ref={'key':'r:'+'a'*32,'set_id':'me02','set_name':'Phantasmal Flames','name':'Charmander','card_number':'011','language':'English'}
        claimed=await asyncio.gather(*(regional._claim(pool,who,'replica',ref) for pool,who in zip(pools,[actor,other])))
        tokens=[r[1] for r in claimed if r[1]]
        assert len(tokens)==1 and sorted(r[2] or '' for r in claimed)==['','REFERENCE_BUSY']
        assert await admin.fetchval("select requests from tcg.reference_regional_provider_budget")==1
        now=datetime.now(timezone.utc)
        row={'source':'TCGDEX_CARDMARKET','original_currency':'EUR','variant_id':'normal','product_id':'123','finish':'Normal','observed_at':now.isoformat(),
            'physical_valuation_eligible':False,'valuation_role':'REGIONAL_CATALOGUE_CONTEXT_ONLY',
            'regional_sale':{'region':'EU','source_field':'avg7','price_gbp_minor':15,'original_minor':20,
                'physical_valuation_eligible':False,'fx_source':'ECB','fx_rate_to_gbp':'.75','fx_effective_at':(now-timedelta(hours=1)).isoformat()}}
        assert await regional._finish(pools[0],actor,'positive',ref,tokens[0],[row])
        cached=await regional._claim(pools[1],other,'other-replica',ref)
        assert cached[0]==[row] and cached[1] is None
        assert await admin.fetchval('select count(*) from tcg.reference_regional_price_history')==1
        assert not await regional._finish(pools[1],other,'duplicate',ref,tokens[0],[row])
        before=await admin.fetchrow('select quotes,checked_at from tcg.reference_regional_price_context')
        # Expire the test context, then simulate a provider 429. Original source
        # dates, quotes and expiry must not be rewritten by the failed attempt.
        await admin.execute("update tcg.reference_regional_price_context set expires_at='2000-01-01'")
        _,token,_=await regional._claim(pools[1],other,'next',ref);assert token
        assert await regional._finish(pools[1],other,'429',ref,token,[],rate_limited=True,backoff=7200)
        after=await admin.fetchrow('select quotes,checked_at,expires_at from tcg.reference_regional_price_context')
        assert before['quotes']==after['quotes'] and before['checked_at']==after['checked_at']
        assert after['expires_at'].year==2000
        ref2=dict(ref,key='r:'+'b'*32)
        assert (await regional._claim(pools[0],actor,'blocked-replica',ref2))[2]=='PROVIDER_BACKOFF'
        assert await admin.fetchval('select requests from tcg.reference_regional_provider_budget')==2
        await admin.execute('update tcg.reference_regional_provider_budget set blocked_until=null')
        assert (await regional._claim(pools[0],actor,'daily-limit',ref2))[2]=='DAILY_LIMIT'
        assert await admin.fetchval('select requests from tcg.reference_regional_provider_budget')==2
        # UTC-day rollover can start a new bounded budget without retries
        # changing any old evidence.
        await admin.execute("update tcg.reference_regional_provider_budget set request_day=current_date-1")
        assert (await regional._claim(pools[1],other,'tomorrow',ref2))[1]
        assert await admin.fetchval('select requests from tcg.reference_regional_provider_budget')==1
        assert await admin.fetchval('select row_to_json(p)::text from tcg.reference_market_prices p')==original
        assert await admin.fetchval('select count(*) from tcg.reference_regional_price_history')==1
        async with pools[0].acquire() as c:
            async with c.transaction():
                await c.execute("select set_config('tcg.user_id','',true)")
                assert await c.fetchval('select count(*) from tcg.reference_regional_price_context')==0
            try:
                async with user_connection(pools[1],other,'forbidden-history-update') as inner:
                    await inner.execute("update tcg.reference_regional_price_history set quotes='[]'")
            except asyncpg.InsufficientPrivilegeError:pass
            else:raise AssertionError('History must be append-only')
        print(json.dumps({'status':'DISPOSABLE_POSTGRES_REGIONAL_CONTEXT_PASSED','replicas':2,
              'shared_cache_or_inventory_writes':0,'history_rows':1,'real_provider_calls':0,
              'concurrent_lease_and_budget_verified':True,'failure_evidence_dates_preserved':True}))
    finally:
        for pool in pools:await pool.close()
        await admin.close()
asyncio.run(main())
