"""Exercise actual Shopify link functions as tcg_api in the seller fixture."""
from pathlib import Path
import re
from uuid import uuid4

import asyncpg


ROOT = Path(__file__).parents[1]


def function_definition(sql, name):
    match = re.search(r"create or replace function tcg\." + name
                      + r"\([\s\S]*?\$function\$;", sql, re.I)
    assert match, name
    return match.group(0)


async def verify_publication_actor(db, pool, owner, item, foreign, seller):
    await db.execute("""
      create table tcg.founder_app_accounts(user_id uuid,owner_id uuid,founder_slot int,active bool);
      create table tcg.automation_events(id uuid,owner_id uuid,event_type text,schema_version int,
        status text,aggregate_type text,aggregate_id text,idempotency_key text,payload jsonb);
      create table tcg.audit_events(actor text,request_id text,action text,entity_type text,
        entity_id uuid,old_values jsonb,new_values jsonb);
      alter table tcg.shopify_inventory_links
        add column id uuid primary key default gen_random_uuid(),
        add column created_by_user_id uuid,add column created_by_automation_event_id uuid,
        add column listing_key text,add column allocation_priority int,
        add column shop_domain text,add column shopify_product_gid text,
        add column shopify_variant_gid text,add column shopify_inventory_item_gid text,
        add column shopify_location_gid text,add column shopify_publication_gid text,
        add column sku text,add column synced_price_minor bigint,add column version int default 1;
    """)
    actor, founder = uuid4(), uuid4()
    await db.execute("insert into tcg.owners(id,owner_type,founder_slot) values($1,'FOUNDER',1)", founder)
    await db.execute("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'PLATFORM_ADMIN')", actor, founder)
    await db.execute("insert into tcg.founder_app_accounts values($1,$2,1,true)", actor, founder)
    await db.execute(function_definition((ROOT/'database/migrations/20261002024856_unified_founder_app_access.sql').read_text(), 'is_platform_admin'))
    baseline = (ROOT/'database/migrations/20260928183039_shopify_automation_publication.sql').read_text()
    for name in ('save_shopify_inventory_draft', 'mark_shopify_inventory_published'):
        await db.execute(function_definition(baseline, name))
    await db.execute('revoke execute on all functions in schema tcg from public; grant execute on all functions in schema tcg to tcg_api')
    before = await db.fetchrow('select * from tcg.inventory_items where id=$1', item)
    version = before['version']
    draft = 'select tcg.save_shopify_inventory_draft(' + ','.join('$'+str(i) for i in range(1,17)) + ')'
    args = [item, owner, version, actor, None, 'publication-fixture', 'inventory:'+str(item),
            'fixture.myshopify.com', 'gid://shopify/Product/1', 'gid://shopify/ProductVariant/1',
            'gid://shopify/InventoryItem/1', 'gid://shopify/Location/1', 'gid://shopify/Publication/1',
            before['inventory_code'], before['store_price_minor'], False]
    published = 'select tcg.mark_shopify_inventory_published(' + ','.join('$'+str(i) for i in range(1,12)) + ')'
    final_args = args[:6] + args[8:11] + args[14:]

    async with pool.acquire() as connection:
        async def session(user):
            await connection.execute("select set_config('tcg.user_id',$1,false)", str(user))

        async def denied(query, values, exception=asyncpg.InsufficientPrivilegeError):
            try:
                await connection.fetchval(query, *values)
            except exception:
                return
            raise AssertionError('Unauthorized or inconsistent publication accepted')

        await session(actor)
        assert await connection.fetchval('select tcg.is_platform_admin()')
        # Reproduce the live failure without adding the founder to the seller.
        await denied(draft, args)
        migration = (ROOT/'database/migrations/20261010153600_shopify_publication_actor.sql').read_text()
        await db.execute(migration)
        await db.execute(migration)
        await session(seller)
        await denied(draft, args)  # A seller cannot claim the founder actor.
        await denied(draft, args[:3]+[seller]+args[4:])
        await session(actor)
        await denied(draft, args[:3]+[uuid4()]+args[4:])
        await denied(draft, [item, foreign]+args[2:], asyncpg.ForeignKeyViolationError)
        await denied(draft, args[:2]+[version+1]+args[3:], asyncpg.ObjectNotInPrerequisiteStateError)
        await db.execute('update tcg.founder_app_accounts set active=false where user_id=$1', actor)
        await denied(draft, args)
        await db.execute('update tcg.founder_app_accounts set active=true where user_id=$1', actor)
        first = await connection.fetchval(draft, *args)
        repeated = await connection.fetchval(draft, *args)
        assert first['id'] == repeated['id'] and first['owner_id'] == str(owner)
        assert first['created_by_user_id'] == str(actor)
        await session(seller)
        await denied(published, final_args)
        await session(actor)
        await denied(published, final_args[:6]+['gid://shopify/Product/wrong']+final_args[7:], asyncpg.ObjectNotInPrerequisiteStateError)
        await db.execute("update tcg.inventory_items set sale_intent='PERSONAL_COLLECTION' where id=$1", item)
        await denied(published, final_args, asyncpg.ObjectNotInPrerequisiteStateError)
        await db.execute("update tcg.inventory_items set sale_intent='FOR_SALE' where id=$1", item)
        final = await connection.fetchval(published, *final_args)
        replay = await connection.fetchval(published, *final_args)
        assert final == replay and final['sync_state'] == 'PUBLISHED'
        assert final['inventory_id'] == str(item) and final['owner_id'] == str(owner)
        assert final['synced_price_minor'] == 1000
        # The separate event-authorized route still rejects an invalid event.
        await denied(draft, args[:3]+[None,uuid4()]+args[5:], asyncpg.CheckViolationError)
        await connection.execute("select set_config('tcg.user_id','',false)")
    assert await db.fetchrow('select * from tcg.inventory_items where id=$1', item) == before
    assert await db.fetchval('select count(*) from tcg.owner_memberships where user_id=$1', actor) == 1
    assert await db.fetchval("select count(*) from tcg.audit_events where action='SHOPIFY_LINK_PUBLISHED' and actor=$1", str(actor)) == 1
    assert await db.fetchval("select count(*) from tcg.audit_events where action='SHOPIFY_LINK_DRAFTED'") == 1
    print('Seller publication PostgreSQL: real founder authority, actor spoofing, owner/version/intent guards, idempotent links and audits passed.')
