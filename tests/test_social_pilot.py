import asyncio
import hashlib
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from app import social_pilot as p


@pytest.fixture
def manifest():
    value = json.loads(p.MANIFEST_PATH.read_text())
    value['expires_at']='2099-01-01T00:00:00+00:00'
    return value


def command(m, op='publish', channel='instagram'):
    return p.PilotCommand(pilot_id=m['pilot_id'], actor_user_id=m['actor_user_id'],
                          revision_sha256=p.digest(m),channel=channel,operation=op)


def provider_post(m, ch='instagram', state='sent'):
    return {'id':'test-post','channelId':m['channels'][ch]['channel_id'],'channelService':ch,
            'text':m['channels'][ch]['text'],'schedulingType':'automatic','shareMode':'shareNow',
            'status':state,'sentAt':'2026-10-04T19:00:00Z' if state=='sent' else None,
            'externalLink':'https://www.instagram.com/p/fixture/' if ch=='instagram' else 'https://www.tiktok.com/@dropratetcg/photo/123'}


class Store:
    def __init__(self):
        self.won=False; self.result=None; self.saves=[]; self.lock=asyncio.Lock()
    async def read(self):
        return self.result or ({'state':'UNKNOWN'} if self.won else None)
    async def claim(self,m):
        async with self.lock:
            if self.won: return False
            self.won=True
            return True
    async def save(self,v,observation=False):
        self.saves.append(v)
        if not observation: self.result=v


@pytest.mark.asyncio
async def test_success_and_replay(manifest):
    store=Store(); provider=AsyncMock()
    provider.submit.return_value=p.normalise_post(provider_post(manifest),manifest,'instagram')
    provider.status.return_value=provider.submit.return_value
    first=await p.execute_pilot(manifest,command(manifest),store,provider,enabled=True)
    second=await p.execute_pilot(manifest,command(manifest),store,provider,enabled=True)
    assert first['state']=='DELIVERED' and second['replayed']
    provider.submit.assert_awaited_once()
    provider.status.assert_awaited_once()


@pytest.mark.asyncio
async def test_eight_way_race(manifest):
    store=Store(); provider=AsyncMock()
    provider.submit.return_value={'state':'ACCEPTED','post_id':'test-post'}
    provider.status.return_value=provider.submit.return_value
    await asyncio.gather(*(p.execute_pilot(manifest,command(manifest),store,provider,enabled=True) for _ in range(8)))
    assert provider.submit.await_count==1


@pytest.mark.asyncio
async def test_ambiguous_write_is_never_repeated(manifest):
    store=Store(); provider=AsyncMock(); provider.submit.side_effect=p.PilotError('BUFFER_OUTCOME_UNVERIFIED')
    first=await p.execute_pilot(manifest,command(manifest),store,provider,enabled=True)
    second=await p.execute_pilot(manifest,command(manifest),store,provider,enabled=True)
    assert first['state']==second['state']=='UNKNOWN'
    provider.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_is_read_only(manifest):
    store=Store(); provider=AsyncMock()
    value=await p.execute_pilot(manifest,command(manifest,'check'),store,provider,enabled=False)
    assert value['state']=='READY' and not store.won and not store.saves
    provider.submit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['disabled','expired','preflight','already_claimed'])
async def test_blocked_paths_do_not_send(manifest,case):
    store=Store(); provider=AsyncMock()
    if case=='expired': manifest['expires_at']='2020-01-01T00:00:00+00:00'
    if case=='preflight': provider.preflight.side_effect=p.PilotError('PILOT_MEDIA_CHANGED')
    if case=='already_claimed': store.won=True
    result=await p.execute_pilot(manifest,command(manifest),store,provider,enabled=case!='disabled')
    assert result['state'] in {'BLOCKED','UNKNOWN'}
    provider.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_db_result_failure_preserves_claim(manifest):
    store=Store(); provider=AsyncMock(); provider.submit.return_value={'state':'ACCEPTED','post_id':'test-post'}
    store.save=AsyncMock(side_effect=RuntimeError('fixture database failure'))
    with pytest.raises(RuntimeError):
        await p.execute_pilot(manifest,command(manifest),store,provider,enabled=True)
    result=await p.execute_pilot(manifest,command(manifest),store,provider,enabled=True)
    assert result['state']=='UNKNOWN'
    provider.submit.assert_awaited_once()


@pytest.mark.parametrize('change',[
 {'channelId':'wrong'},{'channelService':'youtube'},{'text':'edited caption'},
 {'schedulingType':'notification'},{'shareMode':'addToQueue'},
 {'status':'unknown-new-value'},{'sentAt':None},{'externalLink':'http://127.0.0.1/private'},
 {'externalLink':'https://instagram.com.attacker.example/p/abc'}])
def test_provider_identity_and_delivery_guards(manifest,change):
    value=provider_post(manifest); value.update(change)
    with pytest.raises(p.PilotError): p.normalise_post(value,manifest,'instagram')


@pytest.mark.parametrize('channel',['instagram','tiktok'])
def test_fixed_immediate_inputs(manifest,channel):
    value=p.post_input(manifest,channel)
    assert value['mode']=='shareNow' and value['schedulingType']=='automatic'
    assert value['saveToDraft'] is False and value['needsApproval'] is False
    assert value['assets'][0]['image']['url']==manifest['channels'][channel]['asset']['url']
    assert value['aiAssisted'] is True
    assert not any(x in str(value).lower() for x in ['music','shareNext'.lower()])


def test_exact_approval_binding(manifest,monkeypatch,tmp_path):
    file=tmp_path/'approved.json'; file.write_text(json.dumps(manifest))
    monkeypatch.setattr(p,'MANIFEST_PATH',file)
    c=command(manifest); assert p.load_manifest(c)==manifest
    manifest['channels']['instagram']['text']+=' changed'
    file.write_text(json.dumps(manifest))
    with pytest.raises(HTTPException) as exc: p.load_manifest(c)
    assert exc.value.status_code==409


def test_committed_manifest_hash():
    assert p.digest(json.loads(p.MANIFEST_PATH.read_text()))=='2b056042371fbb245ff26dd5582a46f6bcc4ff8463362cb50e31932e67dc7fde'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['http','graphql','redirect','malformed'])
async def test_transport_errors_are_sanitised(failure):
    def respond(req):
        assert str(req.url)==p.BUFFER_ENDPOINT
        if failure=='http': return httpx.Response(401,text='do not leak a secret')
        if failure=='redirect': return httpx.Response(302,headers={'Location':'http://127.0.0.1'})
        if failure=='graphql': return httpx.Response(200,json={'errors':[{'message':'do not leak a secret'}]})
        return httpx.Response(200,text='not json do not leak a secret')
    client=p.BufferClient('fixture-key',transport=httpx.MockTransport(respond))
    with pytest.raises(p.PilotError) as exc: await client.graphql('query {}',{})
    assert 'secret' not in str(exc.value) and 'fixture-key' not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('changed',[False,True])
async def test_media_hash_preflight(manifest,changed):
    body=b'test jpeg fixture'; e=manifest['channels']['instagram']
    e['asset']['bytes']=len(body); e['asset']['sha256']=hashlib.sha256(body).hexdigest()
    def respond(req):
        if req.method=='GET': return httpx.Response(200,content=(b'changed' if changed else body),headers={'content-type':'image/jpeg'})
        return httpx.Response(200,json={'data':{'channel':{'id':e['channel_id'],'organizationId':manifest['organization_id'],'name':'dropratetcg','service':'instagram','allowedActions':['scheduleUpdates'],'isDisconnected':False,'isLocked':False,'isQueuePaused':False}}})
    client=p.BufferClient('fixture-key',transport=httpx.MockTransport(respond))
    if changed:
        with pytest.raises(p.PilotError,match='PILOT_MEDIA_CHANGED'): await client.preflight(manifest,'instagram')
    else: await client.preflight(manifest,'instagram')
