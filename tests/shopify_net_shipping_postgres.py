"""Disposable PostgreSQL integration gate for owner-private shipping accounts."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "database/migrations/20261011020000_shopify_net_shipping_accounts.sql"
ADMIN_USER = UUID("00000000-0000-0000-0000-000000000001")
SELLER_A = UUID("00000000-0000-0000-0000-000000000002")
SELLER_B = UUID("00000000-0000-0000-0000-000000000003")


async def rejected(conn, statement, *args):
    try:
        await conn.execute(statement, *args)
    except asyncpg.PostgresError:
        return
    raise AssertionError("Unexpected successful unauthorised/double/immutable mutation")


async def main():
    dsn = os.environ["SHOPIFY_NET_SHIPPING_TEST_DSN"]
    url = urlsplit(dsn)
    assert url.hostname in {"localhost", "127.0.0.1"} and url.path == "/shopify_net_postage_test"
    db = await asyncpg.connect(dsn)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute("""
          create schema tcg;
          create role tcg_api nologin nobypassrls;
          create role anon nologin;
          create role authenticated nologin;
          create table tcg.owners (id uuid primary key,active bool default true);
          create table tcg.owner_memberships (
            user_id uuid not null,owner_id uuid not null,role text,active bool default true
          );
          create table tcg.orders (
            id uuid primary key,source text,source_reference text,status text
          );
          create table tcg.order_items (
            id uuid primary key,order_id uuid references tcg.orders(id),
            owner_id uuid references tcg.owners(id)
          );
          create table tcg.financial_ledger_entries (
            id uuid primary key default gen_random_uuid(),
            order_id uuid,order_item_id uuid,owner_id uuid,
            entry_type text,amount_minor bigint
          );
          create table tcg.order_item_reconciliations (
            order_item_id uuid primary key,order_id uuid,owner_id uuid,
            shipping_cost_reconciled_at timestamptz
          );
          create table tcg.audit_events (
            id bigserial primary key,actor text not null,request_id text,action text,
            entity_type text,entity_id uuid,old_values jsonb,new_values jsonb
          );
          create function tcg.current_user_id() returns uuid language sql stable
            as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          create function tcg.is_platform_admin() returns boolean
            language sql stable security definer set search_path=pg_catalog
            as $$select tcg.current_user_id()='00000000-0000-0000-0000-000000000001'::uuid$$;
          create function tcg.audit_finance_change() returns trigger
            language plpgsql security definer set search_path=pg_catalog
            as $$
            begin
              insert into tcg.audit_events(actor,request_id,action,entity_type,entity_id,
                  old_values,new_values)
              values(coalesce(nullif(current_setting('tcg.user_id',true),''),session_user::text),
                  nullif(current_setting('tcg.request_id',true),''),tg_op,tg_table_name,
                  case when tg_op='DELETE' then old.id else new.id end,
                  case when tg_op='INSERT' then null else to_jsonb(old) end,
                  case when tg_op='DELETE' then null else to_jsonb(new) end);
              return null;
            end;
            $$;
          create function tcg.prevent_finance_mutation() returns trigger
            language plpgsql set search_path=pg_catalog as $$
            begin
              raise exception 'immutable' using errcode='55000';
            end;
            $$;
          grant usage on schema tcg to tcg_api;
          grant select on tcg.owners,tcg.owner_memberships,tcg.orders,tcg.order_items,
            tcg.financial_ledger_entries,tcg.order_item_reconciliations to tcg_api;
          grant execute on function tcg.current_user_id() to tcg_api;
        """)
        await db.execute(SQL.read_text())
        assert await db.fetchval(
            "select count(*) from information_schema.tables "
            "where table_schema='tcg' and table_name like 'shopify_%'"
        ) == 3
        owner_a,owner_b,free_order,paid_order,copy_a,copy_b,paid_copy=(
            uuid4() for _ in range(7)
        )
        await db.executemany(
            "insert into tcg.owners(id) values($1)", [(owner_a,),(owner_b,)]
        )
        await db.executemany(
            "insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",
            [(SELLER_A,owner_a),(SELLER_B,owner_b),(ADMIN_USER,owner_a)]
        )
        await db.executemany(
            "insert into tcg.orders values($1,'SHOPIFY',$2,'PAID')",
            [(free_order,"310001"),(paid_order,"310002")]
        )
        await db.executemany(
            "insert into tcg.order_items values($1,$2,$3)",
            [(copy_a,free_order,owner_a),(copy_b,free_order,owner_b),
             (paid_copy,paid_order,owner_b)]
        )

        async def actor(uid):
            await db.execute("select set_config('tcg.user_id',$1,false)",str(uid))
        await db.execute("set role tcg_api")
        await actor(SELLER_A)
        # Seller may call the safe function but cannot read raw platform receipts.
        assert await db.fetchval("select count(*) from tcg.shopify_delivery_accounts")==0
        await rejected(db,"insert into tcg.shopify_delivery_accounts("
            "order_id,shopify_order_reference,customer_shipping_paid_minor,"
            "qualifying_merchandise_minor,delivery_service,destination_country,"
            "evidence_status,charge_policy,source_webhook_id) "
            "values($1,'310001',0,5500,'Royal Mail Tracked 48','GB',"
            "'VERIFIED_SHIPPING_LINES','AUTOMATIC_FREE_UK_TRACKED_48','webhook1')",free_order)
        await actor(ADMIN_USER)
        insert="""insert into tcg.shopify_delivery_accounts(
          order_id,shopify_order_reference,customer_shipping_paid_minor,
          qualifying_merchandise_minor,delivery_service,destination_country,
          evidence_status,charge_policy,source_webhook_id
        )values($1,$2,$3,$4,$5,$6,$7,$8,$9)"""
        await db.execute(insert,free_order,"310001",0,5500,"Royal Mail Tracked 48",
                         "GB","VERIFIED_SHIPPING_LINES","AUTOMATIC_FREE_UK_TRACKED_48","webhook1")
        await db.execute(insert,paid_order,"310002",395,2500,"Royal Mail Tracked 48",
                         "GB","VERIFIED_SHIPPING_LINES","COMPANY_FUNDED_CUSTOMER_PAID","webhook2")
        await rejected(db,insert,uuid4(),"310003",0,4900,"Royal Mail Tracked 48",
                       "GB","VERIFIED_SHIPPING_LINES","AUTOMATIC_FREE_UK_TRACKED_48","webhook3")

        result=await db.fetchrow("select * from tcg.owner_net_shopify_postage($1)",copy_a)
        # Admin is a separate member (not a delegated physical copy owner).
        assert result is not None and result["policy_status"]=="AUTO_CHARGE_PENDING"
        await db.execute(
            "insert into tcg.shopify_postage_actual_costs("
            "order_id,owner_id,carrier_label_reference,verified_postage_minor,"
            "owner_net_charge_minor) values($1,$2,'ROYAL-TEST-1',349,349)",
            free_order,owner_a,
        )
        await db.execute(
            "insert into tcg.financial_ledger_entries("
            "order_id,order_item_id,owner_id,entry_type,amount_minor)"
            "values($1,$2,$3,'SHIPPING_COST',-349)",
            free_order,copy_a,owner_a,
        )
        await db.execute(
            "insert into tcg.order_item_reconciliations("
            "order_item_id,order_id,owner_id,shipping_cost_reconciled_at)"
            "values($1,$2,$3,clock_timestamp())",
            copy_a,free_order,owner_a,
        )
        await db.execute(
            "insert into tcg.shopify_postage_actual_costs("
            "order_id,owner_id,carrier_label_reference,verified_postage_minor,"
            "owner_net_charge_minor) values($1,$2,'ROYAL-TEST-2',450,0)",
            paid_order,owner_b,
        )
        await rejected(db,
            "insert into tcg.shopify_postage_actual_costs("
            "order_id,owner_id,carrier_label_reference,verified_postage_minor,"
            "owner_net_charge_minor) values($1,$2,'ROYAL-TEST-3',450,0)",
            paid_order,owner_b,
        )
        await db.execute("set role postgres")
        await rejected(db,
            "update tcg.shopify_postage_actual_costs set owner_net_charge_minor=1"
        )
        await rejected(db,"delete from tcg.shopify_delivery_accounts where order_id=$1",free_order)
        await db.execute("set role tcg_api")
        await actor(SELLER_A)
        a=await db.fetchrow("select * from tcg.owner_net_shopify_postage($1)",copy_a)
        assert a["net_shipping_charge_minor"]==349 and a["policy_status"]=="AUTO_CHARGE_VERIFIED"
        assert await db.fetchrow("select * from tcg.owner_net_shopify_postage($1)",copy_b) is None
        assert await db.fetchrow("select * from tcg.owner_net_shopify_postage($1)",paid_copy) is None
        assert await db.fetchval("select count(*) from tcg.shopify_postage_actual_costs")==0
        await actor(SELLER_B)
        b=await db.fetchrow("select * from tcg.owner_net_shopify_postage($1)",copy_b)
        c=await db.fetchrow("select * from tcg.owner_net_shopify_postage($1)",paid_copy)
        assert b["policy_status"]=="AUTO_CHARGE_PENDING" and b["net_shipping_charge_minor"] is None
        assert c["policy_status"]=="NO_SELLER_CHARGE" and c["net_shipping_charge_minor"]==0
        assert await db.fetchval("select count(*) from tcg.shopify_delivery_accounts")==0
        await db.execute("reset role")
        assert await db.fetchval("select count(*) from tcg.audit_events where action='INSERT'")>=4
        print("Shopify net shipping PostgreSQL: migration, platform RLS, copy isolation, audit, unique invoice, immutable receipt and net-only view passed")
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(main())
