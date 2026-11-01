"""Apply the actual expanded-collectibles DDL to disposable PostgreSQL 17.

Run only against an empty local database named expanded_collectibles_test.
No production credentials, remote databases, Shopify, R2 writes or stock data.

  EXPANDED_COLLECTIBLES_TEST_DSN=postgresql://postgres:...@127.0.0.1:5432/expanded_collectibles_test \
    PYTHONPATH=backend python tests/expanded_collectibles_postgres.py
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg

from app.collectible_source_adapters import (
    figure_product,
    sports_checklist_printing,
    yugioh_printings,
)
from app.reference_library import save_reference_set


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/migrations/20261101205040_collectible_catalogue_expansion.sql"

# The actual predecessor table shape, PK and FK contract, with a minimal
# founder-authorisation fixture. This is not a substitute for production dry-run.
BASE_SCHEMA = """
create schema tcg;
create schema tcg_private;
create role tcg_api nologin nosuperuser nobypassrls;
create role anon nologin;
create role authenticated nologin;
grant usage on schema tcg,tcg_private to tcg_api;
create table tcg.test_founder_admins(user_id uuid primary key);
create function tcg.current_user_id() returns uuid language sql stable
  as $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
create function tcg.is_platform_admin() returns boolean language sql stable
  security definer set search_path=pg_catalog
  as $$select exists(select 1 from tcg.test_founder_admins
        where user_id=tcg.current_user_id())$$;
revoke all on function tcg.is_platform_admin() from public,anon,authenticated;
grant execute on function tcg.is_platform_admin() to tcg_api;
create table tcg.collectible_systems(
  code text primary key check(code ~ '^[A-Z0-9_]{2,80}$'),
  display_name text not null, franchise text not null,
  system_kind text not null constraint collectible_systems_system_kind_check
    check(system_kind in ('TCG','COMICS')),
  publisher text, lifecycle_status text not null default 'ACTIVE',
  official_url text, metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),updated_at timestamptz not null default now()
);
insert into tcg.collectible_systems(code,display_name,franchise,system_kind)
values ('YUGIOH','Yu-Gi-Oh!','Yu-Gi-Oh!','TCG'),
       ('DISNEY_LORCANA','Lorcana','Lorcana','TCG'),
       ('RIFTBOUND','Riftbound','Riftbound','TCG');
grant select on tcg.collectible_systems to tcg_api;
create table tcg.reference_sets(
 provider text not null,system_code text not null references tcg.collectible_systems(code),
 language text not null,set_id text not null,name text not null,release_date date,
 declared_card_count integer check (declared_card_count >= 0),
 source_url text not null check (source_url like 'https://%'),
 refreshed_at timestamptz not null default now(),
 primary key(provider,system_code,language,set_id)
);
create table tcg.reference_cards(
 provider text not null,system_code text not null references tcg.collectible_systems(code),
 language text not null,provider_id text not null,set_id text not null,
 name text not null,card_number text not null,number_key text not null,
 finish text,rarity text,image_url text,
 source_url text not null check (source_url like 'https://%'),
 evidence jsonb not null default '{}'::jsonb,
 refreshed_at timestamptz not null default now(),
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,set_id)
   references tcg.reference_sets(provider,system_code,language,set_id)
);
alter table tcg.reference_sets enable row level security;
alter table tcg.reference_sets force row level security;
alter table tcg.reference_cards enable row level security;
alter table tcg.reference_cards force row level security;
create policy reference_sets_admin on tcg.reference_sets for all to postgres
  using(true) with check(true);
create policy reference_cards_admin on tcg.reference_cards for all to postgres
  using(true) with check(true);
create policy reference_sets_read on tcg.reference_sets for select to tcg_api
  using((select tcg.current_user_id()) is not null);
create policy reference_cards_read on tcg.reference_cards for select to tcg_api
  using((select tcg.current_user_id()) is not null);
create policy reference_sets_insert on tcg.reference_sets for insert to tcg_api
  with check((select tcg.is_platform_admin()));
create policy reference_cards_insert on tcg.reference_cards for insert to tcg_api
  with check((select tcg.is_platform_admin()));
create policy reference_sets_update on tcg.reference_sets for update to tcg_api
  using((select tcg.is_platform_admin())) with check((select tcg.is_platform_admin()));
create policy reference_cards_update on tcg.reference_cards for update to tcg_api
  using((select tcg.is_platform_admin())) with check((select tcg.is_platform_admin()));
grant select,insert,update on tcg.reference_sets,tcg.reference_cards to tcg_api;
"""


async def rejected(connection, query: str, *args) -> None:
    """Blocked writes may raise or match zero RLS-visible rows (UPDATE/DELETE)."""
    async with connection.transaction():
        try:
            async with connection.transaction():
                tag = await connection.execute(query, *args)
        except asyncpg.PostgresError:
            return
        else:
            if tag.endswith(" 0") and tag.split(" ", 1)[0] in {"UPDATE", "DELETE"}:
                return
            raise AssertionError("Unexpectedly accepted a forbidden operation: " + tag)


async def main() -> None:
    dsn = os.environ["EXPANDED_COLLECTIBLES_TEST_DSN"]
    url = urlsplit(dsn)
    assert url.scheme in {"postgres", "postgresql"}
    assert url.hostname in {"localhost", "127.0.0.1"}
    assert url.port in {None, 5432}
    assert url.path == "/expanded_collectibles_test"
    admin_id, member_id = uuid4(), uuid4()
    db = await asyncpg.connect(dsn=dsn)
    admin = member = None
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')"), "Test DB must be empty"
        await db.execute(BASE_SCHEMA)
        await db.execute(MIGRATION.read_text())
        await db.execute("insert into tcg.test_founder_admins values($1)", admin_id)
        assert await db.fetchval("select count(*) from tcg.collectible_systems") == 11
        assert await db.fetchval("select count(*) from tcg.collectible_systems where system_kind='FIGURE'") == 2
        assert await db.fetchval("select count(*) from tcg.collectible_systems where system_kind='SPORTS_CARD'") == 6
        assert await db.fetchval("select count(*) from tcg_private.reference_figures_r2_publication") == 2
        # Every new reference and publication table must force RLS.
        assert await db.fetchval("""
            select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where ((n.nspname='tcg' and c.relname in
              ('reference_card_product_details','reference_figure_products',
               'reference_figure_market_observations','reference_figure_market_values'))
              or (n.nspname='tcg_private' and c.relname='reference_figures_r2_publication'))
              and c.relrowsecurity and c.relforcerowsecurity
        """) == 5

        admin = await asyncpg.connect(dsn=dsn)
        member = await asyncpg.connect(dsn=dsn)
        for conn in (admin, member):
            await conn.execute("set role tcg_api")
        assert await member.fetchval("select count(*) from tcg.reference_figure_products") == 0
        await admin.execute("select set_config('tcg.user_id',$1,false)", str(admin_id))
        await member.execute("select set_config('tcg.user_id',$1,false)", str(member_id))
        assert await admin.fetchval("select tcg.is_platform_admin()")
        assert not await member.fetchval("select tcg.is_platform_admin()")

        # A source-identified figure is only reference metadata. No image or
        # valuation can silently appear from a product page or listing.
        figure = figure_product({
            "system_code": "FUNKO_POP", "manufacturer": "Funko", "provider_id": "test-97402",
            "name": "Synthetic test figure", "figure_number": "123",
            "barcode_gtin": "889698974027", "source_url": "https://funko.com/gb/pop-yellow-lantern/97402.html",
            "reference_image_url": "https://funko.com/images/example.jpg",
        })
        await admin.execute("""
            insert into tcg.reference_figure_products
              (provider,system_code,language,provider_id,name,manufacturer,
               figure_number,barcode_gtin,source_url,reference_image_url)
            values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """, *(figure[k] for k in (
            "provider", "system_code", "language", "provider_id", "name", "manufacturer",
            "figure_number", "barcode_gtin", "source_url", "reference_image_url")))
        assert await member.fetchval("select count(*) from tcg.reference_figure_products") == 1
        assert await member.fetchval("select image_r2_key from tcg.reference_figure_products") is None
        assert await db.fetchval("select generation from tcg_private.reference_figures_r2_publication where system_code='FUNKO_POP'") == 2
        assert await db.fetchval("select generation from tcg_private.reference_figures_r2_publication where system_code='COLLECTIBLE_FIGURES'") == 1
        await rejected(member, "update tcg.reference_figure_products set name='tampered' where provider_id='test-97402'")
        await rejected(member, """
          insert into tcg.reference_figure_market_observations
            (provider,system_code,language,provider_id,market_source,observation_key,
             evidence_kind,observed_at,price_minor,currency,source_url)
          values('Funko Official','FUNKO_POP','English','test-97402','bad','x','SOLD',now(),500,'GBP','https://example.com')
        """)
        await rejected(admin, "update tcg.reference_figure_products set image_r2_key='drop-rate/private-media/unknown.webp' where provider_id='test-97402'")
        await rejected(admin, """
          insert into tcg.reference_figure_products(provider,system_code,language,provider_id,
             name,manufacturer,source_url)
          values('Funko Official','YUGIOH','English','fake','Invalid','Funko','https://funko.com/')
        """)
        await admin.execute("""
          insert into tcg.reference_figure_market_observations
            (provider,system_code,language,provider_id,market_source,observation_key,
             evidence_kind,observed_at,price_minor,currency,source_url)
          values('Funko Official','FUNKO_POP','English','test-97402','test-listing','listed-1',
            'ACTIVE',now(),799,'GBP','https://example.com/listed-1')
        """)
        await rejected(admin, "update tcg.reference_figure_market_observations set evidence_kind='SOLD'")
        assert await member.fetchval("select count(*) from tcg.reference_figure_market_observations where evidence_kind='SOLD'") == 0
        assert await db.fetchval("select count(*) from tcg.reference_figure_market_values") == 0

        # Exercise the *existing* reference upsert path for exact Yu-Gi-Oh!
        # printings and sports parallels; neither can create a listing or price.
        source_card = {"id": 46986414, "name": "Synthetic Dark Magician",
                       "card_sets": [{"set_name": "2016 Mega-Tins", "set_code": "CT13-EN003",
                                      "set_rarity": "Ultra Rare", "set_rarity_code": "(UR)"}]}
        official = {"2016 Mega-Tins": {"set_code": "CT13", "tcg_date": "2016-09-01", "num_of_cards": 12}}
        sample = yugioh_printings(source_card, official_tcg_sets=official)
        assert len(sample) == 1
        await save_reference_set(admin, sample[0][0], [sample[0][1]])
        row = {"system_code": "SPORT_SOCCER", "source_url": "https://uk.topps.com/pages/checklists",
               "manufacturer": "Topps", "series": "Chrome Premier League", "year": 2026,
               "card_number": "PL-101", "athlete": "Synthetic footballer",
               "parallel": "Red /5", "print_run": 5}
        sport_set, sport_card, details = sports_checklist_printing(row)
        await save_reference_set(admin, sport_set, [sport_card])
        await admin.execute("""
          insert into tcg.reference_card_product_details
            (provider,system_code,language,provider_id,manufacturer,product_line,
             sport,athlete,parallel,print_run,source_url,attributes)
          values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
        """, *(details[k] for k in ("provider", "system_code", "language", "provider_id",
                                  "manufacturer", "product_line", "sport", "athlete",
                                  "parallel", "print_run", "source_url")), json.dumps(details["attributes"]))
        assert await member.fetchval("select count(*) from tcg.reference_cards") == 2
        assert await member.fetchval("select count(*) from tcg.reference_card_product_details") == 1
        assert await member.fetchval("select count(*) from tcg.reference_cards where image_url is not null") == 0
        await rejected(member, "delete from tcg.reference_card_product_details")
        print(json.dumps({"status": "PASS", "migration": MIGRATION.name,
                          "systems": 11, "staged_cards": 2, "staged_figures": 1,
                          "verified_market_values": 0, "media_copies": 0,
                          "shopify_products": 0}, sort_keys=True))
    finally:
        if member is not None:
            await member.close()
        if admin is not None:
            await admin.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
