"""Verified shared market data in R2, independently versioned from identities.

Provider jobs keep writing their existing SQL caches. A changed generation
immediately falls back to those caches until a complete R2 copy is verified.
Only bounded catalogue pages use these inputs; SQL retains freshness, exact
printing, currency and owner rules. Inventory valuations are never exported.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
from uuid import UUID, uuid4

from .access_control import require_platform_admin
from .catalogue_r2_cache import _read_with_budget
from .catalogue_r2_live import manifest_digest
from .db import user_connection
from .object_storage import ObjectStorageError, configured_object_storage

log = logging.getLogger(__name__)
SCHEMA = 'drop-rate-market-v1'
KEYS = ('provider', 'system_code', 'language', 'provider_id')
PRICE_COLUMNS = tuple((key, 'text') for key in KEYS) + (
    ('quotes', 'jsonb'), ('market_value_minor', 'bigint'),
    ('market_value_high_minor', 'bigint'), ('pricing_updated_at', 'timestamptz'),
    ('checked_at', 'timestamptz'), ('expires_at', 'timestamptz'))
RELATIONS = {
    'reference_market_prices': PRICE_COLUMNS + (('refresh_revision', 'integer'),),
    'reference_catalogue_prices': PRICE_COLUMNS,
    'reference_sealed_market_prices': PRICE_COLUMNS,
    'reference_asking_prices': tuple((key, 'text') for key in KEYS) + (
        ('snapshot_id', 'uuid'), ('reference_identity', 'jsonb'),
        ('estimate_minor', 'bigint'), ('estimate_high_minor', 'bigint'),
        ('currency', 'text'), ('listing_count', 'integer'), ('seller_count', 'integer'),
        ('observed_at', 'timestamptz'), ('checked_at', 'timestamptz'),
        ('expires_at', 'timestamptz'), ('method_version', 'text'), ('evidence', 'jsonb')),
}
STATE_SQL = '''select generation,published_generation,manifest,published_at
 from tcg_private.live_catalogue_r2_market_publication where singleton'''
CHUNK_ROWS = 250
MAX_PARTS = 800
MAX_BYTES = 160_000_000
LOCK_ID = 847220099


def enabled(kind):
    return os.getenv(f'TCG_R2_MARKET_{kind}_ENABLED', 'false').lower() in {'true', '1'}


def chunk_sql(table):
    columns = ','.join(name for name, _ in RELATIONS[table])
    order = ','.join(KEYS)
    return f'''select coalesce(jsonb_agg(to_jsonb(p) order by {order}),'[]'::jsonb)::text
      from (select {columns} from tcg.{table} order by {order} limit $1 offset $2) p'''


def parse_part(raw, part):
    if (not isinstance(raw, bytes) or len(raw) != part['raw_bytes']
            or not 0 < len(raw) <= 4_000_000
            or hashlib.sha256(raw).hexdigest() != part['sha256']):
        raise ObjectStorageError('Market part integrity failed')
    rows = json.loads(raw)
    columns = RELATIONS[part['relation']]
    if not isinstance(rows, list) or len(rows) != part['rows']:
        raise ObjectStorageError('Market part count failed')
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {n for n, _ in columns}
                or any(not isinstance(row[k], str) or not row[k] for k in KEYS)):
            raise ObjectStorageError('Unexpected market fields or identity')
        for name, kind in columns:
            value = row[name]
            if value is None:
                continue
            valid = (isinstance(value, (dict, list)) if kind == 'jsonb' else
                     type(value) is int if kind in ('integer', 'bigint') else
                     isinstance(value, str))
            if not valid:
                raise ObjectStorageError('Unexpected market field type')
    return rows


def validate_manifest(value, generation):
    if isinstance(value, str):
        value = json.loads(value)
    if (not isinstance(value, dict)
            or set(value) != {'schema', 'generation', 'counts', 'parts', 'raw_bytes'}
            or value['schema'] != SCHEMA or value['generation'] != generation
            or not isinstance(value['counts'], dict) or set(value['counts']) != set(RELATIONS)
            or not isinstance(value['parts'], list) or len(value['parts']) > MAX_PARTS):
        raise ObjectStorageError('Invalid market manifest')
    counts = dict.fromkeys(RELATIONS, 0)
    size, seen = 0, set()
    for part in value['parts']:
        if (not isinstance(part, dict) or set(part) != {'relation', 'sha256', 'raw_bytes', 'rows'}
                or part['relation'] not in RELATIONS
                or not re.fullmatch('[a-f0-9]{64}', str(part['sha256']))
                or type(part['raw_bytes']) is not int or not 0 < part['raw_bytes'] <= 4_000_000
                or type(part['rows']) is not int or not 0 < part['rows'] <= CHUNK_ROWS
                or part['sha256'] in seen):
            raise ObjectStorageError('Invalid market part')
        seen.add(part['sha256'])
        counts[part['relation']] += part['rows']
        size += part['raw_bytes']
    if (counts != value['counts'] or any(type(n) is not int for n in value['counts'].values())
            or type(value['raw_bytes']) is not int or size != value['raw_bytes']
            or not 0 <= size <= MAX_BYTES):
        raise ObjectStorageError('Incomplete market publication')
    return value


@dataclass(frozen=True)
class MarketSnapshot:
    generation: int
    manifest_digest: str
    rows: dict

    def sql(self, query, params, entries):
        """Bind exactly the static shortlist; leave all original SQL rules intact."""
        if len(entries) > 2000 or not query.startswith('\nwith static_page as ('):
            raise ValueError('Market delivery requires a bounded indexed page')
        keys = {tuple(row[k] for k in KEYS) for row in entries}
        args, ctes = list(params), []
        for table, columns in RELATIONS.items():
            # Asking prices use additional live identity/evidence checks and are
            # archived here, but retain their existing display query.
            if table == 'reference_asking_prices':
                continue
            selected = [self.rows[table][key] for key in keys if key in self.rows[table]]
            args.append(json.dumps(selected, separators=(',', ':')))
            fields = ','.join(f'{name} {kind}' for name, kind in columns)
            ctes.append(f'r2_market_{table} as (select * from jsonb_to_recordset(${len(args)}::jsonb) as p({fields}))')
            query = re.sub(r'\btcg\.' + table + r'\b', 'r2_market_' + table, query)
        return query.replace('\nwith ', '\nwith ' + ',\n'.join(ctes) + ',\n', 1), args


def assemble(manifest, parts):
    validate_manifest(manifest, manifest['generation'])
    rows = {table: {} for table in RELATIONS}
    for part, raw in zip(manifest['parts'], parts, strict=True):
        target = rows[part['relation']]
        for row in parse_part(raw, part):
            key = tuple(row[k] for k in KEYS)
            if key in target:
                raise ObjectStorageError('Duplicate market identity')
            target[key] = row
    return MarketSnapshot(manifest['generation'], manifest_digest(manifest), rows)


async def download(manifest, storage):
    semaphore = asyncio.Semaphore(4)
    async def part_read(part):
        async with semaphore:
            return await _read_with_budget(storage, part['sha256'])
    return assemble(manifest, await asyncio.gather(*(part_read(p) for p in manifest['parts'])))


_current = None
_loading = None


async def _load(manifest, storage):
    global _current
    try:
        candidate = await download(manifest, storage)
        if _current is None or candidate.generation >= _current.generation:
            _current = candidate
        log.warning('CATALOGUE_R2_MARKET_LOADED generation=%s counts=%s', candidate.generation, manifest['counts'])
    except Exception as exc:
        log.warning('CATALOGUE_R2_MARKET_LOAD_FAILED type=%s', type(exc).__name__)


async def read(connection):
    global _loading
    if not enabled('DELIVERY'):
        return None
    try:
        async with connection.transaction():
            state = await connection.fetchrow(STATE_SQL)
        if not state or state['generation'] != state['published_generation']:
            return None
        manifest = validate_manifest(state['manifest'], state['generation'])
        if (_current is not None and _current.generation == state['generation']
                and _current.manifest_digest == manifest_digest(manifest)):
            return _current
        if _loading is None or _loading.done():
            storage = configured_object_storage()
            if storage is not None:
                _loading = asyncio.create_task(_load(manifest, storage))
    except Exception as exc:
        log.warning('CATALOGUE_R2_MARKET_FALLBACK type=%s', type(exc).__name__)
    return None


async def publish(pool, actor, *, storage=None):
    """Verify every byte, row and identity before an atomic generation publish."""
    global _current
    if not isinstance(actor, UUID):
        raise ValueError('Market publication requires an existing administrator')
    storage = storage if storage is not None else configured_object_storage()
    if storage is None:
        raise ObjectStorageError('Private R2 is not configured')
    async with pool.acquire() as lock:
        if not await lock.fetchval('select pg_try_advisory_lock($1)', LOCK_ID):
            return {'status': 'LOCKED'}
        try:
            raw_parts = []
            async with user_connection(pool, actor, str(uuid4()), readonly_snapshot=True) as connection:
                await require_platform_admin(connection)
                state = await connection.fetchrow(STATE_SQL)
                if state is None:
                    raise ObjectStorageError('Market publication migration is missing')
                if state['generation'] == state['published_generation']:
                    manifest = validate_manifest(state['manifest'], state['generation'])
                    if (_current is not None and _current.generation == state['generation']
                            and _current.manifest_digest == manifest_digest(manifest)):
                        return {'status': 'CURRENT', 'generation': state['generation'], 'counts': manifest['counts']}
                else:
                    manifest = dict(schema=SCHEMA, generation=state['generation'],
                                    counts=dict.fromkeys(RELATIONS, 0), parts=[], raw_bytes=0)
                    for table in RELATIONS:
                        offset = 0
                        while True:
                            raw = (await connection.fetchval(chunk_sql(table), CHUNK_ROWS, offset)).encode()
                            count = len(json.loads(raw))
                            if not count:
                                break
                            part = dict(relation=table, sha256=hashlib.sha256(raw).hexdigest(),
                                        rows=count, raw_bytes=len(raw))
                            parse_part(raw, part)
                            manifest['parts'].append(part)
                            manifest['counts'][table] += count
                            manifest['raw_bytes'] += len(raw)
                            if manifest['raw_bytes'] > MAX_BYTES or len(manifest['parts']) > MAX_PARTS:
                                raise ObjectStorageError('Market publication exceeds bounds')
                            raw_parts.append(raw)
                            offset += count
                            if count < CHUNK_ROWS:
                                break
            validate_manifest(manifest, state['generation'])
            if state['generation'] == state['published_generation']:
                _current = await download(manifest, storage)
                return {'status': 'LOADED', 'generation': _current.generation, 'counts': manifest['counts']}
            log.warning('CATALOGUE_R2_MARKET_EXTRACTED generation=%s counts=%s raw_bytes=%s',
                        state['generation'], manifest['counts'], manifest['raw_bytes'])
            semaphore = asyncio.Semaphore(4)
            async def upload(part, raw):
                async with semaphore:
                    receipt = await asyncio.to_thread(storage.put_verified_reference_snapshot, raw)
                    if (receipt.get('verified') is not True or receipt.get('sha256') != part['sha256']
                            or receipt.get('key') != f"{storage.config.prefix}/catalogue-reference-inputs/{part['sha256']}.json.gz"):
                        raise ObjectStorageError('Market storage receipt failed verification')
            # Await every bounded write before release, including on failure.
            outcomes = await asyncio.gather(*(upload(p, r) for p, r in zip(manifest['parts'], raw_parts, strict=True)), return_exceptions=True)
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    raise outcome
            candidate = await download(manifest, storage)
            async with user_connection(pool, actor, str(uuid4())) as connection:
                await require_platform_admin(connection)
                committed = await connection.fetchval('''update tcg_private.live_catalogue_r2_market_publication
                  set published_generation=$1,manifest=$2::jsonb,published_at=now()
                  where singleton and generation=$1 returning published_generation''', manifest['generation'], json.dumps(manifest))
            if committed is None:
                return {'status': 'SOURCE_CHANGED', 'generation': manifest['generation']}
            _current = candidate
            return {'status': 'PUBLISHED', 'generation': committed, 'counts': manifest['counts'],
                    'verified_parts': len(raw_parts), 'raw_bytes': manifest['raw_bytes'], 'source_rows_deleted': 0}
        finally:
            await lock.execute('select pg_advisory_unlock($1)', LOCK_ID)
