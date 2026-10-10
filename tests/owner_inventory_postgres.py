"""Exercise seller controls and artwork against disposable real PostgreSQL/RLS."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
from fastapi import HTTPException

from app import owner_inventory as api, inventory_sale_intent as intent
from app.db import _init_connection


async def main():
    dsn=os.environ['INVENTORY_TEST_DSN'];url=urlsplit(dsn)
    assert url.hostname in {'localhost','127.0.0.1'} and url.path=='/inventory_test'
    db=await asyncpg.connect(dsn);await _init_connection(db);pool=None
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute('''create schema tcg;create role tcg_api nologin nobypassrls;
          create function tcg.current_user_id() returns uuid language sql stable as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          create table tcg.owners(id uuid primary key,display_name text,owner_type text,founder_slot int,commission_bps int,active bool default true);
          create table tcg.owner_memberships(id uuid default gen_random_uuid(),user_id uuid,owner_id uuid,role text,active bool default true,created_at timestamptz default now());
          create table tcg.catalogue_products(id uuid primary key,identity_key text,product_type text,game text,name text,set_name text,card_number text,variant text,rarity text,language text);
          create table tcg.catalogue_product_profiles(catalogue_id uuid,system_code text,identity_status text,attributes jsonb default '{}',version int default 1,updated_at timestamptz default now());
          create table tcg.reference_sets(provider text,system_code text,language text,set_id text,name text);
          create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,set_id text,name text,card_number text,rarity text,image_url text);
          create table tcg.reference_sealed_products(provider text,system_code text,language text,provider_id text,set_id text,name text,product_type text,image_url text);
          create table tcg.provider_catalogue_mappings(catalogue_id uuid,source_provider text,system_code text,provider_language text,provider_id text,provider_entity_type text,provider_variant_key text,match_status text);
          create table tcg.inventory_items(id uuid primary key,inventory_code text,catalogue_id uuid,owner_id uuid,
            version int default 1,status text,sale_intent text,language text,condition text,seal_status text,
            grading_company text,grade text,certificate_number text,currency text,store_price_minor bigint,
            market_value_minor bigint,recommended_retail_minor bigint,pricing_updated_at timestamptz,
            acquisition_cost_minor bigint,storage_location_id uuid,identity_confirmed bool default false,
            latest_pricing_snapshot_id uuid,intake_request_key uuid unique,source_record jsonb,
            created_at timestamptz default now(),updated_at timestamptz default now());
          create table tcg.shopify_inventory_links(inventory_id uuid,owner_id uuid,sync_state text,test_mode bool,last_synced_at timestamptz);
          create table tcg.media_assets(id uuid default gen_random_uuid(),owner_id uuid,inventory_id uuid,catalogue_id uuid,
            scope text,side text,media_kind text,media_language text,media_variant text,approval_status text,rights_status text,rights_tier text,source_status text,
            revoked_at timestamptz,approved_at timestamptz,created_at timestamptz default now(),shopify_file_status text,shopify_cdn_url text,public_source_url text);
          create table tcg.pricing_snapshots(id uuid,inventory_id uuid,owner_id uuid,catalogue_id uuid,evidence jsonb);
          create table tcg.request_receipts(owner_id uuid,request_key uuid,payload_hash text,response jsonb,unique(owner_id,request_key));
          create table tcg.listing_inventory_members(id uuid,inventory_id uuid,owner_id uuid,state text,created_at timestamptz default now());
          create table tcg.storage_locations(id uuid,active bool);
          create table tcg.shopify_shipping_profiles(owner_id uuid,profile_key text,active bool);
          create table tcg.order_items(id uuid default gen_random_uuid(),owner_id uuid,inventory_id uuid,cost_basis_minor bigint not null check(cost_basis_minor>=0));
          create table tcg.ebay_inventory_links(inventory_id uuid,owner_id uuid,state text);
          create table tcg.test_inventory_audit(id uuid,old_status text,new_status text);
          create function tcg.fixture_audit() returns trigger language plpgsql as $$begin
            insert into tcg.test_inventory_audit values(new.id,old.status,new.status);return new;end$$;
          create trigger inventory_audit after update on tcg.inventory_items for each row execute function tcg.fixture_audit();
          grant usage on schema tcg to tcg_api;grant select on all tables in schema tcg to tcg_api;
          grant insert on tcg.inventory_items,tcg.request_receipts,tcg.order_items,tcg.test_inventory_audit to tcg_api;
          grant update(store_price_minor,status,sale_intent,version,updated_at,identity_confirmed) on tcg.inventory_items to tcg_api;
          grant update(state) on tcg.listing_inventory_members to tcg_api;
          alter table tcg.inventory_items enable row level security;alter table tcg.inventory_items force row level security;
          create policy inventory_owner on tcg.inventory_items to tcg_api
            using(owner_id in(select owner_id from tcg.owner_memberships where user_id=tcg.current_user_id() and active))
            with check(owner_id in(select owner_id from tcg.owner_memberships where user_id=tcg.current_user_id() and active));
          alter table tcg.request_receipts enable row level security;alter table tcg.request_receipts force row level security;
          create policy receipt_owner on tcg.request_receipts to tcg_api
            using(owner_id in(select owner_id from tcg.owner_memberships where user_id=tcg.current_user_id() and active))
            with check(owner_id in(select owner_id from tcg.owner_memberships where user_id=tcg.current_user_id() and active));
        ''')
        owner,foreign,actor,foreign_actor,product,item,other= (uuid4() for _ in range(7))
        await db.executemany("insert into tcg.owners(id,display_name,owner_type,commission_bps) values($1,$2,'FOUNDER',1000)",[(owner,'Seller A'),(foreign,'Seller B')])
        await db.executemany("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",[(actor,owner),(foreign_actor,foreign)])
        await db.execute("""insert into tcg.catalogue_products values($1,'sealed:v1:one_piece_card_game:op17:booster_pack:jp','SEALED','One Piece',
          'Booster Pack: World''s Strongest Warriors [OP-17]','World''s Strongest Warriors [OP-17]',null,'','','Japanese')""",product)
        await db.execute("insert into tcg.catalogue_product_profiles(catalogue_id,system_code,identity_status) values($1,'ONE_PIECE_CARD_GAME','VERIFIED')",product)
        await db.executemany("""insert into tcg.inventory_items(id,owner_id,catalogue_id,inventory_code,status,sale_intent,language,seal_status,market_value_minor)
          values($1,$2,$3,$4,'DRAFT','PERSONAL_COLLECTION','Japanese','SEALED',866)""",[(item,owner,product,'INV-A'),(other,foreign,product,'INV-B')])
        migration=(Path(__file__).parents[1]/'database/migrations/20261010150000_inventory_op17_reference_artwork.sql').read_text()
        before=await db.fetch("select * from tcg.inventory_items order by id")
        await db.execute(migration);version=await db.fetchval('select version from tcg.catalogue_product_profiles')
        await db.execute(migration)
        assert await db.fetchval('select version from tcg.catalogue_product_profiles')==version,'Artwork replay changed profile version'
        assert await db.fetch('select * from tcg.inventory_items order by id')==before,'Artwork migration changed inventory'
        assert await db.fetchval('select count(*) from tcg.media_assets')==0,'Reference artwork became approved media'

        seller_migration=(Path(__file__).parents[1]/'database/migrations/20261010143413_seller_held_sealed_publication.sql').read_text()
        await db.execute(seller_migration);await db.execute(seller_migration)

        async def init(connection):
            await _init_connection(connection);await connection.execute('set role tcg_api')
        pool=await asyncpg.create_pool(dsn,min_size=1,max_size=4,init=init)
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)),state=SimpleNamespace(request_id='fixture'))
        user=SimpleNamespace(user_id=actor);access={'owner_id':owner}
        with patch.object(api,'get_settings',return_value=SimpleNamespace(shopify_seller_sync_enabled=True,shopify_publish_enabled=True)), \
             patch.object(api,'request_shopify_sync',return_value=True), \
             patch.object(intent,'request_shopify_sync',return_value=True), \
             patch.object(intent,'withdraw_shopify_for_inventory',AsyncMock(return_value=[])), \
             patch.object(intent,'withdraw_ebay_for_inventory',AsyncMock(return_value=None)):
            detail=await api.details(item,request,user,access)
            assert len(detail['copies'])==1 and detail['copies'][0]['inventory_code']=='INV-A'
            assert detail['item']['reference_image_url'].endswith('/product_pack.webp')
            assert 'Drop Rate intake review' in detail['item']['approval_blockers']
            assert 'acquisition_cost_minor' not in detail['item'] and 'intake_ready' not in detail['item']
            for read in (api.details,api.reference_image):
                try: await read(other,request,user,access);raise AssertionError('Read foreign inventory')
                except HTTPException as e:assert e.status_code==404
            for operation,payload in ((api.selling_price,api.SellingPrice(version=1,store_price_minor=1000)),
                                      (api.approval_request,api.SellingPrice(version=1,store_price_minor=1000)),
                                      (api.withdraw_copy,api.VersionRequest(version=1))):
                try:await operation(other,payload,request,user,access);raise AssertionError('Mutated foreign inventory')
                except HTTPException as e:assert e.status_code==404

            key=uuid4();payload=api.AddCopy(version=1,confirmed=True)
            a,b=await asyncio.gather(api.add_copy(item,payload,request,user,access,key),api.add_copy(item,payload,request,user,access,key))
            assert a['item']['id']==b['item']['id'] and a['replayed']!=b['replayed'],'Concurrent retry duplicated stock'
            assert await db.fetchval('select count(*) from tcg.inventory_items where owner_id=$1',owner)==2
            added=await db.fetchrow('select * from tcg.inventory_items where id=$1',__import__('uuid').UUID(a['item']['id']))
            assert added['status']=='DRAFT' and not added['identity_confirmed'] and added['sale_intent']=='PERSONAL_COLLECTION'
            assert added['store_price_minor'] is None and added['acquisition_cost_minor'] is None and added['latest_pricing_snapshot_id'] is None
            approval=await api.approval_request(item,api.SellingPrice(version=1,store_price_minor=1234),request,user,access)
            assert approval['item']['status']=='INSPECTION' and approval['item']['sale_intent']=='FOR_SALE'
            assert await db.fetchval('select market_value_minor from tcg.inventory_items where id=$1',item)==866
            try:await api.selling_price(item,api.SellingPrice(version=1,store_price_minor=9999),request,user,access);raise AssertionError('Stale write accepted')
            except HTTPException as e:assert e.status_code==409
            assert (await api.add_copy(item,payload,request,user,access,key))['replayed'],'Committed retry failed after parent changed'
            for state in ('SOLD','RESERVED','WITHDRAWN'):
                await db.execute('update tcg.inventory_items set status=$2 where id=$1',item,state)
                try:await api.selling_price(item,api.SellingPrice(version=2,store_price_minor=9999),request,user,access);raise AssertionError('Locked stock changed')
                except HTTPException as e:assert e.status_code==409
            await db.execute("update tcg.inventory_items set status='INSPECTION' where id=$1",item)
            await api.withdraw_copy(item,api.VersionRequest(version=2),request,user,access)
            assert await db.fetchval('select status from tcg.inventory_items where id=$1',item)=='WITHDRAWN'
            assert await db.fetchval('select count(*) from tcg.test_inventory_audit where id=$1 and new_status=$2',item,'WITHDRAWN')>=1
            assert (await api.withdraw_copy(item,api.VersionRequest(version=2),request,user,access))['replayed']
            assert (await api.details(item,request,user,access))['copies'][0]['id']==a['item']['id']
            assert await db.fetchrow('select * from tcg.inventory_items where id=$1',other)==next(row for row in before if row['id']==other)
            # Reference identity changes cannot retain the old pack image.
            await db.execute("update tcg.catalogue_products set language='English' where id=$1",product)
            assert 'reference_image_url' not in (await api.details(item,request,user,access))['item']
            # A seller confirms a verified sealed SKU and reuses approved canonical art.
            await db.execute("update tcg.catalogue_products set language='Japanese' where id=$1",product)
            await db.execute("update tcg.owners set owner_type='CONSIGNOR' where id=$1",owner)
            await db.execute("update tcg.inventory_items set status='DRAFT',version=10 where id=$1",item)
            await db.execute("""insert into tcg.media_assets(owner_id,catalogue_id,scope,side,media_kind,media_language,media_variant,approval_status,rights_status,rights_tier,source_status,shopify_file_status,public_source_url)
              values($1,$2,'CANONICAL_PRODUCT','FRONT','IMAGE','Japanese','','APPROVED','VERIFIED','STOREFRONT_ALLOWED','ACTIVE','READY','https://cdn.shopify.com/op17.webp')""",owner,product)
            candidate=await api.details(item,request,user,access)
            assert candidate['item']['seller_approval_available']
            assert 'Drop Rate intake review' not in candidate['item']['approval_blockers']
            done=await api.approval_request(item,api.SellingPrice(version=10,store_price_minor=1000),request,user,access)
            assert done['item']['status']=='APPROVED'
            record=await db.fetchrow('select * from tcg.inventory_items where id=$1',item)
            assert record['acquisition_cost_minor'] is None and record['storage_location_id'] is None
            assert record['source_record']['seller_held_approval']['actor_user_id']==str(actor)
            context=await db.fetchval('select tcg.shopify_publication_context($1,$2)',item,owner)
            assert context['media_assets'][0]['scope']=='CANONICAL_PRODUCT'
            from app.seller_inventory_policy import seller_held_consignment
            assert seller_held_consignment(context['item'])
            await db.execute('insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor) values($1,$2,null)',owner,item)
            from seller_finance_postgres import verify_cost_rollups
            await verify_cost_rollups(db,owner,item)
            try:
                await db.execute('insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor) values($1,$2,null)',foreign,other)
                raise AssertionError('Founder unknown cost accepted')
            except asyncpg.CheckViolationError:pass
            await db.execute("update tcg.catalogue_products set language='English' where id=$1",product)
            # An identity mismatch invalidates approval; NULL cost cannot be smuggled across it.
            await db.execute("update tcg.inventory_items set language='English' where id=$1",item)
            try:
                await db.execute('insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor) values($1,$2,null)',owner,item)
                raise AssertionError('Changed identity retained cost exception')
            except asyncpg.CheckViolationError:pass
        print('Seller inventory PostgreSQL: owner isolation, exact artwork/migration replay, concurrent quantity receipts, price/approval guards and audited withdrawal passed.')
    finally:
        if pool:await pool.close()
        await db.close()


if __name__=='__main__':asyncio.run(main())
