"""Permission-gated catalogue context, isolated from physical/sold price caches."""
import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
from fastapi import HTTPException

from .db import user_connection
from .fx import EcbHistoricalFxProvider
from .reference_market import MAX_AGE, READ_SQL, _time, fetch_quotes

_cache = OrderedDict()
_PERMISSIONS = json.loads((Path(__file__).resolve().parent.parent/'data/regional_price_display_permissions.json').read_text())['sources']


def display_permissions():
    return {source for source,policy in _PERMISSIONS.items() if policy.get('commercial_display') is True}


def eligible_quotes(rows, now, *, allowed_sources=None):
    allowed=display_permissions() if allowed_sources is None else allowed_sources
    result=[]
    for row in rows:
        sale=row.get('regional_sale') or {}
        if (row.get('source') not in allowed or sale.get('physical_valuation_eligible') is not False
            or type(sale.get('price_gbp_minor')) is not int or sale['price_gbp_minor']<=0
            or not row.get('variant_id') or not row.get('product_id')):continue
        pair=(row.get('source'),sale.get('region'),sale.get('source_field'))
        if pair not in {('TCGDEX_CARDMARKET','EU','avg7'),('TCGDEX_CARDMARKET','EU','avg7-holo'),
            ('TCGDEX_CARDMARKET_VARIANT','EU','avg7'),('TCGDEX_CARDMARKET_VARIANT','EU','avg7-holo'),
            ('TCGDEX_TCGPLAYER','US','marketPrice')}:continue
        try:
            observed=_time(row['observed_at'])
            fx_at=_time(sale['fx_effective_at'])
            rate=Decimal(sale['fx_rate_to_gbp'])
            if not rate.is_finite() or rate<=0 or not sale.get('fx_source'):continue
        except (ValueError,TypeError,KeyError,InvalidOperation):continue
        if now-MAX_AGE<=observed<=now and observed-timedelta(days=7)<=fx_at<=observed:
            result.append({**row,'physical_valuation_eligible':False,
                           'valuation_role':'REGIONAL_CATALOGUE_CONTEXT_ONLY'})
    return result


def _identity(row):
    return tuple(row.get(k) for k in ('key','set_id','set_name','name','card_number','language'))


def _identity_hash(row):
    return hashlib.sha256(json.dumps(_identity(row),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def attach_cached_regional_prices(rows):
    now=datetime.now(timezone.utc)
    for row in rows:
        if row.get('provider')=='TCGdex' and row.get('source_kind')=='REFERENCE':
            row['regional_context_permission']=bool(display_permissions())
            row['regional_quotes']=[]
            cached=_cache.get(_identity(row))
            if cached and cached[0]>now:row['regional_quotes']=eligible_quotes(cached[1],now)
    return rows


def _daily_limit():
    # Zero until an operator configures a reviewed provider ceiling. Never imply
    # our hard safety ceiling of 500/day is a published provider allowance.
    try:value=int(os.getenv('DROP_RATE_REGIONAL_TCGDEX_DAILY_LIMIT','0'))
    except ValueError:return 0
    return value if 0<=value<=500 else 0


async def _claim(pool,user_id,request_id,reference):
    key=reference['key'];identity=_identity_hash(reference)
    async with user_connection(pool,user_id,request_id) as c:
        # Shared advisory lock + durable counter; transaction commits before HTTP.
        await c.execute("select pg_advisory_xact_lock(hashtextextended('tcg.regional-tcgdex-budget',0))")
        now=await c.fetchval('select clock_timestamp()')
        cached=await c.fetchrow('select * from tcg.reference_regional_price_context where reference_key=$1 for update',key)
        if cached and cached['identity_sha256']==identity:
            rows=eligible_quotes(cached['quotes'],now)
            if cached['expires_at'] and cached['expires_at']>now and rows:return rows,None,None
            if cached['retry_after'] and cached['retry_after']>now:return [],None,'REFERENCE_BACKOFF'
            if cached['lease_until'] and cached['lease_until']>now:return [],None,'REFERENCE_BUSY'
        await c.execute("insert into tcg.reference_regional_provider_budget(provider,request_day) values('TCGDEX',$1) on conflict do nothing",now.date())
        budget=await c.fetchrow("select * from tcg.reference_regional_provider_budget where provider='TCGDEX' for update")
        if budget['blocked_until'] and budget['blocked_until']>now:return [],None,'PROVIDER_BACKOFF'
        used=budget['requests'] if budget['request_day']==now.date() else 0
        if used>=_daily_limit():return [],None,'DAILY_LIMIT'
        token=uuid4()
        await c.execute("update tcg.reference_regional_provider_budget set request_day=$1,requests=$2 where provider='TCGDEX'",now.date(),used+1)
        await c.execute("""insert into tcg.reference_regional_price_context(reference_key,identity_sha256,lease_token,lease_until)
          values($1,$2,$3,$4) on conflict(reference_key) do update set
          quotes=case when tcg.reference_regional_price_context.identity_sha256=$2 then tcg.reference_regional_price_context.quotes else '[]'::jsonb end,
          expires_at=case when tcg.reference_regional_price_context.identity_sha256=$2 then tcg.reference_regional_price_context.expires_at else null end,
          identity_sha256=$2,lease_token=$3,lease_until=$4""",key,identity,token,now+timedelta(seconds=30))
    return [],token,None


def retry_seconds(response, now):
    value=response.headers.get('retry-after','') if response is not None else ''
    try:seconds=int(value)
    except ValueError:
        try:seconds=int((parsedate_to_datetime(value)-now).total_seconds())
        except (ValueError,TypeError,OverflowError):seconds=3600
    # Never retry earlier than the provider's stated time. Oversized hints fail
    # closed for at least that interval rather than clamping the hint downward.
    return max(60,seconds)


async def _finish(pool,user_id,request_id,reference,token,rows,*,backoff=300,rate_limited=False):
    async with user_connection(pool,user_id,request_id) as c:
        now=await c.fetchval('select clock_timestamp()')
        cached=await c.fetchrow('select * from tcg.reference_regional_price_context where reference_key=$1 for update',reference['key'])
        if rate_limited:
            await c.execute("update tcg.reference_regional_provider_budget set blocked_until=greatest(coalesce(blocked_until,$1),$1) where provider='TCGDEX'",now+timedelta(seconds=backoff))
        if not cached or cached['lease_token']!=token or cached['identity_sha256']!=_identity_hash(reference):return False
        if rows:
            raw=json.dumps(rows,separators=(',',':'));digest=hashlib.sha256(raw.encode()).hexdigest()
            expires=min(now+timedelta(days=1),min(_time(r['observed_at'])+MAX_AGE for r in rows))
            await c.execute('insert into tcg.reference_regional_price_history(reference_key,identity_sha256,quotes_sha256,quotes) values($1,$2,$3,$4::jsonb) on conflict do nothing',reference['key'],_identity_hash(reference),digest,raw)
            await c.execute('update tcg.reference_regional_price_context set quotes=$2::jsonb,checked_at=$3,expires_at=$4,retry_after=null,lease_token=null,lease_until=null where reference_key=$1',reference['key'],raw,now,expires)
        else:
            # Retain prior quotes, evidence dates and expiry on failure/empty.
            await c.execute('update tcg.reference_regional_price_context set retry_after=$2,lease_token=null,lease_until=null where reference_key=$1',reference['key'],now+timedelta(seconds=backoff))
    return True


async def regional_prices_for_reference(pool,user_id,request_id,key):
    if not display_permissions():
        return {'quotes':[],'status':'SOURCE_PERMISSION_UNVERIFIED',
                'blocked_sources':{k:v['reason'] for k,v in _PERMISSIONS.items() if v.get('commercial_display') is not True}}
    async with user_connection(pool,user_id,request_id) as c:
        records=await c.fetch(READ_SQL,[key])
    if not records:raise HTTPException(404,'Unknown regional price reference')
    reference=dict(records[0])
    try:rows,token,reason=await _claim(pool,user_id,request_id,reference)
    except asyncpg.PostgresError:
        raise HTTPException(503,'Regional context cache is not ready') from None
    if not token:return {'quotes':rows,'status':reason or 'CACHED','commercial_display_permitted':True}
    now=datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=6,follow_redirects=False) as client:
            quotes=await asyncio.wait_for(fetch_quotes(client,reference,EcbHistoricalFxProvider(timeout_seconds=6),now=now),timeout=16)
    except httpx.HTTPStatusError as exc:
        limited=exc.response.status_code==429
        await _finish(pool,user_id,request_id,reference,token,[],backoff=retry_seconds(exc.response,now) if limited else 300,rate_limited=limited)
        return {'quotes':[],'status':'PROVIDER_BACKOFF' if limited else 'PROVIDER_UNAVAILABLE'}
    except (httpx.HTTPError,ValueError,RuntimeError,TimeoutError):
        await _finish(pool,user_id,request_id,reference,token,[])
        return {'quotes':[],'status':'PROVIDER_UNAVAILABLE'}
    rows=eligible_quotes(quotes,now)
    if not await _finish(pool,user_id,request_id,reference,token,rows):
        return {'quotes':[],'status':'SUPERSEDED'}
    if rows:
        _cache[_identity(reference)]=(min(now+timedelta(minutes=30),min(_time(r['observed_at'])+MAX_AGE for r in rows)),rows)
        _cache.move_to_end(_identity(reference))
        if len(_cache)>512:_cache.popitem(last=False)
    return {'quotes':rows,'status':'AVAILABLE_CONTEXT' if rows else 'INSUFFICIENT_REGIONAL_EVIDENCE',
            'commercial_display_permitted':True}
