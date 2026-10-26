"""Restore-verified private R2 history archives; guarded SQL alone permits cleanup."""
from __future__ import annotations
import asyncio
import gzip
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from .access_control import require_platform_admin
from .object_storage import ObjectStorageError, configured_object_storage, sha256_file

ARCHIVE_LOCK = 847220092
FORMAT = "drop-rate-reference-history-postgres-json-gzip-v2"
FIELDS = ("id", "reference_kind", "provider", "system_code", "language", "provider_id",
          "quotes", "quote_digest", "market_value_minor", "market_value_high_minor",
          "pricing_updated_at", "recorded_at")
MAX_LINE_BYTES = 1_000_000
RESTORE_BATCH_ROWS = 200
RESTORE_BATCH_BYTES = 2_000_000
EXPORT_SQL = "select row_to_json(h)::text as canonical_row from tcg.reference_market_history h order by h.id"
RESTORE_TABLE_SQL = """create temporary table reference_history_restore_check (
 id uuid primary key,reference_kind text not null check(reference_kind in ('CARD','SEALED')),
 provider text not null,system_code text not null,language text not null,provider_id text not null,
 quotes jsonb not null check(jsonb_typeof(quotes)='array'),quote_digest text not null,
 market_value_minor bigint,market_value_high_minor bigint,pricing_updated_at timestamptz,
 recorded_at timestamptz not null) on commit drop"""
RESTORE_INSERT_SQL = """insert into pg_temp.reference_history_restore_check
 select * from json_populate_recordset(null::pg_temp.reference_history_restore_check,$1::json)"""
RESTORE_CHECK_SQL = """select id::text as id,row_to_json(h)::text as canonical_row,
 md5(quotes::text)=quote_digest as quote_matches from pg_temp.reference_history_restore_check h order by id"""
CLEANUP_SQL = """select tcg_private.archive_verified_reference_history_r2(
 $1::text,$2::bigint,$3::text,$4::text,$5::text,$6::text,$7::text,$8::text,$9::text,$10::timestamptz)"""


def _limits(max_rows, max_raw_bytes):
    if type(max_rows) is not int or not 1 <= max_rows <= 100_000:
        raise ValueError("Archive row limit must be between 1 and 100000")
    if type(max_raw_bytes) is not int or not 1 <= max_raw_bytes <= 128_000_000:
        raise ValueError("Archive byte limit must be between 1 and 128000000")


def _reject_constant(_):
    raise ObjectStorageError("Non-finite JSON in history")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ObjectStorageError("Duplicate JSON field in history")
        result[key] = value
    return result


def validate_row(line: bytes) -> dict:
    try:
        row = json.loads(line, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError("schema")
        if not isinstance(row['id'], str) or str(UUID(row['id'])) != row['id']:
            raise ValueError("id")
        if row['reference_kind'] not in {'CARD', 'SEALED'}:
            raise ValueError("kind")
        for field in ('provider', 'system_code', 'language', 'provider_id'):
            if not isinstance(row[field], str) or not row[field]:
                raise ValueError("identity")
        if not isinstance(row['quotes'], list) or any(not isinstance(q, dict) for q in row['quotes']):
            raise ValueError("quotes")
        if not isinstance(row['quote_digest'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['quote_digest']):
            raise ValueError("digest")
        for field in ('market_value_minor', 'market_value_high_minor'):
            value = row[field]
            if value is not None and (type(value) is not int or not -(2**63) <= value < 2**63):
                raise ValueError("money")
        for field in ('pricing_updated_at', 'recorded_at'):
            value = row[field]
            if value is None and field == 'pricing_updated_at':
                continue
            if not isinstance(value, str):
                raise ValueError("timestamp")
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("timezone")
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
        raise ObjectStorageError("Invalid reference-history record") from exc
    return row


async def _authorize(conn, actor, request_id):
    await conn.execute("select set_config('tcg.user_id',$1,true)", str(actor))
    await conn.execute("select set_config('tcg.request_id',$1,true)", request_id)
    await conn.execute("set local timezone='UTC'")
    await conn.execute("set local datestyle='ISO,YMD'")
    await require_platform_admin(conn)


async def export_snapshot(pool, actor, target, *, max_rows, max_raw_bytes):
    _limits(max_rows, max_raw_bytes)
    root, raw_digest = hashlib.sha256(), hashlib.sha256()
    count = raw_size = 0
    previous = None
    with target.open('xb') as output:
        with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed:
            async with pool.acquire(timeout=15) as conn:
                async with conn.transaction(isolation='repeatable_read', readonly=True):
                    await _authorize(conn, actor, 'r2-history-export')
                    async for record in conn.cursor(EXPORT_SQL, prefetch=RESTORE_BATCH_ROWS):
                        line = record['canonical_row'].encode('utf-8')
                        if len(line) + 1 > MAX_LINE_BYTES:
                            raise ObjectStorageError('History record exceeds archive line limit')
                        row = validate_row(line)
                        if previous is not None and row['id'] <= previous:
                            raise ObjectStorageError('History IDs must be unique and ordered')
                        previous = row['id']
                        count += 1
                        raw_size += len(line) + 1
                        if count > max_rows or raw_size > max_raw_bytes:
                            raise ObjectStorageError('History exceeds bounded archive limits')
                        root.update(hashlib.sha256(line).hexdigest().encode('ascii'))
                        raw_digest.update(line + b'\n')
                        compressed.write(line + b'\n')
    digest, size = sha256_file(target)
    return {'schema': FORMAT, 'row_count': count, 'raw_bytes': raw_size,
            'ndjson_sha256': raw_digest.hexdigest(), 'content_root_sha256': root.hexdigest(),
            'gzip_sha256': digest, 'gzip_bytes': size, 'full_table_snapshot': True}


async def _restore_batch(pool, actor, lines):
    """Each typed restore uses <=200 rows, then rolls back its temp table."""
    expected = {json.loads(line)['id']: line.decode('utf-8') for line in lines}
    async with pool.acquire(timeout=15) as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            await _authorize(conn, actor, 'r2-history-restore')
            await conn.execute(RESTORE_TABLE_SQL)
            # Preserve numeric precision and canonical bytes; do not reserialize JSON.
            payload = '[' + ','.join(line.decode('utf-8') for line in lines) + ']'
            await conn.execute(RESTORE_INSERT_SQL, payload)
            restored = await conn.fetch(RESTORE_CHECK_SQL)
            if len(restored) != len(lines):
                raise ObjectStorageError('PostgreSQL restored count differs')
            for row in restored:
                if (row['id'] not in expected or row['canonical_row'] != expected[row['id']]
                        or row['quote_matches'] is not True):
                    raise ObjectStorageError('PostgreSQL restored history differs from archive')
        finally:
            await transaction.rollback()


async def verify_restore(pool, actor, downloaded, manifest, *, max_rows, max_raw_bytes):
    _limits(max_rows, max_raw_bytes)
    if manifest.get('schema') != FORMAT:
        raise ObjectStorageError('Unsupported archive schema')
    if sha256_file(downloaded) != (manifest['gzip_sha256'], manifest['gzip_bytes']):
        raise ObjectStorageError('Downloaded archive checksum differs')
    root, raw_digest = hashlib.sha256(), hashlib.sha256()
    count = raw_size = 0
    previous = None
    batch = []
    batch_bytes = 0
    try:
        with gzip.open(downloaded, 'rb') as stream:
            while True:
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_LINE_BYTES or not raw.endswith(b'\n'):
                    raise ObjectStorageError('Archive line length or terminator is invalid')
                line = raw[:-1]
                row = validate_row(line)
                if previous is not None and row['id'] <= previous:
                    raise ObjectStorageError('Archive IDs must be unique and ordered')
                previous = row['id']
                count += 1
                raw_size += len(raw)
                if count > max_rows or raw_size > max_raw_bytes:
                    raise ObjectStorageError('Downloaded archive exceeds bounded limits')
                root.update(hashlib.sha256(line).hexdigest().encode('ascii'))
                raw_digest.update(raw)
                if batch and batch_bytes + len(raw) > RESTORE_BATCH_BYTES:
                    await _restore_batch(pool, actor, batch)
                    batch = []
                    batch_bytes = 0
                batch.append(line)
                batch_bytes += len(raw)
                if len(batch) == RESTORE_BATCH_ROWS:
                    await _restore_batch(pool, actor, batch)
                    batch = []
                    batch_bytes = 0
        if batch:
            await _restore_batch(pool, actor, batch)
    except (OSError, EOFError) as exc:
        raise ObjectStorageError('Downloaded archive could not be decompressed') from exc
    if (count != manifest['row_count'] or raw_size != manifest['raw_bytes']
            or root.hexdigest() != manifest['content_root_sha256']
            or raw_digest.hexdigest() != manifest['ndjson_sha256']):
        raise ObjectStorageError('Restored archive does not match manifest')


async def archive_reference_history(pool, actor: UUID, *, cleanup=False,
                                    max_rows=100_000, max_raw_bytes=128_000_000, store=None):
    _limits(max_rows, max_raw_bytes)
    if type(cleanup) is not bool or not isinstance(actor, UUID):
        raise ValueError('Archive needs UUID actor and boolean cleanup')
    store = store if store is not None else configured_object_storage()
    if store is None:
        return {'status': 'DISABLED', 'rows_archived': 0, 'bytes_reclaimed': 0}
    # Shared with bulk pricing; short transactions never span storage requests.
    async with pool.acquire(timeout=15) as lock:
        if not await lock.fetchval('select pg_try_advisory_lock($1)', ARCHIVE_LOCK):
            return {'status': 'BUSY', 'rows_archived': 0, 'bytes_reclaimed': 0}
        try:
            with tempfile.TemporaryDirectory(prefix='drop-rate-r2-history-') as directory:
                root = Path(directory)
                archive = root / 'reference-history.ndjson.gz'
                manifest = await export_snapshot(pool, actor, archive, max_rows=max_rows, max_raw_bytes=max_raw_bytes)
                if manifest['row_count'] == 0:
                    return {'status': 'NO_HISTORY', 'rows_archived': 0, 'bytes_reclaimed': 0}
                receipt = await asyncio.to_thread(store.put_verified_file, archive,
                    category='reference-history', content_type='application/gzip')
                downloaded = root / 'downloaded.ndjson.gz'
                await asyncio.to_thread(store.download_verified_file, receipt['key'], downloaded,
                    expected_sha256=manifest['gzip_sha256'], expected_size=manifest['gzip_bytes'])
                await verify_restore(pool, actor, downloaded, manifest, max_rows=max_rows, max_raw_bytes=max_raw_bytes)
                verified_at = datetime.now(timezone.utc)
                # Timestamp belongs in DB receipt; deterministic manifest avoids retry duplicates.
                manifest.update(archive_object=receipt, restoration_verified=True,
                                storage_endpoint=store.config.endpoint, storage_bucket=store.config.bucket,
                                restoration_method='POSTGRES_TEMP_TABLE_EVERY_FIELD_V1')
                manifest_path = root / 'reference-history.manifest.json'
                manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
                manifest_path.write_bytes(manifest_bytes)
                manifest_receipt = await asyncio.to_thread(store.put_verified_file, manifest_path,
                    category='reference-history', content_type='application/json')
                manifest_download = root / 'downloaded.manifest.json'
                await asyncio.to_thread(store.download_verified_file, manifest_receipt['key'], manifest_download,
                    expected_sha256=manifest_receipt['sha256'], expected_size=manifest_receipt['size_bytes'])
                if manifest_download.read_bytes() != manifest_bytes:
                    raise ObjectStorageError('Downloaded manifest differs from verified history')
                archive_id = 'r2-reference-history-' + manifest['content_root_sha256']
                result = {'archive_id': archive_id, 'status': 'BYTES_AND_RESTORE_VERIFIED', 'verified_rows': manifest['row_count'],
                          'content_root_sha256': manifest['content_root_sha256'], 'restoration_verified': True,
                          'rows_archived': 0, 'bytes_reclaimed': 0, 'restore_verified_at': verified_at.isoformat()}
                if not cleanup:
                    return result
                async with pool.acquire(timeout=15) as conn:
                    async with conn.transaction(isolation='read_committed'):
                        await _authorize(conn, actor, archive_id)
                        raw = await conn.fetchval(CLEANUP_SQL, archive_id, manifest['row_count'],
                            manifest['content_root_sha256'], receipt['key'], manifest_receipt['key'],
                            manifest['gzip_sha256'], manifest_receipt['sha256'],
                            store.config.endpoint, store.config.bucket, verified_at)
                        completed = json.loads(raw) if isinstance(raw, str) else raw
                        if (not isinstance(completed, dict) or completed.get('status') not in {'ARCHIVED', 'ALREADY_ARCHIVED'}
                                or completed.get('rows_archived') != manifest['row_count']
                                or type(completed.get('bytes_reclaimed')) is not int or completed['bytes_reclaimed'] < 0):
                            raise ObjectStorageError('Invalid database archive receipt')
                return {**result, 'status': completed['status'], 'rows_archived': completed['rows_archived'],
                        'bytes_reclaimed': completed['bytes_reclaimed']}
        finally:
            await lock.execute('select pg_advisory_unlock($1)', ARCHIVE_LOCK)


