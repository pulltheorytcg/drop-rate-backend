from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app import shopify_pipeline as shopify
from test_book_connector_import import run_sql

MIGRATION = Path(__file__).parents[1] / 'database/migrations/20261030232801_shopify_personal_withdrawal_quantity.sql'


def test_withdrawal_aggregate_preserves_other_sellers_without_exposing_their_stock(tmp_path):
    owner, other, actor, outsider = [str(UUID(int=n)) for n in range(1, 5)]
    item, sibling, link = [str(UUID(int=n)) for n in range(10, 13)]
    setup = f"""
    create role tcg_api;
    grant usage on schema tcg to tcg_api;
    create table tcg.owners(id uuid,active boolean);
    create table tcg.owner_memberships(owner_id uuid,user_id uuid,active boolean);
    create table tcg.inventory_items(id uuid,owner_id uuid,status text,sale_intent text);
    create table tcg.shopify_inventory_links(id uuid,inventory_id uuid,owner_id uuid,
      shop_domain text,shopify_product_gid text,shopify_variant_gid text,shopify_location_gid text,
      test_mode boolean,sync_state text,reserved_order_reference text,reserved_line_reference text);
    create function tcg.current_user_id() returns uuid language sql as
      $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
    insert into tcg.owners values('{owner}',true),('{other}',true);
    insert into tcg.owner_memberships values('{owner}','{actor}',true);
    insert into tcg.inventory_items values
      ('{item}','{owner}','APPROVED','PERSONAL_COLLECTION'),
      ('{sibling}','{other}','APPROVED','FOR_SALE');
    insert into tcg.shopify_inventory_links values
      ('{link}','{item}','{owner}','shop','product','variant','location',false,'ERROR',null,null),
      ('{UUID(int=13)}','{sibling}','{other}','shop','product','variant','location',false,'PUBLISHED',null,null);
    alter table tcg.inventory_items enable row level security;
    create policy own_inventory on tcg.inventory_items for select to tcg_api using(owner_id in
      (select m.owner_id from tcg.owner_memberships m where m.user_id=tcg.current_user_id() and m.active));
    grant select on tcg.inventory_items,tcg.owner_memberships to tcg_api;
    """ + MIGRATION.read_text()
    def call(user, link_owner=owner):
        return f"set role tcg_api; select set_config('tcg.user_id','{user}',false); select tcg.shopify_personal_withdrawal_target('{link}','{link_owner}') as target; reset role;"
    steps = [
        call(actor), call(outsider), call(actor, other), call(''),
        "reset role; update tcg.shopify_inventory_links set reserved_order_reference='reserved' where sync_state='PUBLISHED';" + call(actor),
        "reset role; update tcg.shopify_inventory_links set reserved_order_reference=null,test_mode=true where sync_state='PUBLISHED';" + call(actor),
        "reset role; update tcg.shopify_inventory_links set test_mode=false,shopify_variant_gid='other-variant' where sync_state='PUBLISHED';" + call(actor),
        f"reset role; update tcg.inventory_items set sale_intent='FOR_SALE' where id='{item}';" + call(actor),
    ]
    result = run_sql(tmp_path, steps, setup=setup, inspect='select 1')
    rows = result['results']
    assert rows[0]['ok'] and rows[0]['rows'][-1]['target'] == {'quantity': 1, 'status': 'ACTIVE'}, result
    assert all(not rows[n]['ok'] for n in (1, 2, 3, 7)), result
    for n in (4, 5):
        assert rows[n]['ok'] and rows[n]['rows'][-1]['target'] == {'quantity': 0, 'status': 'DRAFT'}, result
    assert rows[6]['ok'] and rows[6]['rows'][-1]['target'] == {'quantity': 0, 'status': 'ACTIVE'}, result


@pytest.mark.asyncio
@pytest.mark.parametrize('prior_state', ['PUBLISHED', 'ERROR'])
async def test_retry_keeps_sibling_live_and_records_success_in_authenticated_context(monkeypatch, prior_state):
    owner, actor, item, link = [UUID(int=n) for n in range(1, 5)]
    calls = []
    row = dict(id=link, inventory_id=item, owner_id=owner, sync_state=prior_state, version=3,
               shopify_product_gid='product', shopify_variant_gid='variant',
               shopify_inventory_item_gid='inventory', shopify_location_gid='location')
    connection = SimpleNamespace(fetch=AsyncMock(return_value=[row]),
        fetchval=AsyncMock(return_value={'quantity': 1, 'status': 'ACTIVE'}),
        fetchrow=AsyncMock(return_value={**row, 'sync_state': 'ARCHIVED', 'version': 4}))
    @asynccontextmanager
    async def scope(pool, user_id, request_id):
        assert user_id == actor and request_id == 'withdraw-test'
        calls.append('authenticated')
        yield connection
    client = SimpleNamespace(set_inventory_quantity=AsyncMock(), set_product_status=AsyncMock(),
        get_product_snapshot=AsyncMock(return_value={'status': 'ACTIVE', 'variants': {'nodes': [
            {'id': 'other-variant', 'inventoryQuantity': 9}, {'id': 'variant', 'inventoryQuantity': 1}]}}))
    monkeypatch.setattr(shopify, 'user_connection', scope)
    monkeypatch.setattr(shopify, '_client', lambda: client)
    result = await shopify.withdraw_shopify_for_inventory(object(), [str(item)], owner_id=owner,
        actor_user_id=actor, request_id='withdraw-test', reason='PERSONAL_COLLECTION')
    assert len(calls) == 3
    assert result[0]['status'] == 'ARCHIVED'
    assert client.set_inventory_quantity.call_args.kwargs['quantity'] == 1
    assert client.set_product_status.call_args.kwargs['status'] == 'ACTIVE'
    assert connection.fetchrow.call_args.args[1:] == (link, owner)
