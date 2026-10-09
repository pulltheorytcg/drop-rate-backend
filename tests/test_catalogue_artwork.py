from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app import catalogue_browser as browser
from app.auth import require_user
from app.recognition_images import ReferenceImagePayload


ART = 'https://en.onepiece-cardgame.com/images/cardlist/card/OP16-077.png?260929'
IDENTITY = dict(provider='Bandai Official',system_code='ONE_PIECE_CARD_GAME',language='English',provider_id='OP16-077')


def test_artwork_transport_carries_only_exact_reference_identity():
    row = dict(IDENTITY,source_kind='REFERENCE',image_url=ART)
    result = browser.with_artwork_path(row)
    query = parse_qs(urlsplit(result['reference_image_path']).query)
    assert query == {key:[value] for key,value in IDENTITY.items()}
    assert 'reference_image_path' not in row
    for url in [None,'https://evil.test/card.png','https://en.onepiece-cardgame.com:8443/images/cardlist/card/A.png']:
        assert 'reference_image_path' not in browser.with_artwork_path(dict(row,image_url=url))
    assert 'reference_image_path' not in browser.with_artwork_path(dict(row,source_kind='CATALOGUE'))


@pytest.mark.asyncio
@pytest.mark.parametrize('signed_in,member,url,available,status',[
    (False,False,ART,True,401),(True,False,ART,True,403),
    (True,True,None,True,404),(True,True,'http://127.0.0.1/private',True,404),
    (True,True,ART,False,502),(True,True,ART,True,200)])
async def test_reference_artwork_auth_exact_lookup_and_provider_failure(monkeypatch,signed_in,member,url,available,status):
    user_id,owner_id=uuid4(),uuid4();lookups=[];fetches=[];connected=False
    class Connection:
        async def fetch(self,sql,*args):
            return [{'user_id':user_id,'owner_id':owner_id,'role':'OWNER','founder_authorized':False,
                     'display_name':'Test','owner_type':'CONSIGNOR','founder_slot':None}] if member else []
        async def fetchval(self,sql,*args):
            assert args == tuple(IDENTITY.values())
            assert 's.release_date<=current_date' in sql
            lookups.append(args);return url
    @asynccontextmanager
    async def connection(pool,actor,request_id):
        nonlocal connected
        assert actor==user_id
        connected=True
        try:yield Connection()
        finally:connected=False
    async def image(source):
        assert not connected, 'External HTTP held a database transaction'
        fetches.append(source)
        return ReferenceImagePayload('image/png',b'fixture-image-bytes') if available else None
    monkeypatch.setattr(browser,'user_connection',connection)
    monkeypatch.setattr(browser,'reference_image_bytes',image)
    app=FastAPI();app.state.db_pool=object();app.include_router(browser.router)
    if signed_in:app.dependency_overrides[require_user]=lambda:SimpleNamespace(user_id=user_id)
    @app.middleware('http')
    async def request_id(request,call_next):request.state.request_id='test';return await call_next(request)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/api/v1/catalogue-browser/reference-image',params={**IDENTITY,'url':'https://evil.test'})
    assert response.status_code==status
    if status==200:
        assert response.content==b'fixture-image-bytes'
        assert response.headers['content-type']=='image/png'
    if status in (401,403):assert not lookups
    assert fetches == ([ART] if status in (200,502) else [])
