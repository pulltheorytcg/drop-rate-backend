"""Real PostgreSQL + signed local-issuer HTTP for shared inventory references.
No production credentials, commercial provider requests, or real stock.
"""
import asyncio,base64,json,os,threading,time
from datetime import datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4
import asyncpg,httpx,jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from app import api,auth,owner_inventory,inventory_market_values
from app.db import _init_connection,user_connection
from app.inventory_reference_values import add_shared_reference_values,reference_portfolio,reference_totals
from app.inventory_reference_media import add_shared_inventory_media
from shared_reference_fixture import install_reference_schema
ROOT=Path(__file__).resolve().parents[1]
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jhZkAAAAASUVORK5CYII=')
SCHEMA='''
create schema tcg;create schema auth;create role tcg_api nologin nosuperuser nobypassrls;
create role anon;create role authenticated;
create table auth.users(id uuid primary key);
create table tcg.owners(id uuid primary key,display_name text,owner_type text,founder_slot int,commission_bps int,active bool default true);
create table tcg.owner_memberships(id uuid default gen_random_uuid(),user_id uuid,owner_id uuid,role text,active bool default true,created_at timestamptz default now());
create function tcg.current_user_id() returns uuid language sql stable as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
create table tcg.catalogue_products(id uuid primary key,product_type text,game text,name text,set_name text,card_number text,variant text,rarity text,language text);
create table tcg.catalogue_product_profiles(catalogue_id uuid,identity_status text,attributes jsonb default '{}');
create table tcg.inventory_items(id uuid primary key,inventory_code text,owner_id uuid,catalogue_id uuid,language text,condition text,grading_company text,grade text,seal_status text,certificate_number text,
 status text default 'DRAFT',sale_intent text default 'PERSONAL_COLLECTION',version int default 1,
 market_value_minor bigint,recommended_retail_minor bigint,store_price_minor bigint,pricing_updated_at timestamptz,latest_pricing_snapshot_id uuid,identity_confirmed bool default false,
 acquisition_cost_minor bigint,storage_location_id uuid,created_at timestamptz default now(),updated_at timestamptz default now());
create table tcg.pricing_snapshots(id uuid,inventory_id uuid,catalogue_id uuid,owner_id uuid,confidence numeric,evidence jsonb,source_count int,observation_count int,newest_observation_at timestamptz);
create table tcg.shopify_inventory_links(inventory_id uuid,owner_id uuid,sync_state text,test_mode bool,last_synced_at timestamptz);
create table tcg.audit_events(actor text,request_id text,action text,entity_type text,entity_id uuid,old_values jsonb,new_values jsonb);
grant usage on schema tcg to tcg_api;grant select on all tables in schema tcg to tcg_api;
alter table tcg.owner_memberships enable row level security;
create policy member_read on tcg.owner_memberships for select to tcg_api using(user_id=tcg.current_user_id() and active);
alter table tcg.owners enable row level security;
create policy owner_read on tcg.owners for select to tcg_api using(active and id in(select owner_id from tcg.owner_memberships));
alter table tcg.inventory_items enable row level security;alter table tcg.inventory_items force row level security;
create policy inventory_read on tcg.inventory_items for select to tcg_api using(owner_id in(select id from tcg.owners));
'''
async def main():
 dsn=os.environ['SHARED_REFERENCE_TEST_DSN'];url=urlsplit(dsn)
 assert url.hostname in ('localhost','127.0.0.1') and url.path=='/shared_reference_test'
 db=await asyncpg.connect(dsn);await _init_connection(db);pool=None;server=None
 try:
  assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
  await db.execute(SCHEMA);await install_reference_schema(db)
  for name in ('20260925154423_media_assets_registry.sql',):await db.execute((ROOT/'database/migrations'/name).read_text())
  await db.execute('alter table tcg.media_assets add column capture_context text,add column shopify_cdn_url text')
  for name in ('20260927160758_media_rights_resolver.sql','20260928224759_sealed_product_media.sql','20261011211000_shared_canonical_product_images.sql'):
   await db.execute((ROOT/'database/migrations'/name).read_text())
  owners=[uuid4(),uuid4()];actors=[uuid4(),uuid4()];card=uuid4();raw=[uuid4(),uuid4()];slab=uuid4()
  for n in range(2):
   await db.execute('insert into auth.users values($1)',actors[n])
   await db.execute("insert into tcg.owners values($1,$2,$3,$4,1000,true)",owners[n],f'Synthetic account {n}','FOUNDER' if n==0 else 'CONSIGNOR',1 if n==0 else None)
   await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,$3)",actors[n],owners[n],'PLATFORM_ADMIN' if n==0 else 'OWNER')
  await db.execute("insert into tcg.catalogue_products values($1,'CARD','One Piece','Synthetic card','Exact release','TEST-001','Foil','SR','Japanese')",card)
  for n in range(2):
   await db.execute("insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,language,condition,market_value_minor,store_price_minor,acquisition_cost_minor) values($1,$2,$3,$4,'Japanese','Near Mint',$5,$6,$7)",raw[n],f'INV-TEST-{n}',owners[n],card,1200 if n==0 else None,1500+n*300,100+n*500)
  await db.execute("insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,language,grading_company,grade) values($1,'INV-TEST-SLAB',$2,$3,'Japanese','PSA','10')",slab,owners[1],card)
  async def snap(grade=None,value=1200,age=1):
   return await db.fetchval('''insert into tcg.catalogue_market_snapshots(catalogue_id,identity_digest,basis_key,basis_condition,basis_language,grading_company,grade,
    market_value_minor,recommended_retail_minor,confidence,algorithm_version,oldest_sale_at,evidence_checked_at,calculation_day,evidence_digest,evidence)
    select id,md5(concat_ws(chr(31),product_type,game,name,set_name,card_number,variant,rarity,language)),$2,
      case when $3::text is null then 'Near Mint' end,'Japanese',case when $3::text is not null then 'PSA' end,$3,$4,$4,0.8,'drop-rate-market-v4',now()-interval '10 days',now()-make_interval(days=>$5),current_date,$2,
      '{"method":"CATALOGUE_EBAY_V4","input_sale_count":5}'::jsonb
    from tcg.catalogue_products where id=$1 returning id''',card,str(uuid4()),grade,value,age)
  raw_snapshot=await snap();slab_snapshot=await snap('10',9900)
  async def asset(approval='APPROVED',physical=None,language='Japanese',suffix='shared'):
   return await db.fetchval('''insert into tcg.media_assets(owner_id,catalogue_id,inventory_id,scope,source_type,source_reference,public_source_url,rights_status,rights_basis,approval_status,alt_text,created_by_user_id,approved_by_user_id,approved_at,rights_tier,source_provider,media_language,media_variant,source_status)
     values($1,$2,$3,$4,'OFFICIAL_PROVIDER','synthetic test',$5,'VERIFIED','Synthetic permission',$6,'Fixture',$7,$7,now(),$8,'Fixture',$9,'Foil','ACTIVE') returning id''',owners[0],None if physical else card,physical,'INVENTORY_ITEM' if physical else 'CANONICAL_CARD',f'https://www.onepiece-cardgame.com/{suffix}.png',approval,actors[0],'FIRST_PARTY_CAPTURE' if physical else 'STOREFRONT_ALLOWED',language)
  media=await asset();await asset('PENDING',suffix='pending');await asset(language='English',suffix='wrong-language')
  async def setup(c):await c.execute('set role tcg_api')
  pool=await asyncpg.create_pool(dsn,min_size=1,max_size=3,init=_init_connection,setup=setup)
  tables=('inventory_items','catalogue_products','catalogue_market_snapshots','media_assets','pricing_snapshots','shopify_inventory_links','audit_events')
  async def state():return {t:await db.fetchval(f"select coalesce(jsonb_agg(to_jsonb(x) order by to_jsonb(x)::text),'[]'::jsonb) from tcg.{t} x") for t in tables}
  before=await state()
  profile_values=[]
  for n in range(2):
   async with user_connection(pool,actors[n],'shared-reference') as c:
    visible=await reference_portfolio(c,[owners[n]])
    item=next(row for row in visible if row['id']==raw[n]);profile_values.append(item['reference_value'])
    assert item['market_value_minor']==1200 and item['store_price_minor']==1500+n*300
    assert reference_totals(visible)['valued_count']==(1 if n==0 else 2)
    assert await reference_portfolio(c,[owners[1-n]])==[]
    await add_shared_inventory_media(c,[item]);assert item['image_url'].endswith('/shared.png')
  assert profile_values[0]==profile_values[1]
  key=ec.generate_private_key(ec.SECP256R1());public=json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()));public.update(kid='reference-fixture',use='sig',alg='ES256')
  class JWKS(BaseHTTPRequestHandler):
   def do_GET(self):
    body=json.dumps({'keys':[public]}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
   def log_message(self,*args):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),JWKS);threading.Thread(target=server.serve_forever,daemon=True).start()
  settings=SimpleNamespace(jwks_url=f'http://127.0.0.1:{server.server_port}/jwks',auth_audience='authenticated',auth_issuer='https://reference-fixture.invalid/auth',shopify_seller_sync_enabled=False,shopify_publish_enabled=False)
  def headers(n,expired=False):
   now=int(time.time());return {'Authorization':'Bearer '+jwt.encode(dict(sub=str(actors[n]),aud='authenticated',iss=settings.auth_issuer,role='authenticated',iat=now-20,exp=now-1 if expired else now+600),key,algorithm='ES256',headers={'kid':'reference-fixture'})}
  app=FastAPI();app.state.db_pool=pool;app.include_router(api.router);app.include_router(inventory_market_values.router);app.include_router(owner_inventory.router)
  @app.middleware('http')
  async def context(request,call_next):request.state.request_id='reference-fixture';return await call_next(request)
  outbound=[];real_client=httpx.AsyncClient
  def remote(req):
   assert 'authorization' not in req.headers;outbound.append(str(req.url));return httpx.Response(200,headers={'content-type':'image/png'},content=PNG)
  def provider(**kwargs):return real_client(transport=httpx.MockTransport(remote),**kwargs)
  auth._jwk_client.cache_clear()
  with patch.object(auth,'get_settings',return_value=settings),patch.object(owner_inventory,'get_settings',return_value=settings):
   async with real_client(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
    refs=[]
    for n in range(2):
     endpoint='/api/v1/inventory/market-values'
     response=await client.get(endpoint,params=[('inventory_id',str(v)) for v in raw],headers=headers(n));assert response.status_code==200,response.text
     rows=response.json()['items'];assert len(rows)==1 and rows[0]['id']==str(raw[n]);refs.append(rows[0]['reference_value'])
     assert (await client.get(endpoint,params={'inventory_id':str(raw[n])})).status_code==401
     assert (await client.get(endpoint,params={'inventory_id':str(raw[n])},headers=headers(n,True))).status_code==401
    assert refs[0]==refs[1]
    detail=await client.get(f'/api/v1/owner/inventory/{raw[1]}',headers=headers(1));assert detail.status_code==200,detail.text
    assert detail.json()['item']['reference_value']==refs[1]
    graded=await client.get(f'/api/v1/owner/inventory/{slab}',headers=headers(1));assert graded.status_code==200,graded.text
    assert graded.json()['item']['market_value_minor']==9900
    assert (await client.get(f'/api/v1/owner/inventory/{raw[0]}',headers=headers(1))).status_code==404
    with patch.object(api.httpx,'AsyncClient',side_effect=provider):
     for n in range(2):
      image=await client.get(f'/api/v1/inventory/{raw[n]}/image',headers=headers(n));assert image.status_code==200,image.text
      assert image.content==PNG and image.headers['x-drop-rate-media-id']==str(media)
     assert (await client.get(f'/api/v1/inventory/{raw[0]}/image',headers=headers(1))).status_code==404
  assert outbound==['https://www.onepiece-cardgame.com/shared.png']*2
  assert before==await state(),'GET changed stock, price, history, image approval or listing'
  # Pending canonical pictures are not an uploader-only default anymore.
  await db.execute("update tcg.media_assets set approval_status='PENDING' where id=$1",media)
  for n in range(2):
   async with user_connection(pool,actors[n],'pending-art') as c:
    items=await reference_portfolio(c,[owners[n]]);await add_shared_inventory_media(c,items)
    assert all(row['image_url'] is None for row in items)
  await asset(physical=raw[0],suffix='private-copy')
  for n in range(2):
   async with user_connection(pool,actors[n],'private-art') as c:
    items=await reference_portfolio(c,[owners[n]]);await add_shared_inventory_media(c,items)
    own=next(row for row in items if row['id']==raw[n])
    assert (own['image_url'] or '').endswith('/private-copy.png') == (n==0)
  # A guide has its real DB constraint and current-reference function, not a
  # mocked current flag. It cannot become a slab price or ignore revoked maps.
  await db.execute("update tcg.catalogue_products set card_number='TEST-001' where id=$1",card)
  await db.execute("""insert into tcg.catalogue_market_snapshots(catalogue_id,identity_digest,basis_key,basis_language,
    market_value_minor,recommended_retail_minor,confidence,algorithm_version,evidence_checked_at,calculation_day,evidence_digest,evidence)
    select id,md5(concat_ws(chr(31),product_type,game,name,set_name,card_number,variant,rarity,language)),
      'guide','Japanese',800,800,0.5,'drop-rate-market-v4',now(),current_date,'guide-fixture',
      '{"method":"CATALOGUE_CARDMARKET_V1","input_sale_count":0,"valuation_kind":"REFERENCE_ESTIMATE","quote":{"source":"TCGDEX_CARDMARKET"}}'::jsonb
    from tcg.catalogue_products where id=$1""",card)
  await db.execute("insert into tcg.market_source_mappings values($1,'EBAY','REVIEW')",card)
  async with user_connection(pool,actors[1],'mapping-revoked') as c:
   rows=await reference_portfolio(c,[owners[1]])
   assert next(row for row in rows if row['id']==raw[1])['reference_value']['status']=='REFERENCE_ESTIMATE'
   assert next(row for row in rows if row['id']==slab)['market_value_minor'] is None
  await db.execute("insert into tcg.provider_catalogue_mappings(catalogue_id,provider_language,match_status) values($1,'Japanese','REVIEW')",card)
  async with user_connection(pool,actors[1],'guide-map-revoked') as c:
   assert all(row['market_value_minor'] is None for row in await reference_portfolio(c,[owners[1]]))
  await db.execute('delete from tcg.market_source_mappings')
  await db.execute("update tcg.catalogue_products set variant='Different printing' where id=$1",card)
  async with user_connection(pool,actors[1],'changed-identity') as c:
   assert all(row['market_value_minor'] is None for row in await reference_portfolio(c,[owners[1]]))
  # A real shared-cache lookup now reaches both accounts even when no physical
  # snapshot exists. An unfinished copy sees the same range without being valued.
  guide_card=uuid4();guide_items=[uuid4(),uuid4()]
  await db.execute("insert into tcg.catalogue_products values($1,'CARD','Pokemon','Heat Rotom','Destined Rivals','043/182','sv10-043','Unknown','English')",guide_card)
  await db.execute("insert into tcg.reference_sets(provider,system_code,language,set_id,name) values('TCGdex','POKEMON_TCG','English','sv10','Destined Rivals')")
  await db.execute("insert into tcg.reference_cards(provider,system_code,language,provider_id,set_id,name,card_number,number_key) values('TCGdex','POKEMON_TCG','English','sv10-043','sv10','Heat Rotom','043/182','43:/:182')")
  checked=datetime.now(timezone.utc)-timedelta(hours=1)
  quotes=[dict(source='TCGDEX_CARDMARKET',reference_language='English',finish='Normal',
    price_gbp_minor=85,original_minor=100,original_currency='EUR',fx_source='ECB_EURO_REFERENCE_RATES',
    fx_rate_to_gbp='0.85',observed_at=checked.isoformat())]
  quotes.append(dict(quotes[0],finish='Reverse Holofoil',price_gbp_minor=170,original_minor=200))
  await db.execute("insert into tcg.reference_market_prices values('TCGdex','POKEMON_TCG','English','sv10-043',$1::jsonb)",quotes)
  for n in range(2):
   await db.execute("insert into tcg.inventory_items(id,inventory_code,owner_id,catalogue_id,language,condition,store_price_minor) values($1,$2,$3,$4,'English',$5,$6)",guide_items[n],f'GUIDE-{n}',owners[n],guide_card,None if n else 'Near Mint',500+n*100)
  before=await state();displays=[]
  with patch.object(auth,'get_settings',return_value=settings),patch.object(owner_inventory,'get_settings',return_value=settings):
   async with real_client(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
    for n in range(2):
     response=await client.get('/api/v1/inventory/market-values',params=[('inventory_id',str(v)) for v in guide_items],headers=headers(n))
     assert response.status_code==200,response.text
     rows=response.json()['items'];assert len(rows)==1 and rows[0]['id']==str(guide_items[n])
     value=rows[0];displays.append(value['catalogue_reference'])
     assert value['market_value_minor'] is None and value['recommended_retail_minor'] is None
     detail=await client.get(f'/api/v1/owner/inventory/{guide_items[n]}',headers=headers(n))
     if n==0:
      assert detail.status_code==403,'Founder fixture has no seller portal membership'
     else:
      assert detail.status_code==200,detail.text
      assert detail.json()['item']['catalogue_reference']==value['catalogue_reference']
      assert detail.json()['item']['store_price_minor']==500+n*100
  assert displays[0]==displays[1] and displays[0]['market_value_minor']==85 and displays[0]['market_value_high_minor']==170
  assert before==await state(),'Catalogue display wrote a valuation or changed inventory'
  # Search/set display and inventory consume the same dated cache through the
  # restricted role. No ownership is needed for the catalogue value.
  from app.catalogue_display_prices import read_shared_prices,reference_key,with_shared_price
  browse_row=dict(provider='TCGdex',system_code='POKEMON_TCG',language='English',provider_id='sv10-043',
    card_number='043/182',market_value_minor=None,catalogue_id=None,owned_quantity=0)
  browse_row['key']=reference_key(browse_row)
  for n in range(2):
   async with user_connection(pool,actors[n],'immediate-browse') as c:
    prices=await read_shared_prices(c,[browse_row])
    shown=with_shared_price(browse_row,prices)
    assert shown['market_value_minor']==displays[n]['market_value_minor']
    assert shown['market_value_high_minor']==displays[n]['market_value_high_minor']
    assert shown['shared_price']['checked_at'].isoformat()==displays[n]['checked_at']
    assert shown['catalogue_id'] is None and shown['owned_quantity']==0
  assert before==await state(),'Search pricing changed stock, shared prices or ownership'
  await db.execute("insert into tcg.provider_catalogue_mappings(catalogue_id,provider_language,match_status) values($1,'English','REJECTED')",guide_card)
  async with user_connection(pool,actors[1],'rejected-guide') as c:
   value=next(r for r in await reference_portfolio(c,[owners[1]]) if r['id']==guide_items[1])
   assert not value.get('catalogue_reference') and value['market_value_minor'] is None
  await db.execute('update tcg.owner_memberships set active=false where user_id=$1',actors[1])
  async with user_connection(pool,actors[1],'revoked') as c:assert await reference_portfolio(c,[owners[1]])==[]
  print('PASS: same catalogue/profile gives identical shared value and artwork for independent founder/seller records; exact grade; preserved own price/cost and immutable state; real production snapshot/media migrations + restricted PostgreSQL + signed local-JWKS HTTP, expired/foreign/revoked and changed-identity/mapping checks. Provider bytes mocked; not a live seller login.')
 finally:
  auth._jwk_client.cache_clear()
  if pool:await pool.close()
  await db.close()
  if server:await asyncio.to_thread(server.shutdown);server.server_close()
if __name__=='__main__':asyncio.run(main())
