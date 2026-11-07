"""Disposable real PostgreSQL test of immutable legacy variant aliases."""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg


async def main():
    dsn=os.environ["SEALED_POOL_TEST_DSN"]
    parsed=urlsplit(dsn)
    assert parsed.hostname in ("127.0.0.1","localhost")
    assert parsed.path=="/sealed_pool_test"
    db=await asyncpg.connect(dsn)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute("""create schema tcg;
          create role tcg_api nologin nobypassrls;
          create role anon nologin;
          create role authenticated nologin;
          create role service_role nologin;
          create role tcg_auditor nologin;
          create table tcg.owners(id uuid primary key,owner_type text);
          create table tcg.inventory_items(id uuid primary key,owner_id uuid not null references tcg.owners(id),inventory_code text);
          create function tcg.current_user_id() returns uuid language sql stable as
            $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
          create function tcg.is_platform_admin() returns boolean language sql stable as
            $$select tcg.current_user_id()='00000000-0000-0000-0000-000000000001'::uuid$$;
          grant usage on schema tcg to tcg_api;
          grant select on tcg.inventory_items,tcg.owners to tcg_api;
        """)
        sql=(Path(__file__).parents[1]/"database/migrations/20261010195000_shopify_variant_pool_aliases.sql").read_text()
        await db.execute(sql)
        await db.execute(sql) # migration is idempotent on retry
        owner,inventory,anchor=uuid4(),uuid4(),uuid4()
        await db.execute("insert into tcg.owners values($1,'CONSIGNOR')",owner)
        await db.execute("insert into tcg.inventory_items values($1,$2,'INV-OLD')",inventory,owner)
        await db.execute("insert into tcg.inventory_items values($1,$2,'INV-ANCHOR')",anchor,owner)
        record=(
          "gid://shopify/ProductVariant/101","gid://shopify/Product/201","INV-OLD",
          inventory,owner,uuid4(),"fqu56y-hm.myshopify.com",
          "gid://shopify/ProductVariant/102","gid://shopify/Product/202",
          "shopify-pool:sealed:fixture"
        )
        insert="""insert into tcg.shopify_variant_pool_aliases(
          legacy_variant_gid,legacy_product_gid,legacy_sku,inventory_id,owner_id,
          created_by_user_id,shop_domain,pooled_variant_gid,pooled_product_gid,listing_key
        ) values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)"""
        await db.execute("set role tcg_api")
        # A webhook can read an alias without any actor context; it cannot write.
        assert not await db.fetchval("select exists(select 1 from tcg.shopify_variant_pool_aliases)")
        try:
            await db.execute(insert,*record)
            raise AssertionError("Consignor/unidentified caller inserted an alias")
        except asyncpg.InsufficientPrivilegeError:pass
        await db.execute("select set_config('tcg.user_id','00000000-0000-0000-0000-000000000001',false)")
        await db.execute(insert,*record)
        found=await db.fetchrow("select * from tcg.shopify_variant_pool_aliases where legacy_variant_gid=$1",record[0])
        assert found["inventory_id"]==inventory
        assert found["owner_id"]==owner
        assert found["legacy_sku"]=="INV-OLD"
        anchor_alias=(
          "gid://shopify/ProductVariant/102","gid://shopify/Product/202","INV-ANCHOR",
          anchor,owner,uuid4(),"fqu56y-hm.myshopify.com",
          "gid://shopify/ProductVariant/102","gid://shopify/Product/202",
          "shopify-pool:sealed:fixture"
        )
        # The anchor keeps its variant ID but must retain its ORIGINAL SKU
        # for an order placed before the product was pooled.
        await db.execute(insert,*anchor_alias)
        anchor_row=await db.fetchrow("select * from tcg.shopify_variant_pool_aliases where legacy_variant_gid=$1",anchor_alias[0])
        assert anchor_row["inventory_id"]==anchor
        assert anchor_row["legacy_variant_gid"]==anchor_row["pooled_variant_gid"]
        try:
            await db.execute("update tcg.shopify_variant_pool_aliases set legacy_sku='TAMPERED'")
            raise AssertionError("Immutable alias is writable")
        except asyncpg.InsufficientPrivilegeError:pass
        try:
            await db.execute(insert,*record)
            raise AssertionError("Duplicate legacy variant was accepted")
        except asyncpg.UniqueViolationError:pass
        assert await db.fetchval("select count(*) from tcg.shopify_variant_pool_aliases")==2
        assert await db.fetchval("select count(*) from tcg.inventory_items")==2
        print("Sealed Shopify alias PostgreSQL: RLS, immutable alias, exact owner, unique legacy ID and migration replay passed")
    finally:
        await db.close()

if __name__=="__main__":asyncio.run(main())
