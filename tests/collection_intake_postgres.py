"""Signed HTTP + restricted PostgreSQL role: collection save is not publication.

Synthetic localhost DB/JWKS and stub certificate provider. Actual physical-state
migrations and grader/certificate uniqueness index; not a production sign-in.
"""
from __future__ import annotations
import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI

from app import catalogue_browser, auth, inventory_intake, owner_portal_api, owner_books, seller_channel_sync, book_recognition, recognition
from collection_browse_fixture import prepare as prepare_browse, exercise as exercise_browse
from collection_books_fixture import prepare as prepare_books, exercise as exercise_books
from collection_book_scanner_fixture import prepare as prepare_scanner, exercise as exercise_scanner
from collection_book_research_fixture import exercise as exercise_book_research
from collection_auto_book_fixture import exercise as exercise_auto_books
from book_catalogue_seed_fixture import exercise as exercise_book_catalogue_seed
from app.access_control import require_platform_admin_request
from app.db import _init_connection
from owner_auto_import_postgres import SCHEMA

ROOT=Path(__file__).resolve().parents[1]

async def main():
    dsn=os.environ['COLLECTION_TEST_DSN'];u=urlsplit(dsn)
    assert u.hostname in {'127.0.0.1','localhost'} and u.path=='/collection_intake_test'
    db=await asyncpg.connect(dsn);await _init_connection(db);pool=None;server=None
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"),'Disposable empty DB required'
        await db.execute(SCHEMA)
        await db.execute('''alter table tcg.inventory_items add column intake_request_key uuid unique,
          add column version int default 1,add column created_at timestamptz default now(),add column updated_at timestamptz default now(),
          add column acquisition_date date,add column storage_location_id uuid,add column location text,
          add column store_price_minor bigint check(store_price_minor is null or store_price_minor>=100),
          add column market_value_minor bigint,add column recommended_retail_minor bigint,add column pricing_updated_at timestamptz,
          add column latest_pricing_snapshot_id uuid;
          alter table tcg.inventory_items alter column currency set default 'GBP';
          alter table tcg.inventory_items add constraint fixture_grade_pair check((grading_company is null and grade is null and certificate_number is null) or (grading_company is not null and grade is not null));
          create table tcg.recognition_runs(id uuid primary key,owner_id uuid,status text,decision text,top_catalogue_id uuid);
          create table tcg.recognition_candidates(id uuid default gen_random_uuid(),run_id uuid,catalogue_id uuid,rank int,hard_rejected bool default false);
          create table tcg.recognition_feedback(id uuid default gen_random_uuid(),owner_id uuid,run_id uuid,outcome text,selected_catalogue_id uuid,created_at timestamptz default now());
          create table tcg.catalogue_product_profiles(catalogue_id uuid,collectible_type text,identity_status text);
          create table tcg.sealed_product_details(catalogue_id uuid,identity_status text);
          create table tcg.storage_locations(id uuid,owner_id uuid,code text,active bool);
          create table tcg.request_receipts(id uuid default gen_random_uuid(),owner_id uuid,request_key uuid,payload_hash text,response jsonb,unique(owner_id,request_key));
          create table tcg.shopify_inventory_links(id uuid);create table tcg.ebay_inventory_links(id uuid);create table tcg.financial_ledger_entries(id uuid);
          grant select on all tables in schema tcg to tcg_api;
          grant insert on tcg.request_receipts to tcg_api;
          alter table tcg.recognition_runs enable row level security;
          create policy own_scan on tcg.recognition_runs to tcg_api using(owner_id in(select id from tcg.owners));
          alter table tcg.recognition_feedback enable row level security;
          create policy own_feedback on tcg.recognition_feedback to tcg_api using(owner_id in(select id from tcg.owners));
          alter table tcg.request_receipts enable row level security;
          create policy own_receipts on tcg.request_receipts to tcg_api using(owner_id in(select id from tcg.owners)) with check(owner_id in(select id from tcg.owners));''')
        for name in ('202609230016_harden_inventory_physical_state.sql','202609240005_inventory_physical_state_separation.sql','20261001034809_unique_graded_certificate.sql'):
            await db.execute((ROOT/'database/migrations'/name).read_text())
        await prepare_books(db, ROOT)
        guard=await db.fetchval("select pg_get_functiondef('tcg.validate_inventory_condition_state()'::regprocedure)")
        a,b,f,ua,ub,uf,card,pack,run,rejected,packrun=[uuid4() for _ in range(11)]
        await db.executemany("insert into tcg.owners(id,display_name,owner_type,commission_bps) values($1,$2,$3,1000)",[(a,'Fixture seller A','CONSIGNOR'),(b,'Fixture seller B','CONSIGNOR'),(f,'Fixture founder','FOUNDER')])
        await db.executemany("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,$3)",[(ua,a,'OWNER'),(ub,b,'OWNER'),(uf,f,'PLATFORM_ADMIN')])
        await db.executemany("insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language) values($1,$2,$3,'One Piece',$4,'Test set','OP99-001','Parallel','SR','Japanese')",[(card,'collection:card','CARD','Test card'),(pack,'collection:pack','SEALED','Test pack')])
        for rid,kind,hard in ((run,card,False),(rejected,card,True),(packrun,pack,False)):
            await db.execute("insert into tcg.recognition_runs values($1,$2,'EXACT_CANDIDATE','EXACT_CANDIDATE',$3)",rid,a,kind)
            await db.execute('insert into tcg.recognition_candidates(run_id,catalogue_id,rank,hard_rejected) values($1,$2,1,$3)',rid,kind,hard)
            await db.execute("insert into tcg.recognition_feedback(owner_id,run_id,outcome,selected_catalogue_id) values($1,$2,'CONFIRMED_TOP',$3)",a,rid,kind)
        await db.execute("insert into tcg.catalogue_product_profiles(catalogue_id,system_code,collectible_type,identity_status) values($1,'ONE_PIECE_CARD_GAME','SEALED','VERIFIED')",pack)
        await db.execute("insert into tcg.sealed_product_details values($1,'VERIFIED')",pack)
        private=ec.generate_private_key(ec.SECP256R1());public=json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()));public.update(kid='collection-fixture',use='sig',alg='ES256')
        class JWKS(BaseHTTPRequestHandler):
            def do_GET(self):
                data=json.dumps({'keys':[public]}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),JWKS);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        settings=SimpleNamespace(jwks_url=f'http://127.0.0.1:{server.server_port}/jwks',auth_issuer='https://collection-fixture.invalid/auth/v1',auth_audience='authenticated',shopify_seller_sync_enabled=False,shopify_publish_enabled=False)
        def headers(actor,key,**changes):
            now=int(time.time());claims={'sub':str(actor),'iss':settings.auth_issuer,'aud':settings.auth_audience,'iat':now,'exp':now+300,'role':'authenticated'};claims.update(changes)
            return {'Authorization':'Bearer '+jwt.encode(claims,private,algorithm='ES256',headers={'kid':'collection-fixture'}),'Idempotency-Key':str(key)}
        async def setup(c):await c.execute('set role tcg_api')
        pool=await asyncpg.create_pool(dsn,min_size=1,max_size=5,init=_init_connection,setup=setup)
        app=FastAPI();app.state.db_pool=pool
        @app.middleware('http')
        async def request_id(request,call_next):request.state.request_id='collection-http-fixture';return await call_next(request)
        await prepare_browse(db)
        app.include_router(catalogue_browser.router)
        app.include_router(owner_portal_api.router)
        app.include_router(owner_books.router)
        app.include_router(book_recognition.router)
        app.include_router(recognition.router)
        app.include_router(inventory_intake.router,dependencies=[Depends(require_platform_admin_request)])
        app.include_router(seller_channel_sync.router)
        no_pricing=AsyncMock(side_effect=AssertionError('Collection save waited for pricing'))
        no_publish=AsyncMock(side_effect=AssertionError('Collection save published'))
        no_provider=AsyncMock(side_effect=owner_portal_api.CertificateProviderConfigurationError('Not configured in fixture'))
        auth._jwk_client.cache_clear()
        with patch.object(auth,'get_settings',return_value=settings),patch.object(seller_channel_sync,'get_settings',return_value=settings),patch.object(owner_portal_api,'_recalculate_one',no_pricing),patch.object(owner_portal_api,'lookup_grading_certificate',no_provider),patch.object(seller_channel_sync,'publish_inventory_to_shopify',no_publish):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://collection.test') as client:
                endpoint='/api/v1/owner/recognition-intake';payload={'recognition_run_id':str(run),'selected_catalogue_id':str(card)};key=uuid4()
                for actor,extra,status in ((None,{},401),(ua,{'exp':int(time.time())-60},401),(ub,{},404),(uf,{},403)):
                    resp=await client.post(endpoint,json=payload,headers=headers(actor,key,**extra) if actor else {})
                    assert resp.status_code==status,resp.text
                before=await db.fetchval('select count(*) from tcg.inventory_items')
                results=await asyncio.gather(*[client.post(endpoint,json=payload,headers=headers(ua,key)) for _ in range(2)])
                assert all(r.status_code==201 for r in results),[r.text for r in results]
                ids={r.json()['inventory']['id'] for r in results};assert len(ids)==1
                assert sorted(r.json()['replayed'] for r in results)==[False,True]
                saved=await db.fetchrow('select * from tcg.inventory_items where id=$1',UUID(next(iter(ids))))
                assert saved['owner_id']==a and saved['status']=='DRAFT' and saved['sale_intent']=='PERSONAL_COLLECTION'
                assert saved['condition'] is None and saved['acquisition_cost_minor'] is None and saved['store_price_minor'] is None
                assert saved['language']=='Japanese' and not saved['identity_confirmed']
                assert await db.fetchval('select count(*) from tcg.inventory_items')==before+1
                for data,k in (({**payload,'language':'English'},uuid4()),({**payload,'recognition_run_id':str(rejected)},uuid4()),({**payload,'condition':'Near Mint'},key)):
                    r=await client.post(endpoint,json=data,headers=headers(ua,k));assert r.status_code in (409,422),r.text
                assert await db.fetchval('select count(*) from tcg.inventory_items')==before+1
                sealed=await client.post(endpoint,json={'recognition_run_id':str(packrun),'selected_catalogue_id':str(pack),'seal_status':'SEALED'},headers=headers(ua,uuid4()))
                assert sealed.status_code==201,sealed.text
                assert sealed.json()['inventory']['identity_confirmed'] and sealed.json()['inventory']['sale_intent']=='PERSONAL_COLLECTION'
                graded={'selected_catalogue_id':str(card),'grading_company':'PSA','grade':'10','certificate_number':'12345678','language':'Japanese'}
                gkey=uuid4();slabpath='/api/v1/owner/graded-certificate-intake'
                slabs=await asyncio.gather(*[client.post(slabpath,json=graded,headers=headers(ua,gkey)) for _ in range(2)])
                assert all(r.status_code==201 for r in slabs),[r.text for r in slabs]
                assert len({r.json()['inventory']['id'] for r in slabs})==1
                assert all(r.json()['inventory']['sale_intent']=='PERSONAL_COLLECTION' for r in slabs)
                assert (await client.post(slabpath,json=graded,headers=headers(ub,uuid4()))).status_code==409
                founder=await client.post('/api/v1/inventory/intake',json={'catalogue_id':str(card)},headers=headers(uf,uuid4()))
                assert founder.status_code==201,founder.text
                assert founder.json()['inventory']['sale_intent']=='PERSONAL_COLLECTION'
                assert (await client.post('/api/v1/inventory/intake',json={'catalogue_id':str(card)},headers=headers(ua,uuid4()))).status_code==403
                r=await client.post(f'/api/v1/owner/inventory/{saved["id"]}/channels/shopify/sync',json={'version':1},headers=headers(ua,uuid4()))
                assert r.status_code==409,r.text
                await exercise_browse(client,db,headers,ua,ub,a,b,card,pack)
                book_count = await exercise_books(client,db,headers,ua,ub,uf,a,b)
                await prepare_scanner(db,ROOT,(ua,ub,uf))
                await exercise_scanner(client,db,pool,headers,settings,ua,ub,uf,a,b)
                await exercise_book_research(client,db,pool,headers,settings,ua,ub,a)
                await exercise_auto_books(client,db,headers,settings,ua,ub)
                await db.execute('update tcg.owner_memberships set active=false where user_id=$1',ua)
                assert (await client.post(endpoint,json=payload,headers=headers(ua,key))).status_code==403
                assert no_pricing.await_count==0 and no_publish.await_count==0
        for table in ('shopify_inventory_links','ebay_inventory_links','financial_ledger_entries'):
            assert await db.fetchval(f'select count(*) from tcg.{table}')==0
        assert await db.fetchval('select count(*) from tcg.catalogue_products')==3+book_count
        assert await db.fetchval("select pg_get_functiondef('tcg.validate_inventory_condition_state()'::regprocedure)")==guard
        assert not await db.fetchval('select rolbypassrls from pg_roles where rolname=$1','tcg_api')
        await exercise_book_catalogue_seed(db, (ub, uf))
        print('PASS: actual physical-state migrations + signed HTTP/RLS: optional cost/condition/price, canonical language, raw/slab/sealed, concurrent replay, changed payload, wrong owner/role, expired/revoked access, global certificate uniqueness, no pricing/publication/financial writes. Synthetic issuer and provider only.')
    finally:
        auth._jwk_client.cache_clear()
        if pool:await pool.close()
        await db.close()
        if server:await asyncio.to_thread(server.shutdown);server.server_close();thread.join(timeout=2)
if __name__=='__main__':asyncio.run(main())
