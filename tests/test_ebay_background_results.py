from pathlib import Path
from uuid import UUID
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import ebay_sales

from test_book_connector_import import run_sql

MIGRATION = Path(__file__).parents[1] / 'database/migrations/20261030233511_ebay_background_channel_results.sql'


def test_background_results_run_under_rls_and_preserve_other_sellers_stock(tmp_path):
    own, other, card, sibling, link, shop, shop_sibling = [str(UUID(int=n)) for n in range(1, 8)]
    setup = f"""
    create role tcg_api; create role anon; create role authenticated;
    grant usage on schema tcg to tcg_api;
    create table tcg.owners(id uuid,active boolean);
    create table tcg.inventory_items(id uuid,owner_id uuid,status text,sale_intent text,
      identity_confirmed boolean,language text,storage_location_id uuid,acquisition_cost_minor bigint,
      store_price_minor bigint,grading_company text,grade text,condition text,condition_review_status text);
    create table tcg.ebay_inventory_links(id uuid,inventory_id uuid,owner_id uuid,version integer,
      state text,withdrawal_reason text,listed_price_minor bigint,markup_bps integer,
      offer_id text,listing_id text,withdrawn_at timestamptz,last_verified_at timestamptz,
      last_error_code text,updated_at timestamptz);
    create table tcg.shopify_inventory_links(id uuid,inventory_id uuid,owner_id uuid,
      shop_domain text,shopify_product_gid text,shopify_variant_gid text,shopify_location_gid text,
      test_mode boolean,sync_state text,reserved_order_reference text,reserved_line_reference text);
    create table tcg.shopify_shipping_profiles(owner_id uuid,active boolean,profile_key text);
    create table tcg.media_assets(owner_id uuid,inventory_id uuid,scope text,media_kind text,
      side text,rights_status text,approval_status text,source_status text,revoked_at timestamptz,
      shopify_file_status text,shopify_cdn_url text);
    alter table tcg.inventory_items enable row level security;
    alter table tcg.ebay_inventory_links enable row level security;
    grant select,update on tcg.inventory_items,tcg.ebay_inventory_links to tcg_api;
    insert into tcg.owners values('{own}',true),('{other}',true);
    insert into tcg.inventory_items values
      ('{card}','{own}','APPROVED','FOR_SALE',true,'English','{own}',100,1000,null,null,'Near Mint','VERIFIED_NEAR_MINT'),
      ('{sibling}','{other}','APPROVED','FOR_SALE',true,'English','{own}',100,1000,null,null,'Near Mint','VERIFIED_NEAR_MINT');
    insert into tcg.ebay_inventory_links(id,inventory_id,owner_id,version,state,listed_price_minor,markup_bps,offer_id)
      values('{link}','{card}','{own}',1,'LIVE',1000,0,'offer');
    insert into tcg.shopify_inventory_links values
      ('{shop}','{card}','{own}','shop','product','variant','location',false,'PUBLISHED',null,null),
      ('{shop_sibling}','{sibling}','{other}','shop','product','variant','location',false,'PUBLISHED',null,null);
    insert into tcg.shopify_shipping_profiles values('{own}',true,'RAW_CARD');
    insert into tcg.media_assets values
      ('{own}','{card}','INVENTORY_ITEM','IMAGE','FRONT','VERIFIED','APPROVED','ACTIVE',null,'READY','front'),
      ('{own}','{card}','INVENTORY_ITEM','IMAGE','BACK','VERIFIED','APPROVED','ACTIVE',null,'READY','back');
    """ + MIGRATION.read_text()
    def worker(sql):
        return 'set role tcg_api; ' + sql + '; reset role;'
    def record(version, state, reason='null', listing='null', error='null'):
        return worker(f"select tcg.record_ebay_channel_result('{link}',{version},'{state}',null,{listing},{reason},{error}) as ok")
    def change(sql):
        return 'reset role; ' + sql + ';'
    ready = worker(f"select tcg.ebay_restore_ready('{link}') as ok")
    stock = worker(f"select tcg.shopify_stock_after_ebay_sale('{shop}') as target")
    steps = [
        worker('select count(*)::integer as visible from tcg.inventory_items'),
        record(1, 'WITHDRAWN', "'PERSONAL_COLLECTION'"),
        change(f"update tcg.inventory_items set sale_intent='PERSONAL_COLLECTION' where id='{card}'") + record(1, 'WITHDRAWN', "'PERSONAL_COLLECTION'"),
        record(1, 'ERROR', error="'stale'"), ready,
        change(f"update tcg.inventory_items set sale_intent='FOR_SALE',status='RESERVED' where id='{card}'; update tcg.ebay_inventory_links set state='LIVE',version=3 where id='{link}'") + record(3,'WITHDRAWN',"'SHOPIFY_RESERVED'"),
        change(f"update tcg.inventory_items set status='APPROVED' where id='{card}'") + ready,
        change("update tcg.media_assets set revoked_at=now() where side='BACK'") + ready,
        record(4,'LIVE',listing="'listing'"),
        change(f"update tcg.media_assets set revoked_at=null; update tcg.inventory_items set store_price_minor=1500 where id='{card}'") + ready,
        change(f"update tcg.inventory_items set store_price_minor=1000 where id='{card}'") + record(4,'LIVE',listing="'listing'"),
        record(4,'ERROR',error="'stale'"),
        record(5,'UNSUPPORTED'),
        change(f"update tcg.inventory_items set status='SOLD' where id='{card}'; update tcg.ebay_inventory_links set state='SOLD',version=6 where id='{link}'") + stock,
        record(6,'ERROR',error="'late'"),
        change(f"update tcg.inventory_items set status='RESERVED' where id='{sibling}'") + stock,
        change(f"update tcg.inventory_items set status='APPROVED' where id='{sibling}'; update tcg.shopify_inventory_links set shopify_variant_gid='different' where id='{shop_sibling}'") + stock,
        worker(f"select tcg.shopify_stock_after_ebay_sale('{shop_sibling}')"),
        change(f"update tcg.inventory_items set status='APPROVED',sale_intent='PERSONAL_COLLECTION' where id='{card}'; update tcg.ebay_inventory_links set state='LIVE',version=10 where id='{link}'") + record(10,'WITHDRAWN'),
    ]
    result = run_sql(tmp_path, steps, setup=setup, inspect='select 1')
    rows = result['results']
    assert rows[0]['rows'] == [{'visible': 0}], result
    for n in (1,3,4,7,8,9,11,14,18):
        assert rows[n]['ok'] and rows[n]['rows'][-1]['ok'] is False, (n,result)
    for n in (2,5,6,10):
        assert rows[n]['ok'] and rows[n]['rows'][-1]['ok'] is True, (n,result)
    assert not rows[12]['ok'] and not rows[17]['ok'], result
    for n, target in [(13,{'quantity':1,'status':'ACTIVE'}),
                      (15,{'quantity':0,'status':'DRAFT'}), (16,{'quantity':0,'status':'ACTIVE'})]:
        assert rows[n]['ok'] and rows[n]['rows'][-1]['target'] == target, (n,result)


@pytest.mark.asyncio
async def test_verified_remote_withdrawal_is_recorded_with_expected_link_version(monkeypatch):
    link = dict(id=UUID(int=5), inventory_id=UUID(int=3), owner_id=UUID(int=1),
                state='LIVE', version=7, offer_id='offer', sku='sku')
    monkeypatch.setattr(ebay_sales, '_links_for_inventory', AsyncMock(return_value=[link]))
    monkeypatch.setattr(ebay_sales, 'get_settings', lambda: SimpleNamespace(ebay_marketplace_id='EBAY_GB'))
    client = SimpleNamespace(get_offer=AsyncMock(side_effect=[{'status':'PUBLISHED','listing':{'listingId':'listing'}}, {'status':'UNPUBLISHED'}]),
                             withdraw_offer=AsyncMock())
    monkeypatch.setattr(ebay_sales, 'seller_client', AsyncMock(return_value=(client, None)))
    conn = SimpleNamespace(fetchval=AsyncMock(return_value=True))
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield conn
    await ebay_sales.withdraw_ebay_for_inventory(Pool(), [str(link['inventory_id'])], reason='PERSONAL_COLLECTION')
    client.withdraw_offer.assert_awaited_once_with('offer')
    assert conn.fetchval.call_args.args[1:] == (link['id'], 7, 'offer', 'PERSONAL_COLLECTION')


@pytest.mark.asyncio
async def test_ebay_sale_keeps_other_shopify_copies_available(monkeypatch):
    row = dict(id=UUID(int=6), inventory_id=UUID(int=3), shopify_product_gid='product',
               shopify_variant_gid='variant', shopify_inventory_item_gid='inventory', shopify_location_gid='location')
    conn = SimpleNamespace(fetch=AsyncMock(return_value=[row]),
                           fetchval=AsyncMock(return_value={'quantity':1,'status':'ACTIVE'}))
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield conn
    client = SimpleNamespace(set_inventory_quantity=AsyncMock(), set_product_status=AsyncMock(),
        get_product_snapshot=AsyncMock(return_value={'status':'ACTIVE','variants':{'nodes':[
            {'id':'other','inventoryQuantity':4},{'id':'variant','inventoryQuantity':1}]}}))
    monkeypatch.setattr(ebay_sales, 'get_settings', lambda: object())
    monkeypatch.setattr(ebay_sales, '_shopify_client', lambda _: client)
    await ebay_sales._zero_shopify_for_ebay_sale(Pool(), [str(row['inventory_id'])])
    assert client.set_inventory_quantity.call_args.kwargs['quantity'] == 1
    assert client.set_product_status.call_args.kwargs['status'] == 'ACTIVE'
