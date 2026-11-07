"""Restricted PostgreSQL + real JWT/JWKS-authenticated Business API checks.
Disposable localhost database only. Actual founder-roster migration plus relevant
schema/production-equivalent SELECT policies; not a real Supabase sign-in.
"""
from __future__ import annotations
import asyncio, json, os, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import patch
from uuid import uuid4
import asyncpg, httpx, jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from app import auth, access_control, founder_accounts
from app.db import _init_connection, user_connection
ROOT=Path(__file__).resolve().parents[1]
SCHEMA='''
create role tcg_api nologin nosuperuser nobypassrls;
create role anon nologin;create role authenticated nologin;
create schema auth;create schema tcg;
create table auth.users(id uuid primary key,email_confirmed_at timestamptz);
create table tcg.owners(id uuid primary key,display_name text,username text,owner_type text,founder_slot smallint,active bool default true);
create table tcg.owner_memberships(id uuid default gen_random_uuid(),user_id uuid,owner_id uuid,role text,active bool default true,created_at timestamptz default now());
create function tcg.current_user_id() returns uuid language sql stable set search_path=pg_catalog as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
create table tcg.audit_events(actor text,request_id text,action text,entity_type text,entity_id uuid,old_values jsonb,new_values jsonb);
create table tcg.catalogue_products(id uuid primary key,product_type text,name text,card_number text,set_name text,game text,variant text);
create table tcg.inventory_items(id uuid primary key,inventory_code text,owner_id uuid,catalogue_id uuid,language text,condition text,grading_company text,grade text,certificate_number text,location text,pricing_updated_at timestamptz,updated_at timestamptz default now(),status text,sale_intent text,market_value_minor bigint,store_price_minor bigint);
create table tcg.financial_ledger_entries(id uuid primary key,owner_id uuid,amount_minor bigint,entry_type text,funds_status text);
create table tcg.payout_requests(id uuid primary key,owner_id uuid,payout_code text,amount_minor bigint,currency text,status text,created_at timestamptz default now());
create table tcg.shopify_inventory_links(inventory_id uuid,owner_id uuid,sync_state text,test_mode bool default false,linked_at timestamptz default now());
create table tcg.ebay_inventory_links(inventory_id uuid,owner_id uuid,state text,created_at timestamptz default now());
create table tcg.orders(id uuid primary key,order_number text,source text,status text,created_at timestamptz default now());
create table tcg.order_items(id uuid primary key,order_id uuid,inventory_id uuid,owner_id uuid,sale_price_minor bigint);
'''
POLICIES='''
grant usage on schema tcg to tcg_api;
grant select on tcg.owners,tcg.owner_memberships,tcg.catalogue_products,tcg.inventory_items,tcg.financial_ledger_entries,tcg.payout_requests,tcg.shopify_inventory_links,tcg.ebay_inventory_links,tcg.orders,tcg.order_items to tcg_api;
alter table tcg.owner_memberships enable row level security;
create policy membership_read on tcg.owner_memberships for select to tcg_api using(user_id=tcg.current_user_id() and active);
alter table tcg.owners enable row level security;
create policy owner_read on tcg.owners for select to tcg_api using(active and (tcg.is_platform_admin() or exists(select 1 from tcg.owner_memberships m where m.owner_id=owners.id and m.user_id=tcg.current_user_id() and m.active)));
alter table tcg.orders enable row level security;
create policy own_records on tcg.orders for select to tcg_api using(exists(select 1 from tcg.order_items oi where oi.order_id=orders.id and oi.owner_id in(select id from tcg.owners)));
alter table tcg.shopify_inventory_links enable row level security;
create policy internal_link_lookup on tcg.shopify_inventory_links for select to tcg_api using(true);
alter table tcg.ebay_inventory_links enable row level security;
create policy ebay_inventory_links_api_read on tcg.ebay_inventory_links for select to tcg_api using(true);
'''

async def main():
    dsn=os.environ['BUSINESS_TEST_DSN'];parsed=urlsplit(dsn)
    assert parsed.hostname in ('localhost','127.0.0.1') and parsed.path=='/business_area_test'
    db=await asyncpg.connect(dsn);await _init_connection(db);pool=None;server=None
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"),'Refuse nonempty application database'
        await db.execute(SCHEMA)
        actors=[uuid4() for _ in range(6)];owners=[uuid4() for _ in range(6)];card=uuid4()
        for i in range(6):
            await db.execute('insert into auth.users values($1,now())',actors[i])
            await db.execute('insert into tcg.owners values($1,$2,$3,$4,$5,true)',owners[i],f'Test owner {i}',f'owner{i}', 'FOUNDER' if i<3 else 'CONSIGNOR',i+1 if i<3 else None)
            await db.execute('insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,$3)',actors[i],owners[i],'PLATFORM_ADMIN' if i<3 else 'OWNER')
        await db.execute((ROOT/'database/migrations/20261002024856_unified_founder_app_access.sql').read_text())
        assert await db.fetchval('select count(*) from tcg.founder_app_accounts')==3
        await db.execute(POLICIES)
        for table in ('inventory_items','financial_ledger_entries','payout_requests','order_items'):
            await db.execute(f'alter table tcg.{table} enable row level security;create policy own_records on tcg.{table} to tcg_api using(owner_id in(select id from tcg.owners)) with check(owner_id in(select id from tcg.owners));')
        await db.execute("insert into tcg.catalogue_products values($1,'CARD','Shared exact card','001','Exact set','Pokemon','Foil')",card)
        stock=[]
        for i in range(6):
            item=uuid4();stock.append(item)
            await db.execute("insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,language,condition,status,sale_intent,market_value_minor,store_price_minor) values($1,$2,$3,$4,'English','Near Mint',$5,'FOR_SALE',$6,1000)",item,f'INV-TEST-{i}',owners[i],card, 'APPROVED' if i<3 else 'DRAFT', None if i>=3 else 800)
        order=uuid4();await db.execute("insert into tcg.orders(id,order_number,source,status) values($1,'TEST-ORDER','SHOPIFY','PAID')",order)
        await db.execute('insert into tcg.order_items values($1,$2,$3,$4,1000)',uuid4(),order,stock[3],owners[3])
        await db.execute("insert into tcg.financial_ledger_entries values($1,$2,1000,'SALE_REVENUE','AVAILABLE')",uuid4(),owners[3])
        await db.execute("insert into tcg.payout_requests(id,owner_id,payout_code,amount_minor,currency,status) values($1,$2,'TEST-PAYOUT',100,'GBP','REQUESTED')",uuid4(),owners[3])
        await db.execute("insert into tcg.shopify_inventory_links values($1,$2,'PUBLISHED',false,now())",stock[0],owners[0])
        from shared_reference_fixture import install_reference_schema
        await install_reference_schema(db)
        async def setup(conn):await conn.execute('set role tcg_api')
        pool=await asyncpg.create_pool(dsn,min_size=1,max_size=3,init=_init_connection,setup=setup)
        private=ec.generate_private_key(ec.SECP256R1());public=json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()));public.update(kid='business-fixture',use='sig',alg='ES256')
        class JWKS(BaseHTTPRequestHandler):
            def do_GET(self):
                body=json.dumps({'keys':[public]}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),JWKS);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        settings=SimpleNamespace(jwks_url=f'http://127.0.0.1:{server.server_port}/jwks',auth_audience='authenticated',auth_issuer='https://business-fixture.invalid/auth/v1')
        def headers(actor,**extra):
            now=int(time.time());claims=dict(sub=str(actor),iss=settings.auth_issuer,aud='authenticated',iat=now,exp=now+600,role='authenticated');claims.update(extra)
            return {'Authorization':'Bearer '+jwt.encode(claims,private,algorithm='ES256',headers={'kid':'business-fixture'})}
        app=FastAPI();app.state.db_pool=pool
        @app.middleware('http')
        async def request_id(request,call_next):
            request.state.request_id='business-fixture';response=await call_next(request);response.headers['Cache-Control']='no-store';return response
        app.include_router(access_control.router);app.include_router(founder_accounts.router)
        tables=('owners','owner_memberships','inventory_items','financial_ledger_entries','payout_requests','shopify_inventory_links','order_items','orders')
        async def snapshot():
            return {t:await db.fetchval(f"select coalesce(jsonb_agg(to_jsonb(x) order by to_jsonb(x)::text),'[]'::jsonb) from tcg.{t} x") for t in tables}
        baseline=await snapshot();auth._jwk_client.cache_clear()
        with patch.object(auth,'get_settings',return_value=settings):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://business.test') as client:
                endpoints=('/api/v1/founder/accounts','/api/v1/founder/accounts/inventory','/api/v1/founder/accounts/activity')
                for endpoint in endpoints:
                    assert (await client.get(endpoint)).status_code==401
                    for changes in ({'exp':int(time.time())-60},{'is_anonymous':True},{'role':'service_role'},{'iss':'https://wrong.invalid'}):
                        assert (await client.get(endpoint,headers=headers(actors[0],**changes))).status_code==401
                    for i in (3,4,5):
                        response=await client.get(endpoint,headers=headers(actors[i],user_metadata={'role':'PLATFORM_ADMIN','founder_slot':1},app_metadata={'business_allowed':True}),params={'owner_id':str(owners[0])})
                        assert response.status_code==403 and 'Test owner' not in response.text
                    for i in (0,1,2):
                        assert (await client.get(endpoint,headers=headers(actors[i]))).status_code==200
                    for verb in ('post','patch','delete'):
                        assert (await getattr(client,verb)(endpoint,headers=headers(actors[0]))).status_code==405
                for i in range(6):
                    result=await client.get('/api/v1/access/me',headers=headers(actors[i]));assert result.status_code==200
                    assert result.json()['access']['business_allowed']==(i<3)
                directory=(await client.get(endpoints[0],headers=headers(actors[0]))).json()
                assert len(directory['accounts'])==6 and directory['read_only']
                assert sum(row['draft_count'] for row in directory['accounts'])==3
                assert sum(row['for_sale_count'] for row in directory['accounts'])==3
                seller=next(row for row in directory['accounts'] if row['id']==str(owners[3]))
                assert seller['username']=='owner3' and seller['available_to_withdraw_minor']==900
                result=(await client.get(endpoints[1],headers=headers(actors[1]),params={'search':'001'})).json()
                assert result['total']==6 and len({row['inventory_code'] for row in result['items']})==6
                selected=(await client.get(endpoints[1],headers=headers(actors[2]),params={'owner_id':str(owners[3])})).json()
                assert selected['total']==1 and selected['items'][0]['inventory_code']=='INV-TEST-3'
                by_username=(await client.get(endpoints[1],headers=headers(actors[0]),params={'search':'owner4'})).json()
                assert by_username['total']==1 and by_username['items'][0]['owner_id']==str(owners[4])
                result=(await client.get(endpoints[1],headers=headers(actors[0]),params={'limit':2,'offset':2})).json()
                assert result['total']==6 and len(result['items'])==2
                for params in ({'limit':101},{'offset':-1},{'owner_id':'not-a-uuid'},{'search':'x'*161}):
                    assert (await client.get(endpoints[1],headers=headers(actors[0]),params=params)).status_code==422
                injected=(await client.get(endpoints[1],headers=headers(actors[0]),params={'search':"' OR true--"})).json();assert injected['total']==0
                history=(await client.get(endpoints[2],headers=headers(actors[0]),params={'owner_id':str(owners[3])})).json()
                assert len(history['sales'])==1 and len(history['payouts'])==1
                assert baseline==await snapshot(),'Business GET mutated stock, owners, orders or money'
                await db.execute("update tcg.owner_memberships set role='PLATFORM_ADMIN' where user_id=$1",actors[5])
                for endpoint in endpoints:assert (await client.get(endpoint,headers=headers(actors[5]))).status_code==403
                old=headers(actors[0]);await db.execute('update tcg.founder_app_accounts set active=false where user_id=$1',actors[0])
                for endpoint in endpoints:assert (await client.get(endpoint,headers=old)).status_code==403
                await db.execute('update tcg.founder_app_accounts set active=true where user_id=$1',actors[0])
                await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",actors[1],owners[4])
                for endpoint in endpoints:assert (await client.get(endpoint,headers=headers(actors[1]))).status_code in (403,409)
                await db.execute('update tcg.owner_memberships set active=false where user_id=$1',actors[2])
                for endpoint in endpoints:assert (await client.get(endpoint,headers=headers(actors[2]))).status_code==403
        async with user_connection(pool,actors[3],'business-rls') as conn:
            assert await conn.fetchval('select count(*) from tcg.owners')==1
            assert await conn.fetchval('select count(*) from tcg.inventory_items')==1
            assert not await conn.fetchval("select has_table_privilege(current_user,'tcg.founder_app_accounts','INSERT')")
        print('PASS: actual founder-roster migration + restricted PostgreSQL policies + signed JWT/JWKS HTTP. Three founders allowed; sellers/forged claims/unregistered admin/expired/revoked/ambiguous denied. Directory, shared-card exact copy ownership, search, pagination and history correct; read-only snapshots unchanged. Local issuer/relevant schema, not production sign-in.')
    finally:
        auth._jwk_client.cache_clear()
        if pool:await pool.close()
        await db.close()
        if server:await asyncio.to_thread(server.shutdown);server.server_close();thread.join(timeout=2)
if __name__=='__main__':asyncio.run(main())
