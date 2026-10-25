"""R2 catalogue delivery is an optional, rights-gated byte mirror."""
from __future__ import annotations

import io
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from app import catalogue_browser, r2_media
from app.object_storage import ObjectStorageConfig, ObjectStorageError, S3ObjectStorage
from app.recognition_images import ReferenceImagePayload
from app.automation_commands import MirrorApprovedMediaCommand
from pydantic import ValidationError


class NoSuchKey(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}


class FakeR2:
    def __init__(self):
        self.objects = {}
        self.puts = 0

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise NoSuchKey()
        return {'Body': io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, ContentType, ContentDisposition, CacheControl, Metadata):
        assert Bucket == 'drop-rate-private'
        assert ContentType == 'image/webp' and ContentDisposition == 'inline'
        assert CacheControl.startswith('private')
        self.objects[Key] = Body.read()
        self.puts += 1

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        assert operation == 'get_object' and Params['Bucket'] == 'drop-rate-private'
        assert ExpiresIn == 3600
        return f"https://account.eu.r2.cloudflarestorage.com/drop-rate-private/{Params['Key']}?X-Amz-Signature=test"


@pytest.fixture
def store():
    cfg = ObjectStorageConfig('https://account.eu.r2.cloudflarestorage.com',
                              'drop-rate-private','auto','key','secret')
    fake = FakeR2()
    return S3ObjectStorage(cfg, client=fake), fake


def _image() -> bytes:
    canvas = Image.new('RGB',(500,700),'#ce4428')
    output = io.BytesIO()
    canvas.save(output,format='PNG')
    return output.getvalue()


def test_private_media_roundtrip_is_idempotent_and_signed_by_exact_key(store):
    storage, fake = store
    content = r2_media.optimized_media_bytes(ReferenceImagePayload('image/png',_image()))
    receipt = storage.put_verified_media(content)
    assert receipt['verified'] and receipt['key'].startswith('drop-rate/private-media/')
    assert storage.put_verified_media(content) == receipt
    assert fake.puts == 1
    url = storage.signed_media_url(receipt['key'])
    assert url.startswith('https://account.eu.r2.cloudflarestorage.com/')
    assert 'X-Amz-Signature=' in url
    for key in ('../exports/latest.ndjson.gz','drop-rate/private-media/../../secret',
                'drop-rate/exports/' + receipt['sha256'] + '.webp'):
        with pytest.raises(ObjectStorageError,match='unrecognised'):
            storage.signed_media_url(key)
    with pytest.raises(ObjectStorageError,match='lifetime'):
        storage.signed_media_url(receipt['key'],expires_seconds=86400)


def test_preexisting_corrupt_mirror_is_never_overwritten(store):
    storage, fake = store
    data = r2_media.optimized_media_bytes(ReferenceImagePayload('image/png',_image()))
    receipt = storage.put_verified_media(data)
    fake.objects[receipt['key']] = b'corrupt'
    with pytest.raises(ObjectStorageError,match='SHA-256'):
        storage.put_verified_media(data)
    assert fake.puts == 1
    with pytest.raises(ObjectStorageError,match='validated WebP'):
        storage.put_verified_media(b'<svg>unsafe</svg>')


@pytest.mark.parametrize(('host','provider','source_type','accepted'),[
    ('assets.tcgdex.net','TCGdex','LICENSED_PROVIDER',True),
    ('en.onepiece-cardgame.com','Punk Records','OFFICIAL_PROVIDER',True),
    ('en.onepiece-cardgame.com.evil.test','Punk Records','OFFICIAL_PROVIDER',False),
    ('169.254.169.254','TCGdex','LICENSED_PROVIDER',False),
    ('cdn.shopify.com','Bandai Official','OFFICIAL_PROVIDER',False),
    ('assets.tcgdex.net','Punk Records','LICENSED_PROVIDER',False),
    ('www.dbs-cardgame.com','Bandai Official','OFFICIAL_PROVIDER',True),
    ('assets.tcgdex.net','TCGdex','FOUNDER_UPLOAD',False),
    ('assets.tcgdex.net','Unverified Provider','LICENSED_PROVIDER',False),
])
def test_mirror_source_must_be_rights_allowlisted(host,provider,source_type,accepted):
    assert r2_media.approved_source_url(f'https://{host}/card.png',provider,source_type) is accepted
    if accepted:
        assert not r2_media.approved_source_url(f'https://{host}:9000/card.png',provider,source_type)


def test_signed_row_strips_private_object_key_and_falls_back(monkeypatch,store):
    storage, _ = store
    key='drop-rate/private-media/'+'a'*64+'.webp'
    monkeypatch.setattr(r2_media,'configured_object_storage',lambda:storage)
    row={'name':'Exact Nami','display_image_url':'https://assets.tcgdex.net/card.png',
         'r2_object_key':key}
    monkeypatch.delenv('TCG_R2_MEDIA_DELIVERY_ENABLED',raising=False)
    assert 'r2_image_url' not in r2_media.with_signed_mirror(row)
    monkeypatch.setenv('TCG_R2_MEDIA_DELIVERY_ENABLED','true')
    mirrored=r2_media.with_signed_mirror(row)
    assert 'r2_object_key' not in mirrored
    assert mirrored['r2_image_url'].startswith('https://account.eu.r2.cloudflarestorage.com/')
    assert mirrored['display_image_url']==row['display_image_url']
    monkeypatch.setattr(r2_media,'configured_object_storage',lambda:None)
    assert 'r2_image_url' not in r2_media.with_signed_mirror(row)


@pytest.mark.asyncio
async def test_verified_mirror_batch_checks_source_and_rights_again_after_remote_io(monkeypatch,store):
    storage,_=store
    monkeypatch.setattr(r2_media,'configured_object_storage',lambda:storage)
    scanned=[]
    candidate={'id':uuid4(),'public_source_url':'https://assets.tcgdex.net/en/base/card.png',
               'source_provider':'TCGdex','source_type':'LICENSED_PROVIDER'}

    class Connection:
        async def fetch(self,sql,*args):
            assert 'approval_status=\'APPROVED\'' in sql and 'rights_status=\'VERIFIED\'' in sql
            return [candidate]

        async def execute(self,sql,*args):
            assert sql.startswith('select set_config')
            return 'SELECT 1'

        async def fetchval(self,sql,*args):
            scanned.append((sql,args))
            assert 'on conflict (media_asset_id)' in sql
            assert candidate['id']==args[0] and candidate['public_source_url']==args[1]
            return uuid4()

        @asynccontextmanager
        async def transaction(self):
            yield

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    async def fetch_media(url,**kwargs):
        assert url==candidate['public_source_url']
        assert kwargs['max_bytes']<=4_000_000
        return ReferenceImagePayload('image/png',_image())

    monkeypatch.setattr(r2_media,'reference_image_bytes',fetch_media)
    result=await asyncio.wait_for(r2_media.mirror_approved_media(Pool(),limit=2,request_id='test-id'),timeout=5)
    assert result['mirrored']==1 and result['failed']==0 and len(scanned)==1
    assert scanned[0][1][2].startswith('drop-rate/private-media/')


def test_catalogue_query_keeps_price_tables_live_and_mirror_rights_join():
    query,_=catalogue_browser.product_query(owner_id=uuid4())
    assert 'tcg.reference_market_prices' in query
    assert 'tcg.reference_catalogue_prices' in query
    assert 'tcg.media_object_mirrors' in query
    assert 'mirror.source_url=m.public_source_url' in query
    assert 'm.revoked_at is null' in query
    assert 'media.r2_object_key' in query
    static=Path(__file__).resolve().parents[1] / 'backend/app/static/catalogue-browser.js'
    content=static.read_text()
    assert '[row.r2_image_url,row.display_image_url,row.image_url,row.fallback_image_url]' in content
    assert 'useReferenceFirst' in content


def test_migration_never_grants_anonymous_read_or_write():
    migration=(Path(__file__).resolve().parents[1]/
               'database/migrations/20261025170228_r2_verified_media_delivery.sql').read_text()
    assert 'force row level security' in migration
    assert 'revoke all on table tcg.media_object_mirrors from public, anon, authenticated' in migration
    assert 'm.public_source_url=source_url' in migration
    assert 'm.rights_status=\'VERIFIED\'' in migration
    assert 'revoke delete on tcg.media_object_mirrors from tcg_api' in migration


def test_n8n_r2_mirror_command_is_hmac_protected_small_and_inactive():
    command={"schema_version":1,"action":"MIRROR_APPROVED_CANONICAL_MEDIA",
             "execution_id":"r2-pilot-001","occurred_at":"2026-10-25T17:00:00+00:00","limit":3}
    assert MirrorApprovedMediaCommand.model_validate(command).limit==3
    for invalid in ({**command,'limit':600},{**command,'action':'MIRROR_PRIVATE_SCANS'}):
        with pytest.raises(ValidationError):MirrorApprovedMediaCommand.model_validate(invalid)
    source=(Path(__file__).resolve().parents[1]/'backend/app/automation_commands.py').read_text()
    assert "@router.post('/storage/mirror-approved-media')" in source
    assert 'raw = await _verified_command_body(' in source
    path=Path(__file__).resolve().parents[1]/'automation/n8n/workflows/dr-94-r2-approved-media-mirror.json'
    flow=json.loads(path.read_text())
    assert flow['active'] is False
    nodes={n['name']:n for n in flow['nodes']}
    signing=nodes['Sign Small Mirror Command']['parameters']['jsCode']
    assert "createHmac('sha256'" in signing
    assert 'DROP_RATE_AUTOMATION_COMMAND_SECRET' in signing
    assert 'MIRROR_APPROVED_CANONICAL_MEDIA' in signing
    assert '/commands/storage/mirror-approved-media' in signing
    assert 'r2_mirror_receipt_not_verified' in nodes['Verify R2 Batch Receipt']['parameters']['jsCode']
