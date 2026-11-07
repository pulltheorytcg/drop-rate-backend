"""HMAC, streaming integrity and replay tests for the disabled private bridge."""
import base64
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest

from app import drive_archive_api as api
from app.drive_archive_transfer import ArchiveTransfer, canonical_json
from app.object_storage import ObjectStorageConfig
from test_drive_archive_transfer import FakeS3, destination, drive_metadata, history_fixture

SECRET = 'synthetic-test-command-secret-at-least-32-bytes'
BASE = '/api/v1/automation/commands/storage/drive-archive'


def body(action, **fields):
    return dict(schema_version=1,action=action,execution_id='synthetic-execution-1',
        occurred_at=datetime.now(timezone.utc).isoformat(),destination=destination(),
        kind='REFERENCE_HISTORY',**fields)


def signed(value, *, stamp=None, binary=False):
    raw = json.dumps(value,separators=(',',':')).encode()
    timestamp = str(int(time.time()) if stamp is None else stamp)
    signature = 'sha256='+hmac.new(SECRET.encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    headers = {'X-Drop-Rate-Timestamp':timestamp,'X-Drop-Rate-Signature':signature}
    if binary:
        headers['X-Drop-Rate-Command'] = base64.urlsafe_b64encode(raw).decode().rstrip('=')
        headers['Content-Type'] = 'application/octet-stream'
    else:
        headers['Content-Type'] = 'application/json'
    return raw,headers


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('TCG_DRIVE_ARCHIVE_TRANSFER_ENABLED','true')
    monkeypatch.setattr(api,'get_settings',lambda:SimpleNamespace(automation_command_secret=SECRET))
    service = ArchiveTransfer(ObjectStorageConfig('https://fixture.invalid','private-test','auto',
                                                 'synthetic-id','synthetic-secret'),FakeS3())
    manifest_sha,_,_ = history_fixture(service)
    bundle = service.load_archive('REFERENCE_HISTORY',manifest_sha)
    app = FastAPI()
    app.state.drive_archive_transfer = service
    app.include_router(api.router)
    return app,service,bundle


async def post(client,path,value,*,binary_bytes=None,stamp=None):
    raw,headers = signed(value,stamp=stamp,binary=binary_bytes is not None)
    return await client.post(BASE+path,content=raw if binary_bytes is None else binary_bytes,headers=headers)


@pytest.mark.asyncio
async def test_requires_hmac_and_off_by_default(setup,monkeypatch):
    app,service,_ = setup
    before = list(service.client.calls)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
        command = body('PLAN_DRIVE_ARCHIVE_COPY')
        response = await client.post(BASE+'/plan',json=command)
        assert response.status_code == 401
        response = await post(client,'/plan',command,stamp=int(time.time())-301)
        assert response.status_code == 401
        monkeypatch.delenv('TCG_DRIVE_ARCHIVE_TRANSFER_ENABLED')
        response = await post(client,'/plan',command)
        assert response.status_code == 409 and response.json()['detail'] == 'DRIVE_ARCHIVE_TRANSFER_DISABLED'
        assert (await client.get(BASE+'/object')).status_code == 405
    assert service.client.calls == before


@pytest.mark.asyncio
async def test_signed_action_is_bound_to_endpoint_and_destination(setup):
    app,service,bundle = setup
    before = list(service.client.calls)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
        response = await post(client,'/complete',body('PLAN_DRIVE_ARCHIVE_COPY'))
        assert response.status_code == 422
        command = body('PLAN_DRIVE_ARCHIVE_COPY')
        command['destination']['account_email'] = 'wrong@example.invalid'
        assert (await post(client,'/plan',command)).status_code == 422
        command = body('READ_DRIVE_ARCHIVE_OBJECT',manifest_sha256=bundle.manifest_sha256,
                       object_sha256=bundle.members[0].sha256,url='https://unrelated.invalid/file')
        assert (await post(client,'/object',command)).status_code == 422
        response = await client.post(BASE+'/plan',content=b'x'*(api.MAX_COMMAND_BYTES+1))
        assert response.status_code == 413
    assert service.client.calls == before


@pytest.mark.asyncio
async def test_binary_transfer_round_trip_requires_every_member_and_is_replay_safe(setup):
    app,service,bundle = setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
        pending = await post(client,'/complete',body('COMPLETE_DRIVE_ARCHIVE_COPY',manifest_sha256=bundle.manifest_sha256))
        assert pending.status_code == 409
        for index,member in enumerate(bundle.members):
            identifiers = dict(manifest_sha256=bundle.manifest_sha256,object_sha256=member.sha256)
            reserved = await post(client,'/reserve',body('RESERVE_DRIVE_ARCHIVE_FILE',**identifiers,
                                                       proposed_file_id=f'drive_test_file_{index:03d}'))
            assert reserved.status_code == 200
            reservation = reserved.json()
            fetched = await post(client,'/object',body('READ_DRIVE_ARCHIVE_OBJECT',**identifiers))
            assert fetched.status_code == 200
            assert fetched.headers['cache-control'] == 'no-store'
            assert fetched.headers['x-content-type-options'] == 'nosniff'
            assert fetched.headers['x-drop-rate-content-sha256'] == member.sha256
            assert hashlib.sha256(fetched.content).hexdigest() == member.sha256
            assert 'Location' not in fetched.headers
            metadata = drive_metadata(bundle,member,reservation)
            verified = await post(client,'/verify-readback',body('VERIFY_DRIVE_ARCHIVE_READBACK',
                **identifiers,drive_file=metadata),binary_bytes=fetched.content)
            assert verified.status_code == 200 and verified.json()['status'] == 'BYTES_VERIFIED'
        complete = body('COMPLETE_DRIVE_ARCHIVE_COPY',manifest_sha256=bundle.manifest_sha256)
        first = await post(client,'/complete',complete)
        bucket_before = dict(service.client.objects)
        second = await post(client,'/complete',complete)
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert service.client.objects == bucket_before
        assert first.json()['history_cleanup_authorised'] is False


@pytest.mark.asyncio
async def test_forged_readback_hash_cannot_be_certified_from_metadata(setup):
    app,service,bundle = setup
    member = bundle.members[0]
    reservation = service.reserve(bundle,member,'drive_test_file_001')
    command = body('VERIFY_DRIVE_ARCHIVE_READBACK',manifest_sha256=bundle.manifest_sha256,
        object_sha256=member.sha256,drive_file=drive_metadata(bundle,member,reservation))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
        response = await post(client,'/verify-readback',command,binary_bytes=b'x'*member.size_bytes)
        assert response.status_code == 502 and response.json()['detail'] == 'DRIVE_READBACK_MISMATCH'
        response = await post(client,'/verify-readback',command,binary_bytes=b'x')
        assert response.status_code == 502
        _,headers = signed(command,binary=True)
        async def oversized_chunks():
            yield b'x' * member.size_bytes
            yield b'extra'
        response = await client.post(BASE+'/verify-readback',content=oversized_chunks(),headers=headers)
        assert response.status_code == 502
    assert not any('/objects/' in key or '/complete/' in key for key in service.client.objects)


@pytest.mark.asyncio
async def test_readback_envelope_is_authenticated_before_body_processing(setup):
    app,service,bundle = setup
    before = list(service.client.calls)
    command = body('VERIFY_DRIVE_ARCHIVE_READBACK',manifest_sha256=bundle.manifest_sha256,
                   object_sha256=bundle.members[0].sha256,drive_file={})
    _,headers = signed(command,binary=True)
    headers['X-Drop-Rate-Signature'] = 'sha256='+'0'*64
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
        response = await client.post(BASE+'/verify-readback',content=b'untrusted',headers=headers)
        assert response.status_code == 401
        headers['X-Drop-Rate-Command'] = 'x'*(api.MAX_ENVELOPE_BYTES+1)
        assert (await client.post(BASE+'/verify-readback',content=b'untrusted',headers=headers)).status_code == 413
    assert service.client.calls == before


@pytest.mark.asyncio
async def test_command_read_duration_is_bounded_before_auth_or_storage(setup,monkeypatch):
    app,service,_ = setup
    before = list(service.client.calls)
    monkeypatch.setattr(api,'COMMAND_READ_SECONDS',0.01)
    async def delayed():
        yield b'{'
        await asyncio.sleep(0.05)
        yield b'}'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
        response = await client.post(BASE+'/plan',content=delayed())
        assert response.status_code == 408 and response.json()['detail'] == 'ARCHIVE_COMMAND_READ_TIMEOUT'
    assert service.client.calls == before
