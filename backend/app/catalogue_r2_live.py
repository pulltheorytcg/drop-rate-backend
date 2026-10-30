"""Whole-catalogue R2 content with transactionally fresh, owner-specific SQL overlays.

Only closed, shared identity/display projections enter storage. Prices, mappings,
book validation, media approvals, inventory and ownership remain live SQL rules.
Publication never deletes source rows. An invalidated/incomplete object set cannot
be used, and cold downloads happen off the customer request transaction.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import re
import time
from uuid import UUID, uuid4

from .access_control import require_platform_admin
from .db import user_connection
from .object_storage import ObjectStorageError, configured_object_storage
from .catalogue_r2_index import SharedReferenceIndex
from .catalogue_r2_navigation import build_navigation, owned_navigation
from .catalogue_r2_browse import build_browse_index, indexed_browse_sql, indexed_catalogue_query

log = logging.getLogger(__name__)


def public_game_parity_diff(original, computed):
    """Only public game directory fields; no owner or account data in logs."""
    allowed=('game','languages','products','sets')
    a={r['system_code']:r for r in original if r.get('system_code')}
    b={r['system_code']:r for r in computed if r.get('system_code')}
    changes=[]
    for system in sorted(set(a)|set(b))[:20]:
        lhs,rhs=a.get(system,{}),b.get(system,{})
        fields={
            name:dict(sql=lhs.get(name),r2=rhs.get(name))
            for name in allowed if lhs.get(name)!=rhs.get(name)
        }
        if fields:
            changes.append(dict(system_code=system,fields=fields))
    return dict(sql_order=[r.get('system_code') for r in original[:20]],
                r2_order=[r.get('system_code') for r in computed[:20]],
                differences=changes)


def public_set_parity_diff(original, computed):
    """Public set metadata only; owner counts and valuations never enter logs."""
    fields=('system_code','set_id','set_name','language','provider','game',
            'release_date','indexed_count','card_count','total_count',
            'checklist_status')
    def clean(value):
        return value.isoformat() if hasattr(value,'isoformat') else value
    items=[]
    for idx in range(min(max(len(original),len(computed)),12)):
        a=original[idx] if idx<len(original) else {}
        b=computed[idx] if idx<len(computed) else {}
        changes={
            k:dict(sql=clean(a.get(k)),r2=clean(b.get(k)))
            for k in fields if a.get(k)!=b.get(k)
        }
        private_aggregates=('owned_count','owned_value_minor','unknown_values')
        if any(a.get(k)!=b.get(k) for k in private_aggregates):
            changes['owner_aggregates']='DIFFERENT'  # Never include values.
        if changes:
            items.append(dict(position=idx,fields=changes))
    return dict(sql_rows=len(original),r2_rows=len(computed),
                differences=items)


SCHEMA = 'drop-rate-live-catalogue-v1'
MAX_BYTES = 64_000_000
MAX_PARTS = 300
CHUNK_ROWS = 500
LOCK_ID = 847220097
STATE_SQL = '''select generation,published_generation,manifest,published_at
 from tcg_private.live_catalogue_r2_publication where singleton'''

# No SELECT *, attributes, source evidence, user IDs or physical-copy fields.
RELATIONS = {
    'reference_cards': (('provider','text'),('system_code','text'),('language','text'),
        ('provider_id','text'),('set_id','text'),('name','text'),('card_number','text'),
        ('rarity','text'),('image_url','text'),('source_url','text'),('number_key','text')),
    'reference_sets': (('provider','text'),('system_code','text'),('language','text'),
        ('set_id','text'),('name','text'),('release_date','date'),('declared_card_count','integer')),
    'reference_sealed_products': (('provider','text'),('system_code','text'),('language','text'),
        ('provider_id','text'),('set_id','text'),('name','text'),('product_type','text'),
        ('image_url','text'),('source_url','text')),
    'catalogue_products': (('id','uuid'),('product_type','text'),('game','text'),('name','text'),
        ('set_name','text'),('card_number','text'),('variant','text'),('rarity','text'),('language','text')),
    'catalogue_product_profiles': (('catalogue_id','uuid'),('system_code','text'),
        ('collectible_type','text'),('set_code','text'),('release_date','date')),
}
KEYS = {name: ('provider','system_code','language', 'set_id' if name=='reference_sets' else 'provider_id')
        for name in RELATIONS if name.startswith('reference_')}
KEYS.update(catalogue_products=('id',), catalogue_product_profiles=('catalogue_id',))


def enabled(kind):
    return os.getenv(f'TCG_R2_LIVE_CATALOGUE_{kind}_ENABLED', 'false').lower() in {'true','1'}


def chunk_sql(relation):
    fields = ','.join(name for name, _ in RELATIONS[relation])
    order = ','.join(KEYS[relation])
    return f'''select coalesce(jsonb_agg(to_jsonb(page) order by {order}),'[]'::jsonb)::text as payload
      from (select {fields} from tcg.{relation} order by {order} limit $1 offset $2) page'''


def parse_part(raw, relation, digest, size, count):
    if (not isinstance(raw,bytes) or len(raw)!=size or not 0<size<=4_000_000
            or hashlib.sha256(raw).hexdigest()!=digest):
        raise ObjectStorageError('Live catalogue part failed integrity verification')
    rows = json.loads(raw)
    columns = {name for name, _ in RELATIONS[relation]}
    if not isinstance(rows,list) or len(rows)!=count or not 0<count<=CHUNK_ROWS:
        raise ObjectStorageError('Live catalogue part count is invalid')
    for row in rows:
        if (not isinstance(row,dict) or set(row)!=columns
                or any(value is not None and not isinstance(value,(str,int)) for value in row.values())
                or any(not isinstance(row[key],str) or not row[key] for key in KEYS[relation])):
            raise ObjectStorageError('Live catalogue part contains unexpected fields or identity')
    return rows


def validate_manifest(value, generation):
    if isinstance(value,str):
        value=json.loads(value)
    if (not isinstance(value,dict) or set(value)!={'schema','generation','counts','parts','raw_bytes'}
            or value['schema']!=SCHEMA or value['generation']!=generation
            or not isinstance(value['parts'],list) or len(value['parts'])>MAX_PARTS
            or not isinstance(value['counts'],dict) or set(value['counts'])!=set(RELATIONS)):
        raise ObjectStorageError('Invalid live catalogue manifest')
    counts = dict.fromkeys(RELATIONS,0)
    size = 0
    seen = set()
    for part in value['parts']:
        if (not isinstance(part,dict) or set(part)!={'relation','sha256','raw_bytes','rows'}
                or part['relation'] not in RELATIONS
                or not re.fullmatch('[a-f0-9]{64}',str(part['sha256']))
                or type(part['raw_bytes']) is not int or not 0<part['raw_bytes']<=4_000_000
                or type(part['rows']) is not int or not 0<part['rows']<=CHUNK_ROWS
                or part['sha256'] in seen):
            raise ObjectStorageError('Invalid live catalogue part descriptor')
        seen.add(part['sha256'])
        counts[part['relation']] += part['rows']
        size += part['raw_bytes']
    if (counts!=value['counts'] or size!=value['raw_bytes'] or not 0<size<=MAX_BYTES
            or any(type(n) is not int for n in value['counts'].values())):
        raise ObjectStorageError('Live catalogue completeness check failed')
    return value


@dataclass(frozen=True)
class LiveCatalogue:
    generation: int
    manifest_digest: str
    rows: dict
    scope_index: SharedReferenceIndex | None = field(default=None, repr=False, compare=False)

    def sql(self, query, params, *, systems=None, language='', provider=None, set_id=''):
        """Replace shared content only. Existing SQL still owns every decision."""
        if not query.startswith('\nwith reference_base as not materialized ('):
            raise ValueError('Unexpected catalogue query shape')
        params = list(params)
        ctes=[]
        for table, columns in RELATIONS.items():
            rows=self.rows[table]
            # The source population and SQL decisions are unchanged. Only
            # reference collection is indexed in Railway (not PostgreSQL).
            # Canonical products remain complete for exact-link suppression.
            if table.startswith('reference_'):
                if self.scope_index is not None:
                    rows=self.scope_index.select(table,rows,
                        systems=systems,language=language,provider=provider,
                        set_id=set_id)
                else:
                    rows=[r for r in rows if (not systems or r['system_code'] in systems)
                        and (not language or r['language']==language)
                        and (provider is None or r['provider']==provider)
                        and (not set_id or r['set_id']==set_id)]
            # Bind compact column arrays, not one very large JSONB recordset.
            # JSONB decoding multiplied memory and parse work on the production
            # database. Text arrays keep date/UUID transport consistent across
            # drivers; casts retain the original SQL column types. Every array
            # comes from the same row order, including NULLs.
            arrays=[]
            for name,kind in columns:
                params.append([None if r[name] is None else str(r[name]) for r in rows])
                arrays.append(f'${len(params)}::text[]')
            fields=','.join(f'x.{name}::{kind} as {name}' for name,kind in columns)
            names=','.join(name for name,_ in columns)
            ctes.append(f'live_r2_{table} as (select {fields} from unnest({",".join(arrays)}) as x({names}))')
            query=re.sub(r'\btcg\.'+table+r'\b', 'live_r2_'+table, query)
        return query.replace('\nwith ', '\nwith '+',\n'.join(ctes)+',\n',1),params


def manifest_digest(manifest):
    return hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def assemble(manifest, parts):
    rows={name:[] for name in RELATIONS}
    identities={name:set() for name in RELATIONS}
    for part, raw in zip(manifest['parts'],parts,strict=True):
        table=part['relation']
        for row in parse_part(raw,table,part['sha256'],part['raw_bytes'],part['rows']):
            key=tuple(row[field] for field in KEYS[table])
            if key in identities[table]:
                raise ObjectStorageError('Duplicate catalogue identity across R2 parts')
            identities[table].add(key)
            rows[table].append(row)
    return LiveCatalogue(manifest['generation'],manifest_digest(manifest),rows,
                         SharedReferenceIndex.build(rows))


_current = None
_loading = None
_nav_cache = {}
_browse_cache = {}


def indexed_browse_enabled():
    return os.getenv('TCG_R2_LIVE_CATALOGUE_INDEXED_BROWSE_ENABLED','false').lower() in ('true','1')

def extended_browse_enabled():
    # Separate opt-in: text/owned/sealed shortlists are not default navigation.
    return os.getenv('TCG_R2_LIVE_CATALOGUE_EXTENDED_BROWSE_ENABLED','false').lower() in ('true','1')


def browse_for(snapshot):
    key=(snapshot.generation,datetime.now(timezone.utc).date())
    if key not in _browse_cache:
        _browse_cache.clear()
        _browse_cache[key]=build_browse_index(snapshot.rows,today=key[1])
    return _browse_cache[key]



def navigation_enabled():
    return os.getenv('TCG_R2_LIVE_CATALOGUE_NAVIGATION_ENABLED', 'false').lower() in ('true','1')


def navigation_for(snapshot):
    """Build one immutable Railway navigation index per R2 generation/UTC date.

    The clock-dependent release filter must refresh at midnight without
    requiring an R2 rewrite or restarting Railway.
    """
    key=(snapshot.generation,datetime.now(timezone.utc).date())
    if key not in _nav_cache:
        _nav_cache.clear()
        _nav_cache[key]=build_navigation(snapshot.rows,today=key[1])
    return _nav_cache[key]


async def eligible_navigation(connection,snapshot):
    """Never use precomputed canonical aliases when dynamic verified mappings exist."""
    if snapshot is None or not navigation_enabled():
        return None
    try:
        verified=await connection.fetchval("""select exists(
            select 1 from tcg.provider_catalogue_mappings
            where match_status='VERIFIED'
              and provider_entity_type='CARD_PRINTING'
              and provider_variant_key='')""")
        return None if verified else navigation_for(snapshot)
    except Exception as exc:
        log.warning('CATALOGUE_R2_NAVIGATION_FALLBACK type=%s',type(exc).__name__)
        return None



async def download(manifest, storage):
    """At most four private storage reads at once, with existing bounded IO."""
    from .catalogue_r2_cache import _read_with_budget
    semaphore=asyncio.Semaphore(4)
    async def part_read(part):
        async with semaphore:
            return await _read_with_budget(storage,part['sha256'])
    parts=await asyncio.gather(*(part_read(p) for p in manifest['parts']))
    return assemble(manifest,parts)


async def _load(manifest,storage):
    global _current
    try:
        loaded=await download(manifest,storage)
        if _current is None or loaded.generation>=_current.generation:
            _current=loaded
        log.warning('CATALOGUE_R2_LIVE_LOADED generation=%s counts=%s',loaded.generation,manifest['counts'])
    except Exception as exc:
        log.warning('CATALOGUE_R2_LIVE_LOAD_FAILED type=%s',type(exc).__name__)


async def read(connection):
    """One small version read, no source scan; a cold worker falls back while loading."""
    global _loading
    if not enabled('DELIVERY'):
        return None
    try:
        async with connection.transaction():
            state=await connection.fetchrow(STATE_SQL)
        if not state or state['generation']!=state['published_generation']:
            return None
        manifest=validate_manifest(state['manifest'],state['generation'])
        if (_current is not None and _current.generation==state['generation']
                and _current.manifest_digest==manifest_digest(manifest)):
            return _current
        if _loading is None or _loading.done():
            storage=configured_object_storage()
            if storage is not None:
                _loading=asyncio.create_task(_load(manifest,storage))
        return None
    except Exception as exc:
        log.warning('CATALOGUE_R2_LIVE_FALLBACK type=%s',type(exc).__name__)
        return None


async def fetch(connection, query, params, snapshot, **scope):
    from .catalogue_browser import REFERENCE_VALUES_CTE
    if REFERENCE_VALUES_CTE in query:
        rows=await connection.fetch(query,*params)
        log.info('CATALOGUE_DYNAMIC_VALUE_DATABASE rows=%s',len(rows))
        return rows
    if snapshot is not None and navigation_enabled():
        try:
            from .catalogue_browser import GAMES_SQL, SETS_SQL
            if query in (GAMES_SQL, SETS_SQL):
                nav=await eligible_navigation(connection,snapshot)
                if nav is not None:
                    if query==GAMES_SQL:
                        return nav.games()
                    if isinstance(params[3],str) and params[3].isascii():
                        owner=await owned_navigation(connection,params[0])
                        return nav.sets(systems=params[1],language=params[2],
                            search=params[3],limit=params[4],offset=params[5],
                            owner=owner)
        except Exception as exc:
            log.warning('CATALOGUE_R2_NAVIGATION_QUERY_FALLBACK type=%s',type(exc).__name__)
    if snapshot is not None and (indexed_browse_enabled() or extended_browse_enabled()):
        try:
            # Any verified provider-to-canonical links can change the browsing
            # population without changing the R2 snapshot. Refuse the shortcut.
            if not await connection.fetchval("""select exists(
              select 1 from tcg.provider_catalogue_mappings
              where match_status='VERIFIED'
                and provider_entity_type='CARD_PRINTING'
                and provider_variant_key='')"""):
                selected=browse_for(snapshot)
                from . import catalogue_r2_market
                market=await catalogue_r2_market.read(connection)
                if extended_browse_enabled():
                    owner_nav=(await owned_navigation(connection,params[0])
                        if "where coalesce(o.quantity,0)>0 order by" in query else None)
                    indexed_query,indexed_args,mode=indexed_catalogue_query(
                        query,params,selected,owned=owner_nav,market=market)
                else:
                    indexed_query,indexed_args=indexed_browse_sql(
                        query,params,selected,market=market)
                    mode='NEWEST'
                async with connection.transaction():
                    rows=await connection.fetch(indexed_query,*indexed_args)
                log.info('CATALOGUE_R2_INDEXED_BROWSE_HIT mode=%s rows=%s',
                         mode,len(rows))
                if market is not None:
                    log.info('CATALOGUE_R2_MARKET_HIT generation=%s rows=%s',market.generation,len(rows))
                return rows
        except Exception as exc:
            log.warning('CATALOGUE_R2_INDEXED_BROWSE_FALLBACK type=%s',
                        type(exc).__name__)
    if snapshot is not None:
        try:
            rows=await fetch_snapshot(connection,query,params,snapshot,**scope)
            log.info('CATALOGUE_R2_LIVE_HIT generation=%s rows=%s',snapshot.generation,len(rows))
            return rows
        except Exception as exc:
            log.warning('CATALOGUE_R2_LIVE_QUERY_FALLBACK type=%s',type(exc).__name__)
    return await connection.fetch(query,*params)


async def fetch_snapshot(connection, query, params, snapshot, **scope):
    """Bound JSON joins without leaking planner settings to other SQL.

    Shared inputs have no persistent statistics or indexes. PostgreSQL selected
    quadratic nested loops and spilling merge joins at production size. Hash
    joins preserve the SQL decisions; JIT is disabled for this statement because
    unavoidable lateral loops otherwise inherit the disabled-loop cost penalty.
    A savepoint restores settings on failure, and success restores them explicitly.
    """
    async with connection.transaction():
        from .catalogue_browser import REFERENCE_VALUES_CTE
        if REFERENCE_VALUES_CTE in query:
            # Complete value ranking remains the live SQL authority. Sending
            # all 70k identities as one parameter message stalls the production
            # connection; ordinary bounded pages still use R2 inputs/prices.
            return await connection.fetch(query,*params)
        previous=await connection.fetchrow("select current_setting('enable_nestloop') as nestloop,current_setting('enable_mergejoin') as mergejoin,current_setting('jit') as jit")
        await connection.execute('set local enable_nestloop=off; set local enable_mergejoin=off; set local jit=off')
        sql,args=snapshot.sql(query,params,**scope)
        rows=await connection.fetch(sql,*args)
        await connection.execute("select set_config('enable_nestloop',$1,true),set_config('enable_mergejoin',$2,true),set_config('jit',$3,true)",
                                 previous['nestloop'],previous['mergejoin'],previous['jit'])
        return rows


async def verify(pool, actor, snapshot):
    """Read-only live query parity; no account rows leave this function."""
    from .catalogue_browser import GAMES_SQL, SETS_SQL, SOURCE_CTE, product_query
    results=[]
    async with user_connection(pool,actor,str(uuid4()),readonly_snapshot=True) as connection:
        access=await require_platform_admin(connection)
        state=await connection.fetchrow(STATE_SQL)
        if state['generation']!=snapshot.generation:
            return {'status':'SOURCE_CHANGED','equal':None}
        owner=access['owner_id']
        verified=[dict(row) for row in await connection.fetch("""
          select catalogue_id::text as catalogue_id,source_provider,
            system_code,provider_language,provider_id,provider_entity_type,
            provider_variant_key,match_status
          from tcg.provider_catalogue_mappings
          where provider_entity_type='CARD_PRINTING'
            and provider_variant_key='' and match_status='VERIFIED'""")]
        navigation=build_navigation(snapshot.rows,
            today=datetime.now(timezone.utc).date(),verified_mappings=verified)
        browse_index=build_browse_index(snapshot.rows,
            today=datetime.now(timezone.utc).date(),verified_mappings=verified)
        from . import catalogue_r2_market
        market=await catalogue_r2_market.read(connection)
        # Compare the entire identity population, not only visible samples.
        # The value sort deliberately retains its existing live database path.
        source_keys=await connection.fetch(SOURCE_CTE+' select key from entries',owner)
        expected_keys=sorted(row['key'] for row in source_keys)
        actual_keys=sorted(row['key'] for row in browse_index.entries)
        if expected_keys!=actual_keys:
            return {'status':'MISMATCH','equal':False,'reason':'IDENTITY_POPULATION',
                    'database_entries':len(expected_keys),'r2_entries':len(actual_keys)}
        log.warning('CATALOGUE_R2_LIVE_IDENTITY_PARITY entries=%s equal=true',len(actual_keys))
        owner_nav=await owned_navigation(connection,owner)
        cases=[('games',GAMES_SQL,[owner]),
            ('sets',SETS_SQL,[owner,['POKEMON_TCG'],'','',10,0])]
        for name,options in (('browse',{}),('search',dict(q='Pikachu')),
                ('books',dict(product_type='COMIC')),('sealed',dict(product_type='SEALED')),
                ('owned',dict(owned='owned')),('value',dict(sort='value_desc'))):
            query,args=product_query(owner_id=owner,limit=9,**options)
            cases.append((name,query,args))
        for name,query,args in cases:
            log.warning('CATALOGUE_R2_LIVE_PARITY_START case=%s',name)
            started=time.perf_counter()
            # The legacy full-table baseline itself can exceed the request
            # deadline. Give only this read-only offline comparison 30 seconds;
            # R2 queries and live application request limits remain unchanged.
            async with connection.transaction():
                previous_timeout=await connection.fetchval("select current_setting('statement_timeout')")
                await connection.execute("set local statement_timeout='30s'")
                original=[dict(row) for row in await connection.fetch(query,*args,timeout=30)]
                await connection.execute("select set_config('statement_timeout',$1,true)",previous_timeout)
            db_ms=round((time.perf_counter()-started)*1000,2)
            log.warning('CATALOGUE_R2_LIVE_PARITY_DATABASE case=%s rows=%s elapsed_ms=%s',name,len(original),db_ms)
            started=time.perf_counter()
            if name=='games':
                cached=navigation.games()
            elif name=='sets':
                cached=navigation.sets(systems=['POKEMON_TCG'],limit=10,
                                       owner=owner_nav)
            elif name in ('browse','search','books','sealed','owned'):
                indexed_query,indexed_args,mode=indexed_catalogue_query(
                    query,args,browse_index,owned=owner_nav,market=market)
                cached=[dict(row) for row in await connection.fetch(
                    indexed_query,*indexed_args)]
            else:
                cached=[dict(row) for row in await fetch(connection,query,args,snapshot)]
            r2_ms=round((time.perf_counter()-started)*1000,2)
            results.append(dict(case=name,rows=len(original),equal=original==cached,
                                database_ms=db_ms,r2_ms=None if name=='value' else r2_ms,
                                computed_ms=r2_ms,delivery='POSTGRES_DYNAMIC_VALUE' if name=='value' else 'R2'))
            if market is not None and name in ('browse','search','books','sealed','owned'):
                results[-1]['r2_market_generation']=market.generation
            log.warning('CATALOGUE_R2_LIVE_PARITY %s',json.dumps(results[-1],sort_keys=True))
            if original!=cached:
                if name=='games':
                    log.warning('CATALOGUE_R2_LIVE_PUBLIC_GAME_DIFF %s',
                                json.dumps(public_game_parity_diff(original,cached),
                                           sort_keys=True))
                elif name=='sets':
                    log.warning('CATALOGUE_R2_LIVE_PUBLIC_SET_DIFF %s',
                                json.dumps(public_set_parity_diff(original,cached),
                                           sort_keys=True))
                return {'status':'MISMATCH','equal':False,'cases':results}
    return {'status':'MATCH','equal':True,'identity_entries':len(actual_keys),'cases':results}


async def publish(pool, actor, *, storage=None):
    """Existing worker owns publication; CAS prevents a stale build becoming live."""
    global _current
    if not isinstance(actor,UUID):
        raise ValueError('Publication requires an existing administrator')
    storage=storage if storage is not None else configured_object_storage()
    if storage is None:
        raise ObjectStorageError('Private R2 storage is not configured')
    # Avoid duplicate publishers across overlapping Railway releases.
    async with pool.acquire() as lock:
        if not await lock.fetchval('select pg_try_advisory_lock($1)',LOCK_ID):
            return {'status':'LOCKED'}
        try:
            raw_parts=[]
            async with user_connection(pool,actor,str(uuid4()),readonly_snapshot=True) as connection:
                await require_platform_admin(connection)
                state=await connection.fetchrow(STATE_SQL)
                if state is None:
                    raise ObjectStorageError('Publication migration is not installed')
                if state['generation']==state['published_generation']:
                    manifest=validate_manifest(state['manifest'],state['generation'])
                    if (_current is None or _current.generation!=state['generation']
                            or _current.manifest_digest!=manifest_digest(manifest)):
                        # Loading after releasing the DB snapshot avoids idle leases.
                        pass
                    else:
                        return {'status':'CURRENT','generation':state['generation'],'counts':manifest['counts']}
                else:
                    manifest={'schema':SCHEMA,'generation':state['generation'],'counts':dict.fromkeys(RELATIONS,0),
                              'parts':[],'raw_bytes':0}
                    for table in RELATIONS:
                        offset=0
                        while True:
                            raw=(await connection.fetchval(chunk_sql(table),CHUNK_ROWS,offset)).encode()
                            count=len(json.loads(raw))
                            if not count:
                                break
                            digest=hashlib.sha256(raw).hexdigest()
                            parse_part(raw,table,digest,len(raw),count)
                            manifest['parts'].append(dict(relation=table,sha256=digest,raw_bytes=len(raw),rows=count))
                            manifest['counts'][table]+=count
                            manifest['raw_bytes']+=len(raw)
                            if manifest['raw_bytes']>MAX_BYTES or len(manifest['parts'])>MAX_PARTS:
                                raise ObjectStorageError('Whole catalogue exceeds publication bounds')
                            raw_parts.append(raw)
                            offset+=count
                            if count<CHUNK_ROWS:
                                break
            validate_manifest(manifest,state['generation'])
            log.warning('CATALOGUE_R2_LIVE_EXTRACTED generation=%s counts=%s parts=%s raw_bytes=%s',
                        state['generation'],manifest['counts'],len(manifest['parts']),manifest['raw_bytes'])
            if not raw_parts:
                _current=await download(manifest,storage)
                return {'status':'LOADED','generation':_current.generation,'counts':manifest['counts']}
            # Persist and independently read back every immutable part before CAS.
            for part,raw in zip(manifest['parts'],raw_parts,strict=True):
                receipt=await asyncio.to_thread(storage.put_verified_reference_snapshot,raw)
                if (receipt.get('verified') is not True or receipt.get('sha256')!=part['sha256']
                        or receipt.get('key')!=f"{storage.config.prefix}/catalogue-reference-inputs/{part['sha256']}.json.gz"):
                    raise ObjectStorageError('Storage receipt did not verify the catalogue part')
            candidate=await download(manifest,storage)
            log.warning('CATALOGUE_R2_LIVE_READBACK generation=%s verified_parts=%s',
                        candidate.generation,len(raw_parts))
            parity=await verify(pool,actor,candidate)
            if parity['status']!='MATCH':
                return {'status':parity['status'],'generation':manifest['generation'],'query_parity':parity}
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await require_platform_admin(connection)
                committed=await connection.fetchval('''update tcg_private.live_catalogue_r2_publication
                  set published_generation=$1,manifest=$2::jsonb,published_at=now()
                  where singleton and generation=$1 returning published_generation''',manifest['generation'],json.dumps(manifest))
            if committed is None:
                return {'status':'SOURCE_CHANGED','generation':manifest['generation'],'verified_parts':len(raw_parts)}
            _current=candidate
            return {'status':'PUBLISHED','generation':committed,'counts':manifest['counts'],
                    'verified_parts':len(raw_parts),'raw_bytes':manifest['raw_bytes'],
                    'query_parity':parity,'catalogue_rows_deleted':0}
        finally:
            await lock.execute('select pg_advisory_unlock($1)',LOCK_ID)
