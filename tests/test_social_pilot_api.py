"""Actual signed router with fixture I/O; no external providers or production DB."""
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import automation_commands, social_pilot as p

SECRET='test-only-pilot-signature-12345678901234567890'
URL='/api/v1/automation/commands/approved-social-pilot/execute'
def sign(body):
    ts=str(int(time.time()))
    return {'Content-Type':'application/json','X-Drop-Rate-Timestamp':ts,'X-Drop-Rate-Signature':'sha256='+hmac.new(SECRET.encode(),ts.encode()+b'.'+body,hashlib.sha256).hexdigest()}

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(automation_commands,'get_settings',lambda:SimpleNamespace(automation_command_secret=SECRET))
    monkeypatch.setenv('TCG_BUFFER_API_KEY','fixture-provider-key')
    monkeypatch.delenv('TCG_APPROVED_SOCIAL_PILOT',raising=False)
    app=FastAPI(); app.state.db_pool=object()
    @app.middleware('http')
    async def rid(request,call_next):
        request.state.request_id='fixture-request'; return await call_next(request)
    app.include_router(automation_commands.router)
    with TestClient(app) as c: yield c

@pytest.fixture
def body():
    m=json.loads(p.MANIFEST_PATH.read_text())
    return p.canonical({'pilot_id':m['pilot_id'],'actor_user_id':m['actor_user_id'],'revision_sha256':p.digest(m),'channel':'instagram','operation':'check'})

def test_unsigned_tampered_oversized(client,body):
    assert client.post(URL,content=body).status_code==401
    assert client.post(URL,content=body+b' ',headers=sign(body)).status_code==401
    large=b'x'*65537
    assert client.post(URL,content=large,headers=sign(large)).status_code==413

@pytest.mark.parametrize('change',[{'channel':'youtube'},{'asset':'https://example.com/evil'},{'operation':'activate'}])
def test_extra_and_unsupported_inputs_denied(client,body,change):
    value=json.loads(body);value.update(change);raw=p.canonical(value)
    assert client.post(URL,content=raw,headers=sign(raw)).status_code==422

def test_wrong_manifest_denied(client,body):
    value=json.loads(body);value['revision_sha256']='a'*64;raw=p.canonical(value)
    assert client.post(URL,content=raw,headers=sign(raw)).status_code==409

def test_actual_admin_boundary_denies_nonadmin(client,body,monkeypatch):
    actor=json.loads(body)['actor_user_id']
    class Connection:
        async def fetch(self,*args):
            return [{'user_id':UUID(actor),'owner_id':UUID(actor),'role':'OWNER','display_name':'fixture','owner_type':'CONSIGNOR','founder_slot':None,'founder_authorized':False}]
    @asynccontextmanager
    async def connection(*args): yield Connection()
    monkeypatch.setattr(p,'user_connection',connection)
    assert client.post(URL,content=body,headers=sign(body)).status_code==403

def test_signed_check_does_not_publish(client,body,monkeypatch):
    journal=AsyncMock();journal.read.return_value=None
    provider=AsyncMock()
    monkeypatch.setattr(p,'Journal',lambda *args:journal)
    monkeypatch.setattr(p,'BufferClient',lambda *args:provider)
    response=client.post(URL,content=body,headers=sign(body))
    assert response.status_code==200 and response.json()['state']=='READY'
    journal.claim.assert_not_awaited();provider.submit.assert_not_awaited()
