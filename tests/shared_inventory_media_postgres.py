"""Real media migrations/RLS + signed JWT API tests; local synthetic data only.
Remote image bytes are an HTTP mock; not a production Supabase sign-in.
"""
import asyncio
import base64
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI

from app import api, auth
from app.db import _init_connection, user_connection

ROOT = Path(__file__).resolve().parents[1]
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jhZkAAAAASUVORK5CYII=')

async def main():
    dsn = os.environ['MEDIA_TEST_DSN']; parsed = urlsplit(dsn)
    assert parsed.hostname in ('localhost', '127.0.0.1') and parsed.path == '/media_test'
    db = await asyncpg.connect(dsn); await _init_connection(db)
    pool = None; server = None
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"), 'Fresh disposable database only'
        await db.execute('''create schema tcg; create schema auth;
          create role tcg_api nologin nosuperuser nobypassrls;
          create role anon nologin; create role authenticated nologin;
          create table auth.users(id uuid primary key);
          create table tcg.owners(id uuid primary key, display_name text, owner_type text, founder_slot int, commission_bps int,active bool default true);
          create table tcg.owner_memberships(id uuid primary key default gen_random_uuid(),user_id uuid,owner_id uuid references tcg.owners,role text,active bool default true,created_at timestamptz default now());
          create function tcg.current_user_id() returns uuid language sql stable as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          create table tcg.catalogue_products(id uuid primary key, name text,language text,variant text);
          create table tcg.inventory_items(id uuid primary key,owner_id uuid references tcg.owners,catalogue_id uuid references tcg.catalogue_products,language text);
          create table tcg.audit_events(actor text,request_id text,action text,entity_type text,entity_id uuid,old_values jsonb,new_values jsonb);
          grant usage on schema tcg to tcg_api;
          grant select on all tables in schema tcg to tcg_api;
          alter table tcg.owner_memberships enable row level security;
          create policy member_read on tcg.owner_memberships for select to tcg_api using(user_id=tcg.current_user_id() and active);
          alter table tcg.owners enable row level security;
          create policy owner_read on tcg.owners for select to tcg_api using(active and id in(select owner_id from tcg.owner_memberships));
          alter table tcg.inventory_items enable row level security; alter table tcg.inventory_items force row level security;
          create policy inventory_read on tcg.inventory_items for select to tcg_api using(owner_id in(select id from tcg.owners));
        ''')
        migrations = ROOT / 'database/migrations'
        await db.execute((migrations/'20260925154423_media_assets_registry.sql').read_text())
        await db.execute('alter table tcg.media_assets add column capture_context text, add column shopify_cdn_url text;')
        await db.execute((migrations/'20260927160758_media_rights_resolver.sql').read_text())
        await db.execute((migrations/'20260928224759_sealed_product_media.sql').read_text())
        owners = [uuid4() for _ in range(3)]; actors = [uuid4() for _ in range(3)]; card, pack = uuid4(), uuid4()
        for n, (owner, actor) in enumerate(zip(owners, actors)):
            await db.execute('insert into auth.users values($1)',actor)
            await db.execute("insert into tcg.owners values($1,$2,$3,$4,1000,true)",owner,f'Synthetic owner {n}','FOUNDER' if n==0 else 'CONSIGNOR',1 if n==0 else None)
            await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,$3)",actor,owner,'PLATFORM_ADMIN' if n==0 else 'OWNER')
        for product, name in [(card,'Synthetic raw card'),(pack,'Synthetic pack')]:
            await db.execute("insert into tcg.catalogue_products values($1,$2,'Japanese','Foil')",product,name)
        copies = {(n,p): uuid4() for n in range(3) for p in (card,pack)}
        for (n,p), item in copies.items():
            await db.execute("insert into tcg.inventory_items values($1,$2,$3,'Japanese')",item,owners[n],p)
        async def asset(scope, product=None, inventory=None, language='Japanese',variant='Foil',approval='APPROVED',source='ACTIVE',suffix='card'):
            return await db.fetchval('''insert into tcg.media_assets(owner_id,catalogue_id,inventory_id,scope,source_type,source_reference,public_source_url,rights_status,rights_basis,approval_status,alt_text,created_by_user_id,approved_by_user_id,approved_at,rights_tier,source_provider,media_language,media_variant,source_status)
              values($1,$2,$3,$4,'OFFICIAL_PROVIDER','synthetic fixture',$5,'VERIFIED','Synthetic test permission',$6,'Test image',$7,$7,now(),$8,'Test source',$9,$10,$11) returning id''',owners[0],product,inventory,scope,f'https://www.onepiece-cardgame.com/{suffix}.png',approval,actors[0],'FIRST_PARTY_CAPTURE' if inventory else 'STOREFRONT_ALLOWED',language,variant,source)
        card_media = await asset('CANONICAL_CARD',card)
        pack_media = await asset('CANONICAL_PRODUCT',pack,suffix='pack')
        physical = await asset('INVENTORY_ITEM',inventory=copies[0,card],suffix='private-slab')
        await asset('CANONICAL_CARD',card,language='English',suffix='wrong-language')
        await asset('CANONICAL_CARD',card,variant='Alternate Art',suffix='wrong-variant')
        await asset('CANONICAL_CARD',card,source='DEAD',suffix='dead')
        async def setup(c): await c.execute('set role tcg_api')
        pool = await asyncpg.create_pool(dsn,min_size=1,max_size=3,init=_init_connection,setup=setup)
        async with user_connection(pool,actors[1],'before') as c:
            assert await c.fetchval('select count(*) from tcg.media_assets where id=$1',card_media)==1
            assert await c.fetchval('select count(*) from tcg.media_assets where id=$1 and owner_id=$2',card_media,owners[1])==0
            assert await c.fetchval('select count(*) from tcg.media_assets where id=$1',pack_media)==0
            assert await c.fetchval('select count(*) from tcg.media_assets where id=$1',physical)==0
        await db.execute((migrations/'20261011211000_shared_canonical_product_images.sql').read_text())
        async with user_connection(pool,actors[1],'after') as c:
            assert await c.fetchval('select count(*) from tcg.media_assets where id=$1',pack_media)==1
            assert await c.fetchval('select count(*) from tcg.media_assets where id=$1',physical)==0
            assert await c.execute("update tcg.media_assets set alt_text='forbidden' where id=$1",pack_media)=='UPDATE 0'
        before = {t:await db.fetch(f'select * from tcg.{t} order by id') for t in ('owners','owner_memberships','inventory_items','media_assets')}
        audit_before=await db.fetch('select * from tcg.audit_events')
        key=ec.generate_private_key(ec.SECP256R1()); public=json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()));public.update(kid='local-media',use='sig',alg='ES256')
        class JWKS(BaseHTTPRequestHandler):
            def do_GET(self):
                body=json.dumps({'keys':[public]}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),JWKS);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        settings=SimpleNamespace(jwks_url=f'http://127.0.0.1:{server.server_port}/jwks',auth_audience='authenticated',auth_issuer='https://local-media.test/auth')
        def headers(n,expired=False):
            now=int(time.time()); claims={'sub':str(actors[n]),'aud':'authenticated','iss':settings.auth_issuer,'iat':now-30,'exp':now-1 if expired else now+600,'role':'authenticated'}
            return {'Authorization':'Bearer '+jwt.encode(claims,key,algorithm='ES256',headers={'kid':'local-media'})}
        outbound=[]
        def remote(req):
            assert 'authorization' not in req.headers
            outbound.append(str(req.url));return httpx.Response(200,headers={'content-type':'image/png'},content=PNG)
        real_client=httpx.AsyncClient
        def provider_client(**kwargs):return real_client(transport=httpx.MockTransport(remote),**kwargs)
        app=FastAPI();app.state.db_pool=pool;app.include_router(api.router)
        @app.middleware("http")
        async def request_context(request, call_next):
            request.state.request_id="synthetic-media-http"
            return await call_next(request)
        auth._jwk_client.cache_clear()
        async with real_client(transport=httpx.ASGITransport(app=app),base_url='http://app.test') as client:
            with patch.object(auth,'get_settings',return_value=settings),patch.object(api.httpx,'AsyncClient',side_effect=provider_client):
                for n in range(3):
                    for product in (card,pack):
                        path=f'/api/v1/inventory/{copies[n,product]}/image'
                        response=await client.get(path,headers=headers(n));assert response.status_code==200,response.text
                        expected=physical if n==0 and product==card else card_media if product==card else pack_media
                        assert response.headers['x-drop-rate-media-id']==str(expected)
                        assert response.content==PNG and 'no-store' in response.headers['cache-control']
                for n in (1,2):
                    assert (await client.get(f'/api/v1/inventory/{copies[0,card]}/image',headers=headers(n))).status_code==404
                path=f'/api/v1/inventory/{copies[1,card]}/image'
                assert (await client.get(path)).status_code==401
                assert (await client.get(path,headers=headers(1,True))).status_code==401
                assert not any('wrong-' in u or '/dead.' in u for u in outbound)
                assert len(outbound)==6, 'Denied requests must not fetch anything'
        for t,rows in before.items():assert rows==await db.fetch(f'select * from tcg.{t} order by id')
        assert audit_before==await db.fetch('select * from tcg.audit_events')
        await db.execute('update tcg.owner_memberships set active=false where user_id=$1',actors[2])
        async with user_connection(pool,actors[2],'revoked') as c:
            assert await c.fetchval('select count(*) from tcg.media_assets where id=$1',pack_media)==0
        print('PASS: original uploader filter and product RLS failures reproduced; shared card/product references resolve for separate owners; physical media stays private; exact language/variant and source gates; signed JWT/expired/anonymous/foreign access checks; GET snapshots unchanged. Real PostgreSQL; local issuer and mocked provider bytes, not a live seller login.')
    finally:
        auth._jwk_client.cache_clear()
        if pool: await pool.close()
        await db.close()
        if server: await asyncio.to_thread(server.shutdown);server.server_close()

if __name__=='__main__': asyncio.run(main())
