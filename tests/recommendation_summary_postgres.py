"""Real PostgreSQL and signed local-issuer HTTP; synthetic owners, no production writes."""
import asyncio, json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4
import asyncpg, httpx, jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from app import auth, owner_portal_api, owner_inventory, inventory_market_values
from app.db import _init_connection
from shared_reference_postgres import SCHEMA
from shared_reference_fixture import install_reference_schema

ROOT = Path(__file__).resolve().parents[1]

async def main():
    dsn = os.environ['RECOMMENDATION_TEST_DSN']; url = urlsplit(dsn)
    assert url.hostname in ('localhost', '127.0.0.1') and url.path == '/recommendation_test'
    db = await asyncpg.connect(dsn); await _init_connection(db)
    pool = server = None
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute(SCHEMA); await install_reference_schema(db)
        await db.execute((ROOT/'database/migrations/20260925154423_media_assets_registry.sql').read_text())
        await db.execute('alter table tcg.media_assets add column capture_context text,add column shopify_cdn_url text')
        for name in ('20260927160758_media_rights_resolver.sql','20260928224759_sealed_product_media.sql','20261011211000_shared_canonical_product_images.sql'):
            await db.execute((ROOT/'database/migrations'/name).read_text())
        owners=[uuid4(),uuid4()]; actors=[uuid4(),uuid4()]; products=[uuid4() for _ in range(4)]
        for n in range(2):
            await db.execute('insert into auth.users values($1)',actors[n])
            await db.execute("insert into tcg.owners values($1,$2,'CONSIGNOR',null,1000,true)",owners[n],f'Synthetic owner {n}')
            await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",actors[n],owners[n])
        for index, product in enumerate(products):
            await db.execute("insert into tcg.catalogue_products values($1,$2,'One Piece',$3,'Synthetic set',$4,'Foil','SR','Japanese')",product,'SEALED' if index==1 else 'CARD',f'Synthetic {index}',f'TEST-{index:03}')
        async def snap(product,condition=None,company=None,grade=None,seal=None,market=1200,recommended=1200,guide=False):
            evidence={'method':'CATALOGUE_CARDMARKET_V1','input_sale_count':0,'valuation_kind':'REFERENCE_ESTIMATE','quote':{'source':'TCGDEX_CARDMARKET'}} if guide else {'method':'CATALOGUE_EBAY_V4','input_sale_count':5}
            return await db.fetchval('''insert into tcg.catalogue_market_snapshots(catalogue_id,identity_digest,basis_key,basis_condition,basis_language,grading_company,grade,seal_status,
              market_value_minor,recommended_retail_minor,confidence,algorithm_version,oldest_sale_at,evidence_checked_at,calculation_day,evidence_digest,evidence)
              select id,md5(concat_ws(chr(31),product_type,game,name,set_name,card_number,variant,rarity,language)),$2,$3,'Japanese',$4,$5,$6,
                $7,$8,0.8,'drop-rate-market-v4',case when $9 then null else now()-interval '10 days' end,clock_timestamp(),current_date,$2,$10::jsonb
              from tcg.catalogue_products where id=$1 returning id''',product,str(uuid4()),condition,company,grade,seal,market,recommended,guide,json.dumps(evidence))
        await snap(products[0],condition='Near Mint')
        await snap(products[0],company='PSA',grade='10',market=9900,recommended=9900)
        await snap(products[1],seal='SEALED',market=866,recommended=866)
        await snap(products[2],market=3,recommended=100,guide=True)
        ids=[[],[]]
        for n in range(2):
            profiles=[(products[0],'Near Mint',None,None,None)]*2+[(products[0],None,'PSA','10',None)]+[(products[1],None,None,None,'SEALED')]*2+[(products[2],'Near Mint',None,None,None)]
            for position,(product,condition,company,grade,seal) in enumerate(profiles):
                identifier=uuid4(); ids[n].append(identifier)
                await db.execute('''insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,language,condition,grading_company,grade,seal_status,
                  store_price_minor,acquisition_cost_minor,recommended_retail_minor) values($1,$2,$3,$4,'Japanese',$5,$6,$7,$8,$9,$10,999999)''',
                  identifier,f'INV-SYN-{n}-{position}',owners[n],product,condition,company,grade,seal,(1000+n*500) if position<2 else None,50+n*100)
        for position in range(93):
            await db.execute("insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,language,condition,recommended_retail_minor) values($1,$2,$3,$4,'Japanese','Near Mint',999999)",uuid4(),f'INV-UNPRICED-{position}',owners[0],products[3])
        async def setup(c): await c.execute('set role tcg_api')
        pool=await asyncpg.create_pool(dsn,min_size=1,max_size=3,init=_init_connection,setup=setup)
        key=ec.generate_private_key(ec.SECP256R1()); public=json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key())); public.update(kid='summary-test',use='sig',alg='ES256')
        class JWKS(BaseHTTPRequestHandler):
            def do_GET(self):
                body=json.dumps({'keys':[public]}).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(body)
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),JWKS); threading.Thread(target=server.serve_forever,daemon=True).start()
        settings=SimpleNamespace(jwks_url=f'http://127.0.0.1:{server.server_port}/jwks',auth_audience='authenticated',auth_issuer='https://summary-fixture.invalid/auth',shopify_seller_sync_enabled=False,shopify_publish_enabled=False)
        def headers(n,expired=False):
            now=int(time.time()); token=jwt.encode(dict(sub=str(actors[n]),aud='authenticated',iss=settings.auth_issuer,role='authenticated',iat=now-20,exp=now-1 if expired else now+600),key,algorithm='ES256',headers={'kid':'summary-test'})
            return {'Authorization':'Bearer '+token}
        app=FastAPI(); app.state.db_pool=pool
        for router in (owner_portal_api.router,owner_inventory.router,inventory_market_values.router): app.include_router(router)
        @app.middleware('http')
        async def context(request,call_next): request.state.request_id='summary-test'; return await call_next(request)
        async def state():
            return {table:await db.fetchval(f"select coalesce(jsonb_agg(to_jsonb(r) order by to_jsonb(r)::text),'[]'::jsonb) from tcg.{table} r") for table in ('inventory_items','catalogue_market_snapshots','pricing_snapshots','shopify_inventory_links','media_assets','audit_events')}
        before=await state(); auth._jwk_client.cache_clear()
        with patch.object(auth,'get_settings',return_value=settings),patch.object(owner_inventory,'get_settings',return_value=settings):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
                async def overview(n):
                    response=await client.get('/api/v1/owner/overview',headers=headers(n)); assert response.status_code==200,response.text
                    return response.json()['summary']
                for _ in range(2):
                    a,b=await overview(0),await overview(1)
                    assert a['active_inventory_count']==99 and a['active_recommended_count']==6 and a['active_unrecommended_count']==93
                    assert a['active_market_value_minor']==14035 and a['active_recommended_retail_minor']==14132
                    assert a['recorded_asking_value_minor']==2000 and a['recorded_asking_count']==2 and a['recommendation_guide_count']==1
                    assert a['active_recommended_retail_minor']==b['active_recommended_retail_minor'] and b['recorded_asking_value_minor']==3000
                for n in range(2):
                    detail=await client.get(f'/api/v1/owner/inventory/{ids[n][0]}',headers=headers(n)); assert detail.status_code==200,detail.text
                    item=detail.json()['item']; assert item['recommended_retail_minor']==1200 and item['store_price_minor']==1000+n*500
                    response=await client.get('/api/v1/inventory/market-values',params=[('inventory_id',str(x)) for x in ids[n]],headers=headers(n)); assert response.status_code==200,response.text
                    assert sum(x['recommended_retail_minor'] for x in response.json()['items'])==14132
                assert (await client.get('/api/v1/owner/overview')).status_code==401
                assert (await client.get('/api/v1/owner/overview',headers=headers(0,True))).status_code==401
                assert (await client.get(f'/api/v1/owner/inventory/{ids[1][0]}',headers=headers(0))).status_code==404
                assert before==await state(),'Reading recommendations mutated stored data'
                await snap(products[0],condition='Near Mint',market=1300,recommended=1300)
                after_snapshot=await state()
                assert (await overview(0))['active_recommended_retail_minor']==14332
                assert (await overview(1))['active_recommended_retail_minor']==14332
                assert after_snapshot==await state()
                await db.execute('update tcg.owner_memberships set active=false where user_id=$1',actors[1])
                assert (await client.get('/api/v1/owner/overview',headers=headers(1))).status_code==403
        print('PASS: 99-copy partial summary, 6 shared recommendations including grade/seal/guide, independent asking prices, list/detail/overview equality, repeated GETs, new immutable snapshot, owner isolation and expiry/revocation. Real PostgreSQL and signed local-JWKS HTTP; no real provider or production login.')
    finally:
        auth._jwk_client.cache_clear()
        if pool: await pool.close()
        await db.close()
        if server: await asyncio.to_thread(server.shutdown); server.server_close()

if __name__=='__main__': asyncio.run(main())
