import gzip
import hashlib
import io
import pytest
from app.object_storage import ObjectStorageConfig, ObjectStorageError, S3ObjectStorage


class Missing(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}


class Client:
    def __init__(self):
        self.objects = {}
        self.puts = 0
        self.bodies = []
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs['Key'] not in self.objects:
            raise Missing()
        body = io.BytesIO(self.objects[kwargs['Key']])
        self.bodies.append(body)
        return {'Body': body}

    def put_object(self, **kwargs):
        self.puts += 1
        self.objects[kwargs['Key']] = kwargs['Body'].read()


def storage():
    client = Client()
    config = ObjectStorageConfig('https://example.r2.cloudflarestorage.com',
        'private', 'auto', 'key', 'secret')
    return S3ObjectStorage(config, client=client), client


def test_private_reference_roundtrip_and_idempotency():
    store, client = storage()
    raw = '{"schema":"reference-inputs","name":"日本語","value":9007199254740993}'.encode()
    receipt = store.put_verified_reference_snapshot(raw)
    assert receipt['verified'] is True
    assert receipt['sha256'] == hashlib.sha256(raw).hexdigest()
    compressed = client.objects[receipt['key']]
    assert hashlib.sha256(compressed).hexdigest() == receipt['compressed_sha256']
    assert compressed[9] == 255  # deterministic OS-independent gzip header
    assert gzip.decompress(compressed) == raw
    assert store.read_verified_reference_snapshot(receipt['sha256']) == raw
    assert store.put_verified_reference_snapshot(raw) == receipt
    assert client.puts == 1 and all(body.closed for body in client.bodies)
    assert all(call['Key'].startswith('drop-rate/catalogue-reference-inputs/') for call in client.calls)
    with pytest.raises(ObjectStorageError):
        store.signed_media_url(receipt['key'])


@pytest.mark.parametrize('digest', ['', '../secret', 'A'*64, 'g'*64, None, 7, 'a'*63])
def test_reference_reader_accepts_only_independent_hash(digest):
    store, client = storage()
    with pytest.raises(ObjectStorageError):
        store.read_verified_reference_snapshot(digest)
    assert client.calls == []


def test_corruption_never_overwrites_or_returns_other_data():
    store, client = storage()
    raw = b'{"reference":"correct"}'
    receipt = store.put_verified_reference_snapshot(raw)
    client.objects[receipt['key']] = gzip.compress(b'{"reference":"wrong"}', mtime=0)
    with pytest.raises(ObjectStorageError):
        store.read_verified_reference_snapshot(receipt['sha256'])
    with pytest.raises(ObjectStorageError):
        store.put_verified_reference_snapshot(raw)
    assert client.puts == 1
    assert all(body.closed for body in client.bodies)


@pytest.mark.parametrize('bad', [b'not-gzip', b'x'*2_000_001, gzip.compress(b'x'*4_000_001, mtime=0)])
def test_reader_bounds_corruption_and_decompression(bad):
    store, client = storage()
    digest = 'a'*64
    client.objects[store._reference_snapshot_key(digest)] = bad
    with pytest.raises(ObjectStorageError):
        store.read_verified_reference_snapshot(digest)
    assert all(body.closed for body in client.bodies)


@pytest.mark.parametrize('bad', [b'', b'x'*4_000_001, 'not-bytes', None])
def test_writer_rejects_unbounded_inputs_before_network(bad):
    store, client = storage()
    with pytest.raises(ObjectStorageError):
        store.put_verified_reference_snapshot(bad)
    assert client.calls == [] and client.puts == 0


def test_missing_object_is_an_explicit_cache_miss_error():
    store, client = storage()
    with pytest.raises(ObjectStorageError, match='unavailable'):
        store.read_verified_reference_snapshot('a'*64)
