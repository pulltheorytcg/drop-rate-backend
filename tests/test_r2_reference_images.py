"""Private exact-print cache must not become a generic image scraper."""
from __future__ import annotations

import asyncio
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from app import automation_commands, catalogue_browser, r2_media, r2_reference_images
from app.automation_commands import MirrorReferenceMediaCommand
from app.object_storage import ObjectStorageConfig, S3ObjectStorage
from app.recognition_images import ReferenceImagePayload


ART = 'https://assets.tcgdex.net/en/me/30th/001/high.webp'
PRINT = {'provider': 'TCGdex', 'system_code': 'POKEMON_TCG',
         'language': 'English', 'provider_id': 'me30-1', 'image_url': ART,
         'failure_count': 0}


def _picture():
    image = Image.new('RGB', (200, 200), '#a859a4')
    dest = io.BytesIO()
    image.save(dest, 'PNG')
    return ReferenceImagePayload('image/png', dest.getvalue())


class MissingKey(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}


class MemoryR2:
    def __init__(self):
        self.objects = {}

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise MissingKey()
        return {'Body': io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body.read()

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        return 'https://account.r2.cloudflarestorage.com/private-object?X-Amz-Signature=redacted'


class Connection:
    def __init__(self, candidates):
        self.candidates = candidates
        self.records = []

    async def fetch(self, sql, *args):
        assert 'tcg.reference_cards' in sql and 'next_retry_at<=now()' in sql
        assert 'tcg.reference_image_mirrors' in sql
        return self.candidates[:args[0]]

    async def execute(self, sql, *args):
        assert sql.startswith("select set_config('tcg.request_id'")

    async def fetchval(self, sql, *args):
        self.records.append((sql, args))
        assert '(r.provider,r.system_code,r.language,r.provider_id)' in sql
        assert 'r.image_url=$5' in sql  # must match source *after* HTTP
        assert args[:5] == tuple(PRINT[key] for key in
                                  ('provider', 'system_code', 'language', 'provider_id', 'image_url'))
        return PRINT['provider_id']

    @asynccontextmanager
    async def transaction(self):
        yield


class Pool:
    def __init__(self, candidates):
        self.connection = Connection(candidates)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.mark.parametrize('provider,system,url,accepted', [
    ('TCGdex', 'POKEMON_TCG', ART, True),
    ('Bandai Official', 'DRAGON_BALL_SUPER_MASTERS',
     'https://www.dbs-cardgame.com/images/cardlist/cardimg/BT1-001_b.png', True),
    ('Punk Records', 'ONE_PIECE_CARD_GAME',
     'https://en.onepiece-cardgame.com/images/cardlist/card/OP16-077.png?260929', True),
    ('TCGdex', 'POKEMON_TCG', 'https://assets.tcgdex.net.evil.test/img.png', False),
    ('TCGdex', 'POKEMON_TCG', 'https://assets.tcgdex.net:8080/image.png', False),
    ('TCGdex', 'POKEMON_TCG', 'http://169.254.169.254/private', False),
    ('Punk Records', 'ONE_PIECE_CARD_GAME',
     'https://en.onepiece-cardgame.com/other.png', False),
    ('Naruto Card Game Archive', 'NARUTO_KAYOU',
     'https://narutocardgame.gg/images/1.png', False),
    ('Bandai Official', 'POKEMON_TCG', ART, False),
])
def test_cache_allows_only_known_exact_print_relay(provider, system, url, accepted):
    assert r2_reference_images.accepted_reference_url(url, provider, system) is accepted


@pytest.mark.asyncio
async def test_cache_verifies_r2_bytes_and_current_identity_before_record(monkeypatch):
    client = MemoryR2()
    store = S3ObjectStorage(ObjectStorageConfig('https://account.r2.cloudflarestorage.com',
                         'private-media', 'auto', 'key', 'secret'), client=client)
    monkeypatch.setattr(r2_reference_images, 'configured_object_storage', lambda: store)

    async def fetch(url, **kwargs):
        assert url == ART
        assert kwargs['max_bytes'] <= 4_000_000
        return _picture()

    monkeypatch.setattr(r2_reference_images, 'reference_image_bytes', fetch)
    # Some CI sandboxes disable executor threads; validate the exact pipeline
    # without making the test dependent on that environment restriction.
    async def inline_thread(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(r2_reference_images.asyncio, 'to_thread', inline_thread)
    pool = Pool([PRINT])
    result = await asyncio.wait_for(r2_reference_images.mirror_reference_images(
        pool, limit=3, request_id='test'), timeout=30)
    assert result == {'examined': 1, 'mirrored': 1, 'skipped': 0,
                      'failed': 0, 'remaining_possible': False}
    assert len(pool.connection.records) == 1
    statement, args = pool.connection.records[0]
    assert 'on conflict (provider,system_code,language,provider_id)' in statement
    assert args[5] in client.objects
    assert client.objects[args[5]].startswith(b'RIFF')
    assert args[6] in args[5] and args[7] == len(client.objects[args[5]])


@pytest.mark.asyncio
async def test_invalid_or_unavailable_reference_records_bounded_retry(monkeypatch):
    monkeypatch.setattr(r2_reference_images, 'configured_object_storage', lambda: object())
    async def missing(*args, **kwargs):
        return None
    monkeypatch.setattr(r2_reference_images, 'reference_image_bytes', missing)
    pool = Pool([PRINT])
    result = await r2_reference_images.mirror_reference_images(pool, limit=1,
                                                                request_id='retry-id')
    assert result['failed'] == 1
    query, args = pool.connection.records[0]
    assert "'RETRY'" in query and 'failure_count' in query
    assert args[6] == 'SOURCE_UNAVAILABLE'
    assert args[5].tzinfo is not None


def test_browser_selects_cache_only_for_current_source_and_keeps_live_prices():
    for sort in ('newest', 'value_desc'):
        query, _ = catalogue_browser.product_query(owner_id=uuid4(), sort=sort)
        assert 'tcg.reference_image_mirrors reference_mirror' in query
        assert "page.source_kind='REFERENCE'" in query
        assert "reference_mirror.status='VERIFIED'" in query
        assert 'reference_mirror.source_url=page.image_url' in query
        assert 'reference_mirror.object_key as r2_reference_object_key' in query
        assert 'tcg.catalogue_reference_value_v2' in query


def test_reference_cache_signing_is_independent_and_private(monkeypatch):
    client = MemoryR2()
    store = S3ObjectStorage(ObjectStorageConfig('https://account.r2.cloudflarestorage.com',
                         'private-media', 'auto', 'key', 'secret'), client=client)
    monkeypatch.setattr(r2_media, 'configured_object_storage', lambda: store)
    monkeypatch.delenv('TCG_R2_MEDIA_DELIVERY_ENABLED', raising=False)
    monkeypatch.delenv('TCG_R2_REFERENCE_CACHE_DELIVERY_ENABLED', raising=False)
    key = 'drop-rate/private-media/' + 'a' * 64 + '.webp'
    row = dict(PRINT, r2_reference_object_key=key, r2_object_key=None,
               display_image_url=ART)
    hidden = r2_media.with_signed_mirror(row)
    assert 'r2_reference_object_key' not in hidden and 'r2_object_key' not in hidden
    assert 'r2_image_url' not in hidden
    monkeypatch.setenv('TCG_R2_REFERENCE_CACHE_DELIVERY_ENABLED', 'true')
    signed = r2_media.with_signed_mirror(row)
    assert signed['r2_image_url'].startswith('https://account.r2.cloudflarestorage.com/private-object?')
    assert signed['display_image_url'] == ART


def test_reference_cache_migration_is_backend_only_and_non_destructive():
    path = Path(__file__).resolve().parents[1]
    sql = (path / 'database/migrations/20261025232125_r2_reference_image_cache.sql').read_text()
    assert 'force row level security' in sql
    assert 'revoke all on table tcg.reference_image_mirrors from public,anon,authenticated' in sql
    assert 'grant select,insert,update on tcg.reference_image_mirrors to tcg_api' in sql
    assert 'revoke delete on tcg.reference_image_mirrors from tcg_api' in sql
    assert 'r.image_url=reference_image_mirrors.source_url' in sql
    assert 'on delete cascade' not in sql.lower()


def test_new_automation_command_is_signed_bounded_and_requires_explicit_apply():
    payload = {'action': 'MIRROR_EXACT_REFERENCE_MEDIA', 'execution_id': 'test-pilot',
               'occurred_at': '2026-10-25T20:00:00+00:00'}
    command = MirrorReferenceMediaCommand.model_validate(payload)
    assert command.limit == 10 and command.apply is False
    for bad in ({**payload, 'limit': 21}, {**payload, 'action': 'COPY_ANY_IMAGE'}):
        with pytest.raises(ValidationError):
            MirrorReferenceMediaCommand.model_validate(bad)
    route = (Path(__file__).resolve().parents[1] / 'backend/app/automation_commands.py').read_text()
    assert "@router.post('/storage/mirror-reference-media')" in route
    assert 'raw = await _verified_command_body(' in route
    assert 'r2_reference_cache_apply_enabled' in route


@pytest.mark.asyncio
async def test_signed_reference_command_dry_run_and_apply_gate(monkeypatch):
    active = {'apply': False}

    async def signed(*args, **kwargs):
        return json.dumps({'action': 'MIRROR_EXACT_REFERENCE_MEDIA',
                           'execution_id': 'run-001',
                           'occurred_at': '2026-10-25T22:00:00Z',
                           'limit': 2, 'apply': active['apply']}).encode()

    monkeypatch.setattr(automation_commands, '_verified_command_body', signed)
    monkeypatch.setattr(automation_commands, 'get_settings', lambda:
                        SimpleNamespace(r2_reference_cache_apply_enabled=False))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        db_pool=Pool([PRINT]))), state=SimpleNamespace(request_id='command-test'))
    dry = await automation_commands.mirror_exact_reference_media(request)
    assert dry == {'accepted': True, 'execution_id': 'run-001',
                   'mode': 'DRY_RUN', 'examined': 1,
                   'mirrored': 0, 'remaining_possible': False}
    assert not request.app.state.db_pool.connection.records
    active['apply'] = True
    with pytest.raises(HTTPException) as blocked:
        await automation_commands.mirror_exact_reference_media(request)
    assert blocked.value.status_code == 409

    monkeypatch.setattr(automation_commands, 'get_settings', lambda:
                        SimpleNamespace(r2_reference_cache_apply_enabled=True))
    async def fake_cache(pool, *, limit, request_id):
        assert pool is request.app.state.db_pool
        assert (limit, request_id) == (2, 'command-test')
        return {'examined': 1, 'mirrored': 1, 'skipped': 0,
                'failed': 0, 'remaining_possible': False}
    monkeypatch.setattr(automation_commands, 'mirror_reference_images', fake_cache)
    applied = await automation_commands.mirror_exact_reference_media(request)
    assert (applied['mode'], applied['mirrored']) == ('APPLIED', 1)
