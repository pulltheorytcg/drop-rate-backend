"""Extend disposable test schemas with the actual shared-market migrations.

Never imported by application code. Call only after localhost/fresh-database
assertions in the parent integration test. No provider functions are stubbed.
"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

async def install_reference_schema(db):
    await db.execute('''
      do $$begin
        if not exists(select 1 from pg_roles where rolname='anon') then create role anon nologin;end if;
        if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin;end if;
        if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role nologin;end if;
      end$$;
      create table if not exists tcg.reference_sets(provider text,system_code text,language text,set_id text,name text,release_date date);
      alter table tcg.reference_sets add column if not exists release_date date;
      create table if not exists tcg.reference_cards(provider text,system_code text,language text,provider_id text,set_id text,name text,card_number text,rarity text,image_url text);
      create table if not exists tcg.reference_market_prices(provider text,system_code text,language text,provider_id text,quotes jsonb);
      create table if not exists tcg.reference_catalogue_prices(provider text,system_code text,language text,provider_id text,quotes jsonb);
      alter table tcg.reference_cards add column if not exists number_key text;
      create table if not exists tcg.reference_sealed_products(provider text,system_code text,language text,provider_id text,set_id text,name text,product_type text,image_url text);
      create table if not exists tcg.provider_catalogue_mappings(catalogue_id uuid,source_provider text,system_code text,provider_language text,provider_id text,provider_entity_type text,provider_variant_key text,match_status text);
      create table if not exists tcg.market_source_mappings(catalogue_id uuid,source text,match_status text);
      create table if not exists tcg.catalogue_job_runs(job text constraint catalogue_job_runs_job_check check(job in ('REFERENCE_PRICES')));
      alter table tcg.catalogue_products add column if not exists language text,add column if not exists rarity text;
      alter table tcg.inventory_items add column if not exists seal_status text,add column if not exists recommended_retail_minor bigint;
      do $$begin
        if to_regprocedure('tcg.is_platform_admin()') is null then
          execute 'create function tcg.is_platform_admin() returns boolean language sql stable as $f$select exists(select 1 from tcg.owner_memberships where user_id=tcg.current_user_id() and active and role=''PLATFORM_ADMIN'')$f$';
        end if;
        if to_regclass('tcg.media_assets') is not null then
          alter table tcg.media_assets add column if not exists source_provider text;
        end if;
      end$$;
      grant select on tcg.reference_sets,tcg.reference_cards,tcg.reference_market_prices,tcg.reference_catalogue_prices,tcg.reference_sealed_products,
        tcg.provider_catalogue_mappings,tcg.market_source_mappings to tcg_api;
    ''')
    for name in ('20261009184349_independent_catalogue_valuations.sql',
                 '20261009185130_activate_catalogue_reference_values.sql',
                 '20261009193333_cardmarket_valuation_fallback.sql',
                 '20261010010226_cardmarket_multigame_guard.sql'):
        await db.execute((ROOT/'database/migrations'/name).read_text())
