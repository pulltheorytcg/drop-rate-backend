"""One explicitly approved image pilot. No model, schedule, or retrying writes."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .access_control import require_platform_admin
from .db import user_connection

router = APIRouter(prefix='/approved-social-pilot', tags=['approved-social-pilot'])
MANIFEST_PATH = Path(__file__).with_name('approved_social_pilot.json')
BUFFER_ENDPOINT = 'https://api.buffer.com'
KINDS = {name: 'N8N:approved-social-pilot-' + name for name in ('intent','claim','submission','observation')}
POST_FIELDS = 'id channelId channelService text status schedulingType shareMode sentAt externalLink'
CHANNEL_QUERY = '''query($input: ChannelInput!) { channel(input:$input) {
 id organizationId name service allowedActions isDisconnected isLocked isQueuePaused timezone } }'''
POST_QUERY = 'query($input: PostInput!) { post(input:$input) { ' + POST_FIELDS + ' } }'
CREATE_MUTATION = '''mutation($input: CreatePostInput!) { createPost(input:$input) {
 __typename ... on PostActionSuccess { post { ''' + POST_FIELDS + ''' } }
 ... on MutationError { message } } }'''


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class PilotCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    pilot_id: str = Field(pattern=r'^[0-9a-f-]{36}$')
    actor_user_id: str = Field(pattern=r'^[0-9a-f-]{36}$')
    revision_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    channel: Literal['instagram','tiktok']
    operation: Literal['check','publish','status']


class PilotError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def load_manifest(command):
    manifest = json.loads(MANIFEST_PATH.read_text())
    if (command.pilot_id != manifest['pilot_id'] or command.actor_user_id != manifest['actor_user_id']
            or command.revision_sha256 != digest(manifest)):
        raise HTTPException(409, 'Approved pilot revision does not match')
    UUID(command.pilot_id); UUID(command.actor_user_id)
    return manifest


def post_input(manifest, channel):
    entry = manifest['channels'][channel]
    value = {'channelId': entry['channel_id'], 'text': entry['text'],
             'mode': 'shareNow', 'schedulingType': 'automatic', 'saveToDraft': False,
             'needsApproval': False, 'aiAssisted': True,
             'assets': [{'image': {'url': entry['asset']['url']}}]}
    value['metadata'] = ({'instagram': {'type':'post','shouldShareToFeed':True,'isAiGenerated':True}}
                         if channel == 'instagram' else {'tiktok': {'title':entry['title']}})
    return value


def normalise_post(post, manifest, channel):
    entry = manifest['channels'][channel]
    if (not isinstance(post, dict) or post.get('channelId') != entry['channel_id']
            or post.get('channelService') != channel or post.get('text') != entry['text']
            or not isinstance(post.get('id'), str) or not post['id'] or len(post['id']) > 100):
        raise PilotError('BUFFER_POST_IDENTITY_MISMATCH')
    if post.get('schedulingType') != 'automatic' or post.get('shareMode') != 'shareNow':
        raise PilotError('BUFFER_WRONG_PUBLISHING_MODE')
    status = post.get('status')
    state = {'sent':'DELIVERED','error':'FAILED','sending':'SENDING','scheduled':'ACCEPTED',
             'buffer':'ACCEPTED','draft':'BLOCKED','needs_approval':'BLOCKED'}.get(status)
    if state is None:
        raise PilotError('BUFFER_UNKNOWN_POST_STATUS')
    link = post.get('externalLink')
    if link:
        if not isinstance(link,str):
            raise PilotError('BUFFER_INVALID_DELIVERY_URL')
        parts = urlsplit(link)
        domains = {'instagram.com','www.instagram.com'} if channel=='instagram' else {'tiktok.com','www.tiktok.com','vm.tiktok.com'}
        if parts.scheme != 'https' or parts.hostname not in domains or parts.username or parts.password:
            raise PilotError('BUFFER_INVALID_DELIVERY_URL')
    sent_at = post.get('sentAt')
    if state == 'DELIVERED':
        try:
            when = datetime.fromisoformat(sent_at.replace('Z','+00:00'))
            if when.tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise PilotError('BUFFER_SENT_WITHOUT_TIMESTAMP') from None
    return {'state':state, 'post_id':post['id'], 'provider_status':status,
            'sent_at':sent_at, 'external_url':link, 'delivery_reported':state=='DELIVERED',
            'public_visibility_verified':False}


class BufferClient:
    def __init__(self, key, *, transport=None):
        self.key, self.transport = key, transport

    async def graphql(self, query, variables):
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=False, transport=self.transport) as client:
                async with client.stream('POST', BUFFER_ENDPOINT, headers={'Authorization':'Bearer '+self.key},
                                         json={'query':query,'variables':variables}) as response:
                    if response.status_code != 200:
                        raise PilotError('BUFFER_HTTP_' + str(response.status_code))
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1024*1024:
                            raise PilotError('BUFFER_RESPONSE_TOO_LARGE')
            value = json.loads(body)
            if value.get('errors') or not isinstance(value.get('data'),dict):
                raise PilotError('BUFFER_GRAPHQL_ERROR')
            return value['data']
        except PilotError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise PilotError('BUFFER_OUTCOME_UNVERIFIED') from None

    async def preflight(self, manifest, channel):
        entry = manifest['channels'][channel]
        data = await self.graphql(CHANNEL_QUERY, {'input':{'id':entry['channel_id']}})
        item = data.get('channel')
        if not isinstance(item,dict):
            raise PilotError('BUFFER_CHANNEL_MISSING')
        if (item.get('id') != entry['channel_id'] or item.get('organizationId') != manifest['organization_id']
                or item.get('service') != channel or str(item.get('name','')).lstrip('@').lower() != 'dropratetcg'):
            raise PilotError('BUFFER_CHANNEL_IDENTITY_MISMATCH')
        if (any(item.get(k) is not False for k in ('isDisconnected','isLocked','isQueuePaused'))
                or not isinstance(item.get('allowedActions'),list)
                or 'scheduleUpdates' not in item['allowedActions']):
            raise PilotError('BUFFER_CHANNEL_NOT_READY')
        asset = entry['asset']
        parts = urlsplit(asset['url'])
        if (parts.scheme != 'https' or parts.hostname != 'cdn.shopify.com' or parts.username or parts.password
                or not parts.path.startswith('/s/files/1/1038/7482/2491/files/')):
            raise PilotError('PILOT_MEDIA_URL_NOT_APPROVED')
        try:
            async with httpx.AsyncClient(timeout=20,follow_redirects=False,transport=self.transport) as client:
                async with client.stream('GET',asset['url']) as response:
                    if response.status_code != 200 or response.headers.get('content-type','').split(';')[0] != 'image/jpeg':
                        raise PilotError('PILOT_MEDIA_NOT_AVAILABLE')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body)>8*1024*1024:
                            raise PilotError('PILOT_MEDIA_TOO_LARGE')
            if len(body) != asset['bytes'] or hashlib.sha256(body).hexdigest() != asset['sha256']:
                raise PilotError('PILOT_MEDIA_CHANGED')
        except PilotError:
            raise
        except httpx.HTTPError:
            raise PilotError('PILOT_MEDIA_UNVERIFIED') from None

    async def submit(self, manifest, channel):
        data = await self.graphql(CREATE_MUTATION, {'input':post_input(manifest,channel)})
        result = data.get('createPost')
        if not isinstance(result,dict) or result.get('__typename') != 'PostActionSuccess':
            # No blind retries, including provider errors: preserve the durable claim.
            raise PilotError('BUFFER_CREATE_REJECTED_OR_UNKNOWN')
        return normalise_post(result.get('post'),manifest,channel)

    async def status(self, manifest, channel, post_id):
        data = await self.graphql(POST_QUERY, {'input':{'id':post_id}})
        value = normalise_post(data.get('post'),manifest,channel)
        if value['post_id'] != post_id:
            raise PilotError('BUFFER_POST_IDENTITY_MISMATCH')
        return value


class Journal:
    """Append-only existing automation_runs; app has INSERT/SELECT, not UPDATE/DELETE."""
    def __init__(self, pool, command, request_id):
        self.pool, self.command, self.request_id = pool, command, request_id
        self.key = 'approved-social-pilot:' + command.pilot_id + ':' + command.channel

    @asynccontextmanager
    async def connection(self):
        async with user_connection(self.pool,UUID(self.command.actor_user_id),self.request_id) as conn:
            auth = await require_platform_admin(conn)
            yield conn, auth['owner_id']

    async def read(self):
        async with self.connection() as (conn, owner):
            rows = await conn.fetch('select job_type,result from tcg.automation_runs where owner_id=$1 and run_key=$2',owner,self.key)
        values = {row['job_type']:row['result'] for row in rows}
        if KINDS['claim'] not in values:
            return None
        claim = values[KINDS['claim']]
        if claim['revision_sha256'] != self.command.revision_sha256:
            raise HTTPException(409,'Publication claim belongs to another revision')
        return values.get(KINDS['submission'], {'state':'UNKNOWN','reason':'CLAIM_EXISTS_WITHOUT_RESULT'})

    async def claim(self, manifest):
        async with self.connection() as (conn, owner):
            await conn.execute('select pg_advisory_xact_lock(hashtextextended($1,0))',self.key)
            prior = await conn.fetchrow('select result from tcg.automation_runs where owner_id=$1 and job_type=$2 and run_key=$3',owner,KINDS['intent'],self.key)
            intent = {'revision_sha256':self.command.revision_sha256,'manifest':manifest,'actor_user_id':self.command.actor_user_id}
            if prior and prior['result'] != intent:
                raise HTTPException(409,'Immutable approval has changed')
            await conn.execute("insert into tcg.automation_runs(owner_id,job_type,run_key,initiated_by,result) values($1,$2,$3,'N8N',$4::jsonb) on conflict do nothing",owner,KINDS['intent'],self.key,intent)
            row = await conn.fetchrow("insert into tcg.automation_runs(owner_id,job_type,run_key,initiated_by,result) values($1,$2,$3,'N8N',$4::jsonb) on conflict do nothing returning id",owner,KINDS['claim'],self.key,{'revision_sha256':self.command.revision_sha256,'state':'CLAIMED'})
            return row is not None

    async def save(self, value, *, observation=False):
        kind = KINDS['observation' if observation else 'submission']
        key = self.key + (':'+digest(value)[:24] if observation else '')
        async with self.connection() as (conn, owner):
            inserted = await conn.fetchrow("insert into tcg.automation_runs(owner_id,job_type,run_key,initiated_by,result) values($1,$2,$3,'N8N',$4::jsonb) on conflict do nothing returning id",owner,kind,key,value)
            if inserted is not None and value['state'] in {'FAILED','UNKNOWN','BLOCKED'}:
                await conn.execute("""insert into tcg.action_required_items(owner_id,category,code,severity,entity_type,entity_id,dedupe_key,title,detail,recommended_action,status,metadata)
                values($1,'AUTOMATION','SOCIAL_PILOT_REQUIRES_REVIEW','HIGH','OWNER',$1,$2,'Social publishing pilot needs review',
                'Publication failed or its outcome could not be verified.','Check Buffer and the saved journal. Do not repost an unknown result.','OPEN',$3::jsonb)
                on conflict(owner_id,dedupe_key) do nothing""",owner,self.key,{'pilot_id':self.command.pilot_id,'channel':self.command.channel,'state':value['state']})


async def execute_pilot(manifest, command, journal, provider, *, enabled):
    existing = await journal.read()
    if command.operation == 'status' or existing is not None:
        if existing is None:
            return {'state':'NOT_STARTED','published':False}
        if not existing.get('post_id'):
            return {**existing,'replayed':True,'published':False}
        try:
            value = await provider.status(manifest,command.channel,existing['post_id'])
            await journal.save(value,observation=True)
            return {**value,'replayed':True,'published':value['state']=='DELIVERED'}
        except PilotError as error:
            return {'state':'UNKNOWN','reason':error.code,'post_id':existing['post_id'],'published':False,'replayed':True}
    if command.operation == 'publish' and (not enabled or datetime.now(timezone.utc) >= datetime.fromisoformat(manifest['expires_at'])):
        return {'state':'BLOCKED','reason':'PILOT_NOT_ENABLED','published':False}
    try:
        await provider.preflight(manifest,command.channel)
    except PilotError as error:
        return {'state':'BLOCKED','reason':error.code,'published':False}
    if command.operation == 'check':
        return {'state':'READY','published':False,'revision_sha256':command.revision_sha256}
    if not await journal.claim(manifest):
        return {'state':'UNKNOWN','reason':'ALREADY_CLAIMED_RECONCILE_ONLY','replayed':True,'published':False}
    try:
        value = await provider.submit(manifest,command.channel)
    except PilotError as error:
        value = {'state':'UNKNOWN','reason':error.code}
    await journal.save(value)
    return {**value,'replayed':False,'published':value['state']=='DELIVERED'}


@router.post('/execute')
async def pilot_route(request: Request):
    from .marketing_specialist_api import verified
    command = await verified(request,PilotCommand)
    manifest = load_manifest(command)
    journal = Journal(request.app.state.db_pool,command,request.state.request_id)
    key = os.environ.get('TCG_BUFFER_API_KEY','').strip()
    if not key:
        raise HTTPException(503,'Buffer runtime credential is not configured')
    enabled = os.environ.get('TCG_APPROVED_SOCIAL_PILOT','') == command.revision_sha256
    result = await execute_pilot(manifest,command,journal,BufferClient(key),enabled=enabled)
    return {**command.model_dump(), **result}
