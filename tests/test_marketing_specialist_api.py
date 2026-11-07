from __future__ import annotations

import hashlib
import hmac
import json
import runpy
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import automation_commands
from app import marketing_specialist_api as api

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'test-only-marketing-command-signature-1234567890'
ACTOR = '00000000-0000-4000-8000-000000000002'


def headers(body):
    timestamp = str(int(time.time()))
    signature = 'sha256=' + hmac.new(SECRET.encode(), timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    return {'Content-Type':'application/json','X-Drop-Rate-Timestamp':timestamp,'X-Drop-Rate-Signature':signature}


@pytest.fixture
def client(monkeypatch):
    settings = SimpleNamespace(automation_command_secret=SECRET, openai_api_key=None)
    monkeypatch.setattr(automation_commands, 'get_settings', lambda: settings)
    monkeypatch.setattr(api, 'get_settings', lambda: settings)
    monkeypatch.delenv('TCG_MARKETING_SPECIALISTS_ENABLED', raising=False)
    app = FastAPI()
    app.state.db_pool = object()

    @app.middleware('http')
    async def request_id(request, call_next):
        request.state.request_id = '00000000-0000-4000-8000-000000000099'
        return await call_next(request)

    app.include_router(automation_commands.router)
    with TestClient(app) as test_client:
        yield test_client


def post(client, action, payload, signed=True):
    body = json.dumps(payload).encode()
    return client.post('/api/v1/automation/commands/marketing/' + action, content=body, headers=headers(body) if signed else {})


def test_unsigned_and_tampered_commands_fail_before_store(client):
    assert post(client,'catalog',{'actor_user_id':ACTOR},False).status_code == 401
    original = json.dumps({'actor_user_id':ACTOR}).encode()
    response = client.post('/api/v1/automation/commands/marketing/catalog',content=original+b' ',headers=headers(original))
    assert response.status_code == 401


def test_oversize_command_rejected(client):
    body = b'x' * (65536 + 1)
    assert client.post('/api/v1/automation/commands/marketing/catalog', content=body, headers=headers(body)).status_code == 413


@pytest.mark.parametrize('payload', [{}, {'actor_user_id':'invalid'}, {'actor_user_id':ACTOR,'publish':True}])
def test_bad_command_shapes_rejected(client, payload):
    assert post(client,'catalog',payload).status_code == 422


def test_execution_flag_defaults_off(client):
    payload = {'actor_user_id':ACTOR,'job_id':'00000000-0000-4000-8000-000000000001','input':{'topic':'Test'}}
    assert post(client,'create',payload).status_code == 409


def test_signed_non_admin_is_still_forbidden(client, monkeypatch):
    class Connection:
        async def fetch(self, *_args):
            return [{'user_id':UUID(ACTOR),'owner_id':UUID(ACTOR),'role':'OWNER',
                     'display_name':'Fixture owner','owner_type':'CONSIGNOR',
                     'founder_slot':None,'founder_authorized':False}]

    @asynccontextmanager
    async def connection(*args):
        yield Connection()

    monkeypatch.setattr(api, 'user_connection', connection)
    assert post(client,'catalog',{'actor_user_id':ACTOR}).status_code == 403


def test_signed_admin_gets_six_nonpublishing_registrations(client, monkeypatch):
    class Connection:
        async def fetch(self, *_args):
            return [{'user_id':UUID(ACTOR),'owner_id':UUID(ACTOR),'role':'PLATFORM_ADMIN',
                     'display_name':'Fixture founder','owner_type':'FOUNDER',
                     'founder_slot':1,'founder_authorized':True}]

    @asynccontextmanager
    async def connection(*args):
        yield Connection()

    monkeypatch.setattr(api, 'user_connection', connection)
    response = post(client,'catalog',{'actor_user_id':ACTOR})
    assert response.status_code == 200
    assert len(response.json()['specialists']) == 6
    assert response.json()['enabled'] is False
    assert response.json()['published'] is False


def test_generated_workflows_match_committed_export():
    generator = runpy.run_path(str(ROOT / 'automation/n8n/marketing/build_workflows.py'))
    saved = json.loads((ROOT / 'automation/n8n/marketing/workflows.json').read_text())
    assert saved == generator['exports']()


def test_actual_n8n_code_nodes_under_node():
    completed = subprocess.run(['node','--test',str(ROOT / 'tests/marketing_workflows.test.cjs')], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
