"""Inventory delivery uses only the authorized asset's verified mirror bytes."""
from contextlib import asynccontextmanager
import hashlib
import io
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.object_storage import ObjectStorageConfig, ObjectStorageError, S3ObjectStorage


# The storage reader validates the immutable WebP signature/hash; decoding and
# optimization are already tested at the only permitted mirror producer.
WEBP = b'RIFF\x10\x00\x00\x00WEBPverified-image-bytes'


class ObjectClient:
    def __init__(self, payload=WEBP):
        self.payload = payload
        self.reads = []
        self.body = None

    def get_object(self, **kwargs):
        self.reads.append(kwargs)
        if isinstance(self.payload, Exception):
            raise self.payload
        self.body = io.BytesIO(self.payload)
        return {'Body': self.body}


def storage(client):
    return S3ObjectStorage(ObjectStorageConfig(
        'https://r2.example.test', 'drop-rate-private', 'auto', 'key', 'secret'),
        client=client)


def receipt(payload=WEBP):
    digest = hashlib.sha256(payload).hexdigest()
    return dict(object_key=f'drop-rate/private-media/{digest}.webp',
                content_sha256=digest, size_bytes=len(payload))


def read(storage, row):
    return storage.read_verified_media(row['object_key'],
        expected_sha256=row['content_sha256'], expected_size=row['size_bytes'])


def test_verified_private_bytes_are_returned_without_signed_links():
    client = ObjectClient()
    assert read(storage(client), receipt()) == WEBP
    assert client.reads == [{'Bucket': 'drop-rate-private', 'Key': receipt()['object_key']}]
    assert client.body.closed


@pytest.mark.parametrize('change', [
    {'object_key': 'drop-rate/exports/secret.json'},
    {'object_key': 'drop-rate/private-media/' + 'a' * 64 + '.webp'},
    {'content_sha256': 'not-a-digest'}, {'size_bytes': 0},
    {'size_bytes': True}, {'size_bytes': 10_000_001},
])
def test_private_reader_rejects_untrusted_object_identity_before_io(change):
    client = ObjectClient()
    with pytest.raises(ObjectStorageError):
        read(storage(client), dict(receipt(), **change))
    assert client.reads == []


@pytest.mark.parametrize('payload', [WEBP + b'x', WEBP[:-1], b'x' * len(WEBP), TimeoutError()])
def test_private_reader_rejects_oversized_truncated_corrupt_and_failed_objects(payload):
    client = ObjectClient(payload)
    with pytest.raises(ObjectStorageError):
        read(storage(client), receipt())
    assert client.body is None or client.body.closed


def test_even_hash_matching_non_webp_bytes_are_rejected():
    payload = b'<svg>not a verified image</svg>'
    with pytest.raises(ObjectStorageError):
        read(storage(ObjectClient(payload)), receipt(payload))


@pytest.fixture
def delivery(monkeypatch):
    from app import api, r2_media

    owner_id, inventory_id = uuid4(), uuid4()
    asset = dict(id=uuid4(), scope='CANONICAL_CARD', approval_status='APPROVED',
                 source_provider='TCGdex', shopify_cdn_url=None,
                 public_source_url='https://assets.tcgdex.net/ja/SV/SV5a/078/high.webp')
    mirror = dict(receipt(), media_asset_id=asset['id'],
                  source_url=asset['public_source_url'], source_provider='TCGdex',
                  source_type='LICENSED_PROVIDER')
    state = SimpleNamespace(assets=[asset], mirrors=[mirror], authorized=True,
                            query_count=0, source_requests=[], source_payload=(b'provider', 'image/png'))
    client = ObjectClient()

    class Connection:
        async def fetchrow(self, sql, *args):
            assert 'i.owner_id = $2' in sql
            assert args == (inventory_id, owner_id)
            return dict(id=inventory_id, catalogue_id=uuid4(), language='Japanese') if state.authorized else None

        async def fetch(self, sql, *args):
            state.query_count += 1
            assert 'mirror.source_url=m.public_source_url' in sql
            for clause in ("m.approval_status='APPROVED'", "m.rights_status='VERIFIED'",
                           "m.rights_tier='STOREFRONT_ALLOWED'", "m.source_status='ACTIVE'",
                           'm.revoked_at is null', 'mirror.verified_at is not null'):
                assert clause in sql
            assert args[0] == [a['id'] for a in state.assets
                               if a['scope'].startswith('CANONICAL') and a['approval_status'] == 'APPROVED']
            return state.mirrors

    @asynccontextmanager
    async def connection(*args):
        yield Connection()

    async def current_owner(connection):
        return {'id': owner_id}

    async def assets(connection, ids):
        assert state.authorized and ids == [inventory_id]
        return state.assets

    async def inline_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    class HTTPClient:
        def __init__(self, **kwargs):
            assert kwargs['follow_redirects'] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    async def provider(client, url):
        state.source_requests.append(url)
        return state.source_payload

    monkeypatch.setenv('TCG_R2_MEDIA_DELIVERY_ENABLED', 'true')
    monkeypatch.setattr(api, 'user_connection', connection)
    monkeypatch.setattr(api, '_owner', current_owner)
    monkeypatch.setattr(api, 'shared_media_assets', assets)
    monkeypatch.setattr(api.httpx, 'AsyncClient', HTTPClient)
    monkeypatch.setattr(api, '_fetch_inventory_image', provider)
    monkeypatch.setattr(r2_media, 'configured_object_storage', lambda: storage(client))
    monkeypatch.setattr(r2_media.asyncio, 'to_thread', inline_thread)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                              state=SimpleNamespace(request_id='image-test'), headers={})
    state.call = lambda: api.inventory_card_image(inventory_id, request,
        SimpleNamespace(user_id=uuid4()))
    state.client = client
    return state


@pytest.mark.asyncio
async def test_inventory_uses_exact_verified_mirror_before_provider(delivery):
    response = await delivery.call()
    assert response.body == WEBP and response.media_type == 'image/webp'
    assert delivery.source_requests == [] and len(delivery.client.reads) == 1
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert response.headers['x-drop-rate-media-id'] == str(delivery.assets[0]['id'])


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['missing', 'disabled', 'unconfigured', 'outage', 'corrupt'])
async def test_missing_or_unavailable_mirror_keeps_original_provider_fallback(delivery, monkeypatch, reason):
    from app import r2_media

    if reason == 'missing':
        delivery.mirrors = []
    elif reason == 'disabled':
        monkeypatch.delenv('TCG_R2_MEDIA_DELIVERY_ENABLED')
    elif reason == 'unconfigured':
        monkeypatch.setattr(r2_media, 'configured_object_storage', lambda: None)
    else:
        delivery.client.payload = TimeoutError() if reason == 'outage' else b'broken'
    response = await delivery.call()
    assert response.body == b'provider' and response.media_type == 'image/png'
    assert delivery.source_requests == [delivery.assets[0]['public_source_url']]


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'source_url': 'https://assets.tcgdex.net/different-printing.webp'},
    {'source_provider': 'Punk Records'}, {'media_asset_id': uuid4()},
    {'source_type': 'FOUNDER_UPLOAD'},
])
async def test_stale_or_mismatched_mirror_is_not_read(delivery, change):
    delivery.mirrors[0].update(change)
    assert (await delivery.call()).body == b'provider'
    assert delivery.client.reads == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'scope': 'INVENTORY_ITEM'}, {'approval_status': 'PENDING'},
    {'public_source_url': 'https://assets.tcgdex.net.evil.test/card.webp'},
])
async def test_unapproved_or_untrusted_source_cannot_gain_a_mirror(delivery, change):
    delivery.assets[0].update(change)
    delivery.mirrors[0]['source_url'] = delivery.assets[0]['public_source_url']
    # A legitimate Shopify fallback demonstrates the unsafe mirror is skipped
    # while leaving the pre-existing source host guard in control.
    delivery.assets[0]['shopify_cdn_url'] = 'https://cdn.shopify.com/s/files/1/photo.png'
    assert (await delivery.call()).body == b'provider'
    assert delivery.client.reads == []


@pytest.mark.asyncio
async def test_owner_photo_stays_ahead_of_shared_catalogue_mirror(delivery):
    photo = dict(delivery.assets[0], id=uuid4(), scope='INVENTORY_ITEM', approval_status='PENDING',
                 public_source_url='https://cdn.shopify.com/s/files/1/owner.png')
    delivery.assets.insert(0, photo)
    assert (await delivery.call()).body == b'provider'
    assert delivery.source_requests == [photo['public_source_url']]
    assert delivery.client.reads == []


@pytest.mark.asyncio
async def test_other_owners_inventory_cannot_query_or_read_mirrors(delivery):
    delivery.authorized = False
    with pytest.raises(HTTPException) as denied:
        await delivery.call()
    assert denied.value.status_code == 404
    assert delivery.query_count == 0 and delivery.client.reads == []
    assert delivery.source_requests == []
