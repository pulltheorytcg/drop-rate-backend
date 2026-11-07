"""Archive corruption and invalid receipts must never authorize history cleanup."""
import gzip
import hashlib
import io
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
from app import reference_history_archive as archive
from app.object_storage import ObjectStorageConfig, ObjectStorageError, S3ObjectStorage


def row(**changes):
    value = dict(id='00000000-0000-0000-0000-000000000001', reference_kind='CARD',
        provider='TCGdex', system_code='POKEMON_TCG', language='Japanese', provider_id='set-001',
        quotes=[], quote_digest='d751713988987e9331980363e24189ce', market_value_minor=100,
        market_value_high_minor=150, pricing_updated_at=None, recorded_at='2026-10-26T12:00:00+00:00')
    value.update(changes)
    return value


def line(value=None):
    return json.dumps(value or row(), separators=(',', ':'), ensure_ascii=False).encode()


@pytest.mark.parametrize('changes', [
    {'id': 'wrong'}, {'id': 1}, {'reference_kind': 'OWNER'}, {'provider': ''},
    {'system_code': None}, {'language': 3}, {'provider_id': []}, {'quotes': {}},
    {'quotes': [True]}, {'quote_digest': 'invalid'}, {'market_value_minor': True},
    {'market_value_minor': 1.5}, {'market_value_high_minor': 2**63},
    {'recorded_at': None}, {'recorded_at': '2026-10-26T12:00:00'},
    {'pricing_updated_at': 'not-a-date'}, {'extra': 'unreviewed'},
])
def test_invalid_closed_schema_is_rejected(changes):
    with pytest.raises(ObjectStorageError, match='Invalid'):
        archive.validate_row(line(row(**changes)))


def test_valid_unicode_numeric_history_is_not_rewritten():
    raw = line(row(provider_id='\u30ab\u30fc\u30c9', quotes=[{'number': 9007199254740993}]))
    assert archive.validate_row(raw)['quotes'][0]['number'] == 9007199254740993


@pytest.mark.parametrize('raw', [b'{"id":"one","id":"two"}', b'{"value":NaN}', b'{"value":Infinity}'])
def test_duplicate_and_nonfinite_json_rejected(raw):
    with pytest.raises(ObjectStorageError):
        archive.validate_row(raw)


@pytest.mark.parametrize('rows,size', [(True, 1), (0, 1), (100001, 1), (1, 0), (1, True), (1, 128000001)])
def test_worker_bounds_cannot_be_disabled(rows, size):
    with pytest.raises(ValueError):
        archive._limits(rows, size)


def config():
    return ObjectStorageConfig('https://example.r2.cloudflarestorage.com', 'private', 'auto', 'key', 'secret')


class Body(io.BytesIO):
    closed_seen = False
    def close(self):
        self.closed_seen = True
        super().close()


class DownloadClient:
    def __init__(self, payload):
        self.body = Body(payload)
        self.calls = []
    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        return {'Body': self.body}


def test_download_uses_actual_remote_bytes_and_private_key(tmp_path):
    payload = b'archive-data'
    digest = hashlib.sha256(payload).hexdigest()
    client = DownloadClient(payload)
    store = S3ObjectStorage(config(), client=client)
    target = tmp_path / 'download.gz'
    store.download_verified_file(f'drop-rate/reference-history/{digest}.ndjson.gz', target,
                                expected_sha256=digest, expected_size=len(payload))
    assert target.read_bytes() == payload
    assert client.body.closed_seen
    assert client.calls[0]['Bucket'] == 'private'


@pytest.mark.parametrize('payload', [b'x', b'bad-content', b'archive-data-with-extra-bytes'])
def test_remote_corruption_or_truncation_refused(tmp_path, payload):
    expected = b'archive-data'
    digest = hashlib.sha256(expected).hexdigest()
    client = DownloadClient(payload)
    store = S3ObjectStorage(config(), client=client)
    with pytest.raises(ObjectStorageError):
        store.download_verified_file(f'drop-rate/reference-history/{digest}.ndjson.gz', tmp_path / 'x.gz',
                                    expected_sha256=digest, expected_size=len(expected))
    assert client.body.closed_seen


@pytest.mark.parametrize('key', ['../secret', 'drop-rate/private-media/{sha}.webp',
                               'other/reference-history/{sha}.ndjson.gz',
                               'drop-rate/reference-history/{sha}.exe'])
def test_download_cannot_read_other_private_objects(tmp_path, key):
    digest = hashlib.sha256(b'a').hexdigest()
    client = DownloadClient(b'a')
    store = S3ObjectStorage(config(), client=client)
    with pytest.raises(ObjectStorageError):
        store.download_verified_file(key.format(sha=digest), tmp_path / 'x.gz', expected_sha256=digest, expected_size=1)
    assert client.calls == []


def make_archive(path, values):
    raw = b''.join(line(value) + b'\n' for value in values)
    data = gzip.compress(raw, mtime=0)
    path.write_bytes(data)
    root = hashlib.sha256()
    for item in raw.splitlines():
        root.update(hashlib.sha256(item).hexdigest().encode())
    return {'schema': archive.FORMAT, 'row_count': len(values), 'raw_bytes': len(raw),
            'gzip_sha256': hashlib.sha256(data).hexdigest(), 'gzip_bytes': len(data),
            'ndjson_sha256': hashlib.sha256(raw).hexdigest(), 'content_root_sha256': root.hexdigest()}


@pytest.mark.asyncio
async def test_restore_bounds_batches_and_passes_exact_raw_json(monkeypatch, tmp_path):
    target = tmp_path / 'input.gz'
    values = [row(id=str(UUID(int=i))) for i in range(1, 402)]
    manifest = make_archive(target, values)
    batches = []
    async def restore(_pool, _actor, lines):
        batches.append(lines)
    monkeypatch.setattr(archive, '_restore_batch', restore)
    await archive.verify_restore(object(), uuid4(), target, manifest, max_rows=500, max_raw_bytes=1_000_000)
    assert [len(batch) for batch in batches] == [200, 200, 1]
    assert batches[0][0] == line(values[0])


@pytest.mark.asyncio
@pytest.mark.parametrize('ids', [[1, 1], [2, 1]])
async def test_restore_rejects_duplicate_or_reordered_ids(monkeypatch, tmp_path, ids):
    target = tmp_path / 'input.gz'
    manifest = make_archive(target, [row(id=str(UUID(int=i))) for i in ids])
    with pytest.raises(ObjectStorageError, match='unique and ordered'):
        await archive.verify_restore(object(), uuid4(), target, manifest, max_rows=10, max_raw_bytes=10000)


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('row_count', 9), ('raw_bytes', 9),
    ('ndjson_sha256', '0'*64), ('content_root_sha256', '0'*64)])
async def test_restore_rejects_manifest_mismatch(monkeypatch, tmp_path, field, value):
    target = tmp_path / 'input.gz'
    manifest = make_archive(target, [row()])
    async def restore(*args):
        pass
    monkeypatch.setattr(archive, '_restore_batch', restore)
    manifest[field] = value
    with pytest.raises(ObjectStorageError, match='match manifest'):
        await archive.verify_restore(object(), uuid4(), target, manifest, max_rows=10, max_raw_bytes=10000)


@pytest.mark.asyncio
async def test_failed_postgres_restore_propagates(monkeypatch, tmp_path):
    target = tmp_path / 'input.gz'
    manifest = make_archive(target, [row()])
    async def restore(*args):
        raise ObjectStorageError('PostgreSQL restored history differs from archive')
    monkeypatch.setattr(archive, '_restore_batch', restore)
    with pytest.raises(ObjectStorageError, match='PostgreSQL'):
        await archive.verify_restore(object(), uuid4(), target, manifest, max_rows=10, max_raw_bytes=10000)


@pytest.mark.asyncio
async def test_failed_verification_never_reaches_cleanup_and_unlocks(monkeypatch, tmp_path):
    calls = []
    class Lock:
        async def fetchval(self, sql, *args):
            calls.append(sql)
            assert 'pg_try_advisory_lock' in sql
            return True
        async def execute(self, sql, *args):
            calls.append(sql)
    class Pool:
        @asynccontextmanager
        async def acquire(self, **kwargs):
            yield Lock()
    class Store:
        def put_verified_file(self, path, **kwargs):
            return {'key': 'key', 'size_bytes': 1, 'sha256': '0'*64}
        def download_verified_file(self, *args, **kwargs):
            raise ObjectStorageError('Downloaded archive failed SHA-256 verification')
    async def export(*args, **kwargs):
        return {'row_count': 1, 'gzip_sha256': '0'*64, 'gzip_bytes': 1}
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(archive, 'export_snapshot', export)
    monkeypatch.setattr(archive.asyncio, 'to_thread', inline)
    with pytest.raises(ObjectStorageError, match='SHA-256'):
        await archive.archive_reference_history(Pool(), uuid4(), cleanup=True, store=Store())
    assert len(calls) == 2
    assert 'pg_advisory_unlock' in calls[-1]
    assert not any('archive_verified_reference_history_r2' in sql for sql in calls)


@pytest.mark.asyncio
async def test_restore_byte_cap_bounds_large_rows(monkeypatch, tmp_path):
    target = tmp_path / 'large.gz'
    values = [row(id=str(UUID(int=i)), quotes=[{'source_payload': 'x' * 750_000}]) for i in range(1, 4)]
    manifest = make_archive(target, values)
    batches = []
    async def restore(_pool, _actor, lines):
        batches.append((len(lines), sum(len(item) + 1 for item in lines)))
    monkeypatch.setattr(archive, '_restore_batch', restore)
    await archive.verify_restore(object(), uuid4(), target, manifest, max_rows=10, max_raw_bytes=4_000_000)
    assert [count for count, _ in batches] == [2, 1]
    assert all(size <= archive.RESTORE_BATCH_BYTES for _, size in batches)

@pytest.mark.asyncio
@pytest.mark.parametrize('mismatch', ['fields', 'quote_digest', 'count'])
async def test_typed_restore_mismatch_rolls_back_temp_table(monkeypatch, mismatch):
    calls = []
    original = line()
    class Transaction:
        async def start(self):
            calls.append('start')
        async def rollback(self):
            calls.append('rollback')
    class Connection:
        def transaction(self):
            return Transaction()
        async def execute(self, sql, *args):
            calls.append(sql)
            if sql == archive.RESTORE_INSERT_SQL:
                assert args[0] == '[' + original.decode() + ']'
        async def fetch(self, sql):
            assert sql == archive.RESTORE_CHECK_SQL
            if mismatch == 'count':
                return []
            return [{'id': row()['id'], 'canonical_row': original.decode() + (' ' if mismatch == 'fields' else ''),
                     'quote_matches': mismatch != 'quote_digest'}]
    class Pool:
        @asynccontextmanager
        async def acquire(self, **kwargs):
            yield Connection()
    async def authorize(*args):
        pass
    monkeypatch.setattr(archive, 'require_platform_admin', authorize)
    with pytest.raises(ObjectStorageError, match='PostgreSQL'):
        await archive._restore_batch(Pool(), uuid4(), [original])
    assert calls[-1] == 'rollback'
    assert "set local timezone='UTC'" in calls
    assert "set local datestyle='ISO,YMD'" in calls
