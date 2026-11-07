"""Authenticated ASGI + actual PostgreSQL, with a local test JWKS issuer.

No auth dependency override, mocked query response, production JWT, live seller
or Shopify request. The local issuer is not a real Supabase sign-in flow.
Run after owner_auto_import_postgres.py in the same disposable CI database.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, Depends

from app import auth, owner_imports, imports
from app.access_control import require_platform_admin_request
from app.db import _init_connection
from owner_auto_import_postgres import payload


async def main():
    dsn=os.environ['IMPORT_TEST_DSN'];u=urlsplit(dsn)
    assert u.hostname in {'localhost','127.0.0.1'} and u.path=='/import_intake_test'
    db=await asyncpg.connect(dsn);await _init_connection(db)
    private=ec.generate_private_key(ec.SECP256R1())
    public=json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    public.update(kid='disposable-intake-key',use='sig',alg='ES256')
    class JWKS(BaseHTTPRequestHandler):
        def do_GET(self):
            body=json.dumps({'keys':[public]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):
            pass
    server=ThreadingHTTPServer(('127.0.0.1',0),JWKS)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    settings=SimpleNamespace(jwks_url=f'http://127.0.0.1:{server.server_port}/jwks.json',auth_audience='authenticated',auth_issuer='https://intake-fixture.invalid/auth/v1')
    async def setup(c):
        await c.execute('set role tcg_api')
    pool=await asyncpg.create_pool(dsn,min_size=1,max_size=4,init=_init_connection,setup=setup)
    try:
        card_b=await db.fetchval("select id from tcg.catalogue_products where identity_key='synthetic:b'")
        assert card_b,'Expected disposable fixture, not a production database'
        owner_a,owner_b,owner_admin,actor_a,actor_b,actor_admin=[uuid4() for _ in range(6)]
        await db.executemany("insert into tcg.owners(id,display_name,owner_type,commission_bps) values($1,$2,'CONSIGNOR',1000)",[(owner_a,'HTTP Seller A'),(owner_b,'HTTP Seller B'),(owner_admin,'HTTP Founder fixture')])
        await db.executemany("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,$3)",[(actor_a,owner_a,'OWNER'),(actor_b,owner_b,'OWNER'),(actor_admin,owner_admin,'PLATFORM_ADMIN')])
        app=FastAPI();app.state.db_pool=pool
        @app.middleware('http')
        async def request_id(request,call_next):
            request.state.request_id='http-intake-fixture'
            return await call_next(request)
        app.include_router(owner_imports.router)
        app.include_router(imports.router,dependencies=[Depends(require_platform_admin_request)])
        def token(actor,**changes):
            now=int(time.time())
            claims={'sub':str(actor),'iss':settings.auth_issuer,'aud':settings.auth_audience,'iat':now,'exp':now+600,'role':'authenticated','session_id':str(uuid4()),'email':'synthetic@example.invalid'}
            claims.update(changes)
            return jwt.encode(claims,private,algorithm='ES256',headers={'kid':'disposable-intake-key'})
        def headers(actor,**changes):
            return {'Authorization':'Bearer '+token(actor,**changes)}
        auth._jwk_client.cache_clear()
        with patch.object(auth,'get_settings',return_value=settings):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://intake.test') as client:
                upload='/api/v1/owner/imports/upload'
                data=payload().model_dump()
                assert (await client.post(upload,json=data)).status_code==401
                for changes in ({'exp':int(time.time())-60},{'is_anonymous':True},{'role':'service_role'},{'iss':'https://wrong.invalid'}):
                    assert (await client.post(upload,json=data,headers=headers(actor_a,**changes))).status_code==401
                assert (await client.post(upload,json=data,headers=headers(actor_admin))).status_code==403,'Founder bypassed owner-only portal gate'
                assert (await client.post('/api/v1/imports/preview',json=data,headers=headers(actor_a))).status_code==403,'Seller reached founder import API'
                response=await client.post(upload,json=data,headers=headers(actor_a))
                assert response.status_code==201,response.text
                result=response.json();batch_id=result['batch_id'];version=result['version']
                assert result['created_count']==2 and result['summary']['review_rows']==1
                detail='/api/v1/owner/imports/'+batch_id
                assert (await client.get(detail,headers=headers(actor_b))).status_code==404
                assert (await client.get(detail,headers=headers(actor_b,user_metadata={'owner_id':str(owner_a),'role':'PLATFORM_ADMIN'}))).status_code==404
                stored=(await client.get(detail,headers=headers(actor_a))).json()
                candidate=next(x for x in stored['candidates'] if x['status']=='REVIEW')
                confirm=detail+'/candidates/'+candidate['id']+'/resolve'
                decision={'version':version,'catalogue_id':str(card_b)}
                assert (await client.post(confirm,json=decision,headers=headers(actor_b))).status_code==404
                completed=await client.post(confirm,json=decision,headers=headers(actor_a))
                assert completed.status_code==200,completed.text
                assert completed.json()['created_count']==1 and completed.json()['status']=='COMMITTED'
                retry=await client.post(upload,json=data,headers=headers(actor_a))
                assert retry.status_code==201 and retry.json()['created_count']==0
                stock=await db.fetch('select owner_id,status,identity_confirmed from tcg.inventory_items where import_batch_id=$1',UUID(batch_id))
                assert len(stock)==3 and all(r['owner_id']==owner_a and r['status']=='DRAFT' and not r['identity_confirmed'] for r in stock)
                await db.execute('update tcg.owner_memberships set active=false where user_id=$1',actor_a)
                assert (await client.get(detail,headers=headers(actor_a))).status_code==403,'Revoked membership retained import access'
        print('PASS: real JWT signature/JWKS verification + authenticated owner HTTP routes + PostgreSQL; immediate partial intake, confirmation, replay, foreign/forged-metadata access, invalid/expired/anonymous tokens and revoked membership. Local test issuer, not production Supabase login.')
    finally:
        auth._jwk_client.cache_clear()
        await pool.close();await db.close()
        await asyncio.to_thread(server.shutdown);server.server_close();thread.join(timeout=2)


if __name__=='__main__':
    asyncio.run(main())
