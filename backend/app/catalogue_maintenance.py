"""Daily reference imports and bounded Shopify reconciliation in the existing API.

Provider calls never approve identities/media or change an owner's selling price.
Durable receipts and advisory locks survive restarts and overlapping deployments.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .access_control import require_platform_admin
from .cardtrader_client import CardTraderClient
from .db import user_connection
from .fx import EcbHistoricalFxProvider
from .reference_feeds import ReferenceFeeds
from .reference_library import save_reference_set
from .reference_market import REVISION, refresh_reference_prices
from .one_piece_market import refresh_one_piece_prices
from .dragon_ball_market import refresh_dragon_ball_prices
from .pokemon_catalogue_market import refresh_pokemon_catalogue_prices
from .reference_sealed import save_sealed_set, sealed_feed
from .sealed_market import REVISION as SEALED_MARKET_REVISION, refresh_sealed_prices
from .catalogue_coverage import record_coverage
from .cardmarket_valuations import refresh_cardmarket_values, REVISION as CARDMARKET_VALUE_REVISION
from .catalogue_valuations import REVISION as CATALOGUE_VALUE_REVISION, refresh_catalogue_values
from .shopify_pipeline import publish_inventory_to_shopify, reconcile_shopify_product_prices

log=logging.getLogger(__name__)
SOURCES=('cardtrader_sealed','tcgdex','punk','one_piece_official','dragon_ball_masters','dragon_ball_fusion','naruto_kayou','naruto_bandai')
SOURCE_REVISIONS={'cardtrader_sealed':4,'one_piece_official':2,'punk':2}
REFERENCE_JOB_REVISION=5
SHOPIFY_CANDIDATES="""
select i.id,i.owner_id,i.version from tcg.inventory_items i
join tcg.owners o on o.id=i.owner_id and o.active
left join tcg.shopify_inventory_links l on l.inventory_id=i.id
where i.status='APPROVED' and i.sale_intent='FOR_SALE'
 and (l.id is null or (l.test_mode=false and l.sync_state in ('DRAFT','ERROR')))
 and not exists(select 1 from tcg.catalogue_job_runs r
   where r.job='SHOPIFY_SYNC' and r.report->>'inventory_id'=i.id::text
     and r.report->>'version'=i.version::text
     and r.started_at>now()-case when r.status in ('RUNNING','FAILED') then interval '15 minutes' else interval '6 hours' end)
order by i.updated_at,i.id limit 10
"""


def daily_slot(now):
    local=now.astimezone(ZoneInfo('Europe/London'))
    slot=local.replace(hour=3,minute=0,second=0,microsecond=0)
    if local<slot:slot-=timedelta(days=1)
    return slot.astimezone(timezone.utc)


def due(run,now,*,revision=None):
    if run is None:return True
    if revision is not None and (run.get('report') or {}).get('importer_revision',1)!=revision:return True
    if run['status']=='COMPLETE':return run['started_at']<daily_slot(now)
    return run['started_at']<now-timedelta(hours=1)


@asynccontextmanager
async def actor_connection(pool,actor):
    # Publication already performs short atomic SQL transitions around remote I/O.
    # A surrounding long transaction would time out or hold row locks over HTTP.
    async with pool.acquire() as connection:
        try:
            await connection.execute("select set_config('tcg.user_id',$1,false),set_config('tcg.request_id',$2,false)",str(actor),str(uuid4()))
            await require_platform_admin(connection)
            yield connection
        finally:
            if not connection.is_closed():
                await connection.execute("select set_config('tcg.user_id','',false),set_config('tcg.request_id','',false)")


async def receipt(pool,actor,job,status,report,run_id=None):
    async with user_connection(pool,actor,str(uuid4())) as connection:
        await require_platform_admin(connection)
        if run_id:
            await connection.execute('''update tcg.catalogue_job_runs set status=$2,report=$3::jsonb,
              finished_at=clock_timestamp() where id=$1 and actor_user_id=$4''',run_id,status,json.dumps(report),actor)
            return run_id
        return await connection.fetchval('''insert into tcg.catalogue_job_runs(job,actor_user_id,status,report,finished_at)
          values($1,$2,$3,$4::jsonb,case when $3='RUNNING' then null else now() end) returning id''',job,actor,status,json.dumps(report))


async def sync_source(pool,actor,source,settings):
    feed=ReferenceFeeds();sets=cards=0;status='INCOMPLETE'
    async with user_connection(pool,actor,str(uuid4())) as connection:
        await require_platform_admin(connection)
        run_id=await connection.fetchval("insert into tcg.reference_sync_runs(source,status) values($1,'RUNNING') returning id",source)
    try:
        if source=='cardtrader_sealed':
            if not settings.cardtrader_api_token:raise ValueError('CardTrader is not configured')
            records=sealed_feed(CardTraderClient(api_token=settings.cardtrader_api_token))
            save=save_sealed_set
        else:
            records=getattr(feed,source)();save=save_reference_set
        async for record,items in records:
            if sets>=2000 or cards+len(items)>200000:raise ValueError('Reference import exceeds limit')
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await require_platform_admin(connection)
                await save(connection,record,items)
                await connection.execute('''update tcg.reference_sync_runs set sets_loaded=$2,cards_loaded=$3
                  where id=$1''',run_id,sets+1,cards+len({i['provider_id'] for i in items}))
            sets+=1;cards+=len({i['provider_id'] for i in items})
        if not sets:feed.failures.append({'reason':'NO_REFERENCE_RECORDS'})
        status='INCOMPLETE' if feed.failures else 'COMPLETE'
    except asyncio.CancelledError:
        feed.failures.append({'reason':'INTERRUPTED'});raise
    except Exception as exc:
        feed.failures.append({'reason':type(exc).__name__})
    finally:
        await feed.close()
        async with user_connection(pool,actor,str(uuid4())) as connection:
            await connection.execute('''update tcg.reference_sync_runs set status=$2,finished_at=now(),
              sets_loaded=$3,cards_loaded=$4,report=$5::jsonb where id=$1''',run_id,status,sets,cards,
              json.dumps({'scheduled':True,'importer_revision':SOURCE_REVISIONS.get(source,1),'failures':feed.failures[:30]}))
        log.warning('Daily catalogue source=%s status=%s sets=%s records=%s',source,status,sets,cards)
    return {'status':status,'sets':sets,'records':cards}


async def warm_prices(pool,actor,limit):
    run_id=await receipt(pool,actor,'REFERENCE_PRICES','RUNNING',{})
    checked=priced=failed=us_only=0;status='INCOMPLETE';report={'importer_revision':REFERENCE_JOB_REVISION}
    fx=EcbHistoricalFxProvider(timeout_seconds=6)
    try:
        report['pokemon_catalogue']=await refresh_pokemon_catalogue_prices(pool,actor,fx)
        report['one_piece']=await refresh_one_piece_prices(pool,actor,fx)
        report['dragon_ball']=await refresh_dragon_ball_prices(pool,actor,fx)
        async with user_connection(pool,actor,str(uuid4())) as connection:
            rows=await connection.fetch('''select 'r:'||md5(concat_ws(chr(31),r.provider,r.system_code,r.language,r.provider_id)) as key
              from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
              left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
              where r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language in ('English','Japanese')
                and (s.release_date is null or s.release_date<=current_date)
                and (p.checked_at is null or p.checked_at<$2 or p.refresh_revision<$3
                     or (p.expires_at<=now() and p.expires_at<=p.checked_at+interval '5 minutes'))
              order by p.checked_at nulls first,s.release_date desc nulls last,r.provider_id limit $1''',
              limit+1,daily_slot(datetime.now(timezone.utc)),REVISION)
        for start in range(0,min(len(rows),limit),40):
            keys=[r['key'] for r in rows[start:min(start+40,limit)]]
            views=await refresh_reference_prices(pool,actor,str(uuid4()),keys,fx_provider=fx,force=True)
            checked+=len(views);priced+=sum(v['market_value_minor'] is not None for v in views)
            failed+=sum(v.get('provider_refresh_failed',False) for v in views)
            us_only+=sum(v['market_value_minor'] is None and bool(v.get('market_quotes')) for v in views)
            if views and all(v.get('provider_refresh_failed') for v in views):
                report['reason']='PROVIDER_UNAVAILABLE';break
            await asyncio.sleep(.5)
        status='COMPLETE' if (len(rows)<=limit and not failed and not report['one_piece']['provider_failures']
                              and not report['dragon_ball']['provider_failures']
                              and not report['pokemon_catalogue']['provider_failures']) else 'INCOMPLETE'
        report['more_due_at_start']=len(rows)>limit
    except asyncio.CancelledError:
        report['reason']='INTERRUPTED';raise
    except Exception as exc:
        report['reason']=type(exc).__name__
    finally:
        report.update(checked=checked,priced=priced,us_context_only=us_only,provider_failures=failed,
                      scope='All English/Japanese Pokemon, English One Piece and English Dragon Ball references; independent of inventory')
        await receipt(pool,actor,'REFERENCE_PRICES',status,report,run_id)
        log.warning('Daily reference prices status=%s checked=%s priced=%s',status,checked,priced)


async def daily_pass(pool,settings):
    actor=UUID(settings.catalogue_maintenance_actor_user_id)
    async with pool.acquire() as lock:
        if not await lock.fetchval('select pg_try_advisory_lock($1)',847220092):return
        try:
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await require_platform_admin(connection)
                runs=await connection.fetch('select distinct on(source) source,started_at,status,report from tcg.reference_sync_runs order by source,started_at desc')
                jobs=await connection.fetch("select distinct on(job) job,started_at,status,report from tcg.catalogue_job_runs where job in ('REFERENCE_PRICES','SEALED_REFERENCE_PRICES','CATALOGUE_COVERAGE','CATALOGUE_VALUES','CARDMARKET_VALUES') order by job,started_at desc")
            last={r['source']:r for r in runs};now=datetime.now(timezone.utc)
            latest={r['job']:r for r in jobs}
            if due(latest.get('CATALOGUE_VALUES'),now,revision=CATALOGUE_VALUE_REVISION):
                await refresh_catalogue_values(pool,actor)
            if due(latest.get('CARDMARKET_VALUES'),now,revision=CARDMARKET_VALUE_REVISION):
                await refresh_cardmarket_values(pool,actor)
            for source in SOURCES:
                if due(last.get(source),now,revision=SOURCE_REVISIONS.get(source,1)):
                    await sync_source(pool,actor,source,settings)
            sealed_refreshed=False
            if due(latest.get('SEALED_REFERENCE_PRICES'),now,revision=SEALED_MARKET_REVISION):
                await refresh_sealed_prices(pool,actor)
                sealed_refreshed=True
            if due(latest.get('REFERENCE_PRICES'),now,revision=REFERENCE_JOB_REVISION):
                # Record the complete database scope before a potentially long
                # first fill; the final receipt then reflects its progress.
                await record_coverage(pool,actor)
                await warm_prices(pool,actor,settings.catalogue_price_refresh_limit)
                await refresh_cardmarket_values(pool,actor)
                await record_coverage(pool,actor)
            elif sealed_refreshed or due(latest.get('CATALOGUE_COVERAGE'),now):
                await record_coverage(pool,actor)
        finally:await lock.execute('select pg_advisory_unlock($1)',847220092)


async def shopify_pass(pool,settings):
    if not settings.shopify_publish_enabled or not settings.shopify_seller_sync_enabled:
        log.warning('Automatic Shopify sync paused: publication or seller sync is disabled');return
    actor=UUID(settings.catalogue_maintenance_actor_user_id)
    async with pool.acquire() as lock:
        if not await lock.fetchval('select pg_try_advisory_lock($1)',847220093):return
        try:
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await require_platform_admin(connection)
                candidates=await connection.fetch(SHOPIFY_CANDIDATES)
                previous=await connection.fetchval("select max(started_at) from tcg.catalogue_job_runs where job='SHOPIFY_SYNC'")
            for item in candidates:
                report={'inventory_id':str(item['id']),'version':item['version']}
                run=await receipt(pool,actor,'SHOPIFY_SYNC','RUNNING',report)
                try:
                    async with actor_connection(pool,actor) as connection:
                        result=await publish_inventory_to_shopify(connection,inventory_id=item['id'],owner_id=item['owner_id'],
                            expected_version=item['version'],actor_user_id=actor,automation_event_id=None,
                            request_id=str(run),test_mode=False)
                    report['result']=result['status'];status='COMPLETE'
                except asyncio.CancelledError:raise
                except HTTPException as exc:
                    report.update(result='REVIEW_OR_RETRY_REQUIRED',http_status=exc.status_code)
                    status='FAILED' if exc.status_code>=500 or exc.status_code==429 else 'INCOMPLETE'
                except Exception as exc:
                    report.update(result='RETRY_REQUIRED',reason=type(exc).__name__);status='FAILED'
                await receipt(pool,actor,'SHOPIFY_SYNC',status,report,run)
            prices=await reconcile_shopify_product_prices(pool,limit=25,request_id=str(uuid4()))
            if candidates or prices['candidate_count'] or previous is None or previous<datetime.now(timezone.utc)-timedelta(hours=1):
                status='INCOMPLETE' if prices.get('failed_count') or prices.get('retry_required_count') else 'COMPLETE'
                await receipt(pool,actor,'SHOPIFY_SYNC',status,{'publication_candidates':len(candidates),
                    'price_candidates':prices['candidate_count'],'prices_synced':prices['synced_count'],
                    'price_failures':prices.get('failed_count',0),'heartbeat':True})
                log.warning('Automatic Shopify sync candidates=%s prices=%s status=%s',len(candidates),prices['synced_count'],status)
        finally:await lock.execute('select pg_advisory_unlock($1)',847220093)


async def run_loop(pool,settings,*,shopify=False,wakeup=None):
    while True:
        # Clear BEFORE scanning: an approval during a pass must cause another
        # pass, not disappear into a subsequent clear/sleep race.
        if wakeup is not None:wakeup.clear()
        try:await (shopify_pass if shopify else daily_pass)(pool,settings)
        except asyncio.CancelledError:raise
        except Exception as exc:log.error('Catalogue maintenance job=%s failed type=%s','SHOPIFY' if shopify else 'DAILY',type(exc).__name__)
        if wakeup is None:
            await asyncio.sleep(60 if shopify else 300)
        else:
            try:await asyncio.wait_for(wakeup.wait(),timeout=60 if shopify else 300)
            except asyncio.TimeoutError:pass
