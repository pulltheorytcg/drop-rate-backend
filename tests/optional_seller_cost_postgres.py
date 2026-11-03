"""Disposable PostgreSQL regression for optional cost and active Collection reads.

Runs actual migrations and commission triggers against synthetic, in-memory
PGlite data. No network, provider, production credentials or production writes.
Run after npm ci --prefix tools/history-archive-verify:
    PYTHONPATH=backend python tests/optional_seller_cost_postgres.py
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from uuid import UUID, uuid4
from unittest.mock import patch

from app.finance import _settlement_amounts
from app.inventory_collection_filters import ACTIVE_COLLECTION_SQL, collection_facets, collection_state_counts
from app.inventory_display_groups import inventory_group_page
from app.inventory_value_sort import inventory_value_page
from catalogue_r2_cache_postgres import PGliteConnection, PGliteError

ROOT = Path(__file__).resolve().parents[1]
SELLER = UUID('10000000-0000-0000-0000-000000000001')
FOUNDER = UUID('10000000-0000-0000-0000-000000000002')
OTHER = UUID('10000000-0000-0000-0000-000000000003')
LOCATION = UUID('20000000-0000-0000-0000-000000000001')
SCHEMA = """
create schema tcg;
create role tcg_api nologin nosuperuser nobypassrls;
create role anon nologin;
create role authenticated nologin;
create table tcg.owners(id uuid primary key,owner_type text,active bool default true);
create table tcg.catalogue_products(id uuid primary key,product_type text,game text,name text,
 set_name text,variant text,language text,card_number text,rarity text);
create table tcg.catalogue_product_profiles(catalogue_id uuid,system_code text);
create table tcg.collectible_systems(code text,system_kind text);
create table tcg.sealed_product_details(catalogue_id uuid,attributes jsonb);
create table tcg.inventory_items(id uuid primary key,owner_id uuid,catalogue_id uuid,
 inventory_code text,version int default 1,status text default 'APPROVED',
 sale_intent text default 'FOR_SALE',identity_confirmed bool default true,
 acquisition_cost_minor bigint check(acquisition_cost_minor>=0),storage_location_id uuid,
 language text default 'English',condition text default 'Near Mint',seal_status text,
 grading_company text,grade text,certificate_number text,condition_review_status text default 'VERIFIED_NEAR_MINT',
 store_price_minor bigint default 2000,market_value_minor bigint default 1000,
 recommended_retail_minor bigint default 2000,latest_pricing_snapshot_id uuid,
 source_record jsonb default '{}',created_at timestamptz default now(),updated_at timestamptz default now());
create table tcg.pricing_snapshots(id uuid,owner_id uuid,inventory_id uuid,evidence jsonb);
create table tcg.order_items(id uuid primary key default gen_random_uuid(),owner_id uuid,
 inventory_id uuid,cost_basis_minor bigint not null check(cost_basis_minor>=0),
 sale_price_minor bigint not null,discount_minor bigint not null default 0,
 net_sale_minor bigint generated always as(sale_price_minor-discount_minor) stored);
create table tcg.inventory_reservations(id uuid primary key default gen_random_uuid(),
 inventory_id uuid,acquisition_cost_minor_snapshot bigint not null check(acquisition_cost_minor_snapshot>=0));
create table tcg.financial_ledger_entries(id uuid primary key default gen_random_uuid(),
 owner_id uuid,order_id uuid,order_item_id uuid,entry_type text,amount_minor bigint,currency text,
 funds_status text,source_key text unique,occurred_at timestamptz,available_at timestamptz,notes text);
create table tcg.audit_events(actor text,request_id text,action text,entity_type text,entity_id uuid,old_values jsonb,new_values jsonb);
create table tcg.shopify_inventory_links(inventory_id uuid,owner_id uuid,test_mode bool,sync_state text);
create table tcg.ebay_inventory_links(id uuid primary key,inventory_id uuid,owner_id uuid,state text,
 withdrawal_reason text,listed_price_minor bigint,markup_bps int);
create table tcg.shopify_shipping_profiles(owner_id uuid,active bool,profile_key text);
create table tcg.media_assets(owner_id uuid,inventory_id uuid,scope text,media_kind text,side text,
 rights_status text,approval_status text,source_status text,revoked_at timestamptz,
 shopify_file_status text,shopify_cdn_url text);
"""


async def expect_constraint(db, sql, *params):
    try:
        await db.execute(sql, *params)
    except PGliteError as error:
        assert str(error).startswith('23514:'), str(error)
    else:
        raise AssertionError('Expected physical-sale or nonnegative-cost constraint')


async def item(db, owner, product_type='CARD', game='Pokemon', status='APPROVED', *, catalogue=None, **changes):
    catalogue = catalogue or uuid4()
    await db.execute("""insert into tcg.catalogue_products(id,product_type,game,name,set_name,variant,language)
      values($1,$2,$3,'Synthetic exact copy','Synthetic set','Normal','English') on conflict(id) do nothing""",
      catalogue,product_type,game)
    identifier = uuid4()
    await db.execute("""insert into tcg.inventory_items(id,owner_id,catalogue_id,inventory_code,status,storage_location_id)
      values($1,$2,$3,$4,$5,$6)""",identifier,owner,catalogue,'INV-'+identifier.hex,status,LOCATION)
    for column, value in changes.items():
        assert column in {'identity_confirmed','sale_intent','storage_location_id','market_value_minor','language','seal_status','source_record','condition_review_status'}
        await db.execute(f'update tcg.inventory_items set {column}=$2 where id=$1',identifier,value)
    return identifier


async def sale(db, inventory, owner, cost):
    return await db.fetchrow("""insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor,sale_price_minor,discount_minor)
      values($1,$2,$3,2500,500) returning *""",owner,inventory,cost)


async def verify_cost_and_commission(db):
    await db.execute(SCHEMA)
    await db.execute('insert into tcg.owners values($1,\'CONSIGNOR\',true),($2,\'FOUNDER\',true),($3,\'CONSIGNOR\',true)',SELLER,FOUNDER,OTHER)
    await db.execute((ROOT/'database/migrations/20260926182559_consignor_commission_10pct.sql').read_text())
    # Apply the existing cost trigger unchanged, then the proposed migration.
    old=(ROOT/'database/migrations/20261010143413_seller_held_sealed_publication.sql').read_text()
    await db.execute(old.split('-- Preserve the existing publication function')[0]+'commit;')
    original=await sale(db,await item(db,SELLER),SELLER,800)
    await db.execute((ROOT/'database/migrations/20261103184836_optional_seller_purchase_cost.sql').read_text())
    assert await db.fetchrow('select * from tcg.order_items where id=$1',original['id']) == original
    assert await db.fetchval('select commission_bps from tcg.owners where id=$1',SELLER)==1000
    assert await db.fetchval('select commission_bps from tcg.owners where id=$1',FOUNDER)==0
    checked=0
    for owner in (SELLER,FOUNDER):
        for product_type,game in (('CARD','Pokemon'),('CARD','Sports'),('COMIC','Marvel Comics'),('COMIC','Manga'),('FIGURE','Figures'),('SEALED','Pokemon'),('COLLECTION','Pokemon')):
            for cost in (None,0,800):
                inventory=await item(db,owner,product_type,game)
                row=await sale(db,inventory,owner,cost)
                assert row['cost_basis_minor'] == cost
                commission=200 if owner==SELLER else 0
                assert row['commission_minor']==commission
                assert row['net_sale_minor']==2000
                await db.execute("""insert into tcg.financial_ledger_entries(owner_id,order_item_id,entry_type,
                  amount_minor,currency,funds_status,source_key,occurred_at)
                  values($1,$2,'SALE_REVENUE',2000,'GBP','PENDING',$3,now())""",owner,row['id'],'sale:'+row['id'])
                assert await db.fetchval("select coalesce(-sum(amount_minor),0)::int from tcg.financial_ledger_entries where order_item_id=$1 and entry_type='COMMISSION'",row['id'])==commission
                amounts=_settlement_amounts(item_revenue_minor=2000,shipping_revenue_minor=0,item_refunds_minor=0,
                    shipping_refunds_minor=0,platform_fees_minor=0,payment_fees_minor=100,shipping_cost_minor=0,
                    fulfilment_material_cost_minor=0,commission_minor=commission,adjustments_minor=0,effective_cogs_minor=cost)
                assert amounts['net_owner_proceeds_minor']==1900-commission
                assert amounts['owner_profit_minor']==(None if cost is None else 1900-commission-cost)
                reserved=await db.fetchrow('insert into tcg.inventory_reservations(inventory_id,acquisition_cost_minor_snapshot) values($1,$2) returning *',inventory,cost)
                assert reserved['acquisition_cost_minor_snapshot']==cost
                checked+=1
    safe=await item(db,SELLER)
    await expect_constraint(db,'insert into tcg.inventory_reservations(inventory_id,acquisition_cost_minor_snapshot) values($1,-1)',safe)
    await expect_constraint(db,'insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor,sale_price_minor) values($1,$2,-1,2000)',SELLER,safe)
    for change in ({'identity_confirmed':False},{'sale_intent':'PERSONAL_COLLECTION'},{'storage_location_id':None}):
        unsafe=await item(db,SELLER,**change)
        await expect_constraint(db,'insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor,sale_price_minor) values($1,$2,null,2000)',SELLER,unsafe)
    for status in ('DRAFT','INSPECTION','WITHDRAWN'):
        unsafe=await item(db,SELLER,status=status)
        await expect_constraint(db,'insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor,sale_price_minor) values($1,$2,null,2000)',SELLER,unsafe)
    await expect_constraint(db,'insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor,sale_price_minor) values($1,$2,null,2000)',OTHER,safe)
    await db.execute('update tcg.owners set active=false where id=$1',OTHER)
    unsafe=await item(db,OTHER)
    await expect_constraint(db,'insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor,sale_price_minor) values($1,$2,null,2000)',OTHER,unsafe)
    # The exact seller-held sealed exception still works without invented storage.
    sealed=await item(db,SELLER,'SEALED',seal_status='SEALED',storage_location_id=None)
    await db.execute("""update tcg.inventory_items i set source_record=jsonb_build_object('seller_held_approval',
      jsonb_build_object('owner_id',i.owner_id,'catalogue_id',i.catalogue_id,'language',i.language,
      'name',p.name,'set_name',p.set_name,'variant',p.variant,'actor_user_id','synthetic-actor'))
      from tcg.catalogue_products p where i.id=$1 and p.id=i.catalogue_id""",sealed)
    assert (await sale(db,sealed,SELLER,None))['cost_basis_minor'] is None
    await db.execute("update tcg.inventory_items set source_record='{}' where id=$1",sealed)
    await expect_constraint(db,'insert into tcg.order_items(owner_id,inventory_id,cost_basis_minor,sale_price_minor) values($1,$2,null,2000)',SELLER,sealed)
    # Restore after a cross-channel reservation keeps photo, location and price checks.
    ebay=uuid4()
    await db.execute("insert into tcg.ebay_inventory_links values($1,$2,$3,'WITHDRAWN','SHOPIFY_RESERVED',2000,0)",ebay,safe,SELLER)
    await db.execute("insert into tcg.shopify_shipping_profiles values($1,true,'RAW_CARD')",SELLER)
    await db.execute("""insert into tcg.media_assets(owner_id,inventory_id,scope,media_kind,side,rights_status,
      approval_status,source_status,shopify_file_status,shopify_cdn_url)
      select $1,$2,'INVENTORY_ITEM','IMAGE',side,'VERIFIED','APPROVED','ACTIVE','READY','https://fixture.invalid/photo'
      from unnest(array['FRONT','BACK']) side""",SELLER,safe)
    assert await db.fetchval('select tcg.ebay_restore_ready($1)',ebay) is True
    await db.execute("update tcg.media_assets set approval_status='PENDING' where inventory_id=$1 and side='BACK'",safe)
    assert await db.fetchval('select tcg.ebay_restore_ready($1)',ebay) is False
    print(f'PASS: {checked} cost/type/owner sales + nullable reservations, revenue commission, preserved history and physical-sale guards')


async def verify_collection(db):
    # A separate owner makes the read set explicit without erasing sale fixtures.
    owner=uuid4();await db.execute("insert into tcg.owners(id,owner_type) values($1,'CONSIGNOR')",owner)
    product=uuid4()
    a=await item(db,owner,catalogue=product,status='APPROVED')
    b=await item(db,owner,catalogue=product,status='DRAFT')
    review=await item(db,owner,'COMIC','Manga',status='INSPECTION')
    reserved=await item(db,owner,'FIGURE','Figures',status='RESERVED')
    removed=await item(db,owner,'COMIC','Removed-only game',status='WITHDRAWN',market_value_minor=900000,language='Removed-only language')
    sold=await item(db,owner,status='SOLD',market_value_minor=800000)
    await item(db,OTHER,game='Private other owner')
    # A stale published link on removed stock must not inflate actionable counts.
    for ident in (a,removed):
        await db.execute("insert into tcg.shopify_inventory_links values($1,$2,false,'PUBLISHED')",ident,owner)
    where='i.owner_id=$1 and '+ACTIVE_COLLECTION_SQL
    first=await inventory_group_page(db,where,[owner],1,0,sort='name')
    assert first[:2]==(3,4)
    all_ids=[]
    for offset in range(3):
        total,copies,ids=await inventory_group_page(db,where,[owner],1,offset,sort='name')
        assert (total,copies)==(3,4);all_ids.extend(ids)
    assert set(all_ids)==set(map(str,(a,b,review,reserved)))
    assert (await inventory_group_page(db,where,[owner],1,3))[2]==[]
    facets=await collection_facets(db,owner)
    assert facets['games']==['Figures','Manga','Pokemon']
    assert facets['languages']==['English']
    states=await collection_state_counts(db,owner)
    assert states==dict(personal=0,for_sale=4,preparing=1,review=1,ready=0,listed=1)
    source=ast.parse((ROOT/'backend/app/owner_portal_api.py').read_text())
    overview=next(node for node in source.body if isinstance(node,ast.AsyncFunctionDef) and node.name=='owner_overview')
    summary_sql=next(node.value for node in ast.walk(overview) if isinstance(node,ast.Constant)
                     and isinstance(node.value,str) and 'as total_inventory_count' in node.value)
    summary=await db.fetchrow(summary_sql,owner)
    assert summary['total_inventory_count']==4 and summary['active_market_value_minor']==4000
    assert summary['sold_count']==summary['withdrawn_count']==1
    enriched=[]
    async def evidence(connection,rows):
        enriched.extend(row['id'] for row in rows)
        for row in rows:
            row['reference_value']={'status':'AVAILABLE','market_value_minor':1000}
        return rows
    with patch('app.inventory_value_sort.add_shared_reference_values',evidence):
        value=await inventory_value_page(db,where,[owner],1,0,grouped=True,descending=True)
    assert value.total==3 and value.copy_total==4
    assert set(enriched)==set(map(str,(a,b,review,reserved)))
    # Remove the remaining exact pair through the same audit-preserving status.
    await db.execute("update tcg.inventory_items set status='WITHDRAWN',sale_intent='PERSONAL_COLLECTION' where id=any($1::uuid[])",[a,b])
    assert (await inventory_group_page(db,where,[owner],50,0))[:2]==(2,2)
    assert (await db.fetchrow(summary_sql,owner))['active_market_value_minor']==2000
    assert (await collection_state_counts(db,owner))['listed']==0
    assert await db.fetchval('select count(*)::int from tcg.inventory_items where owner_id=$1',owner)==6
    assert await db.fetchval('select status from tcg.inventory_items where id=$1',removed)=='WITHDRAWN'
    assert await db.fetchval('select status from tcg.inventory_items where id=$1',sold)=='SOLD'
    print('PASS: active Collection SQL counts, facets, grouping, pagination, values and state totals exclude removed/sold/foreign copies; history retained')


async def main():
    db=await PGliteConnection.open()
    try:
        await verify_cost_and_commission(db)
        await verify_collection(db)
    finally:
        await db.close()


if __name__=='__main__':
    asyncio.run(main())
