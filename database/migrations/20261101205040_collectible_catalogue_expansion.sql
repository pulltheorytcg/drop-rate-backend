begin;

-- Expand the *reference* registry; this does not make new kinds sellable stock.
-- Existing canonical card, owner, pricing and Shopify rules stay unchanged.
alter table tcg.collectible_systems
  drop constraint collectible_systems_system_kind_check;
alter table tcg.collectible_systems
  add constraint collectible_systems_system_kind_check
  check (system_kind in ('TCG', 'COMICS', 'SPORTS_CARD', 'FIGURE'));

insert into tcg.collectible_systems
  (code, display_name, franchise, system_kind, publisher, lifecycle_status, official_url)
values
  ('SPORT_SOCCER', 'Football (soccer) cards', 'Football', 'SPORTS_CARD', null, 'ACTIVE', 'https://uk.topps.com/'),
  ('SPORT_AMERICAN_FOOTBALL', 'American football cards', 'American Football', 'SPORTS_CARD', null, 'ACTIVE', 'https://www.paniniamerica.net/'),
  ('SPORT_BASKETBALL', 'Basketball cards', 'Basketball', 'SPORTS_CARD', null, 'ACTIVE', 'https://www.paniniamerica.net/'),
  ('SPORT_BASEBALL', 'Baseball cards', 'Baseball', 'SPORTS_CARD', null, 'ACTIVE', 'https://www.topps.com/'),
  ('SPORT_HOCKEY', 'Ice hockey cards', 'Ice Hockey', 'SPORTS_CARD', null, 'ACTIVE', null),
  ('SPORT_MOTORSPORT', 'Motorsport cards', 'Motorsport', 'SPORTS_CARD', null, 'ACTIVE', null),
  ('FUNKO_POP', 'Funko Pop!', 'Funko', 'FIGURE', 'Funko', 'ACTIVE', 'https://funko.com/gb/'),
  ('COLLECTIBLE_FIGURES', 'Other collectible figures', 'Collectible Figures', 'FIGURE', null, 'ACTIVE', null)
on conflict (code) do nothing;

-- Optional typed attributes on existing reference_cards. A manufacturer-specific
-- parallel is not interchangeable with the base printing or a different sport.
create table tcg.reference_card_product_details (
  provider text not null,
  system_code text not null,
  language text not null,
  provider_id text not null,
  manufacturer text not null check (length(btrim(manufacturer)) between 1 and 160),
  product_line text,
  sport text,
  league text,
  team text,
  athlete text,
  parallel text,
  print_run integer check (print_run is null or print_run > 0),
  is_autograph boolean not null default false,
  is_memorabilia boolean not null default false,
  manufacturer_sku text,
  source_url text not null check (source_url like 'https://%'),
  attributes jsonb not null default '{}'::jsonb check (jsonb_typeof(attributes) = 'object'),
  refreshed_at timestamptz not null default now(),
  primary key (provider, system_code, language, provider_id),
  foreign key (provider, system_code, language, provider_id)
    references tcg.reference_cards(provider, system_code, language, provider_id)
);
create index reference_card_product_details_athlete_idx
  on tcg.reference_card_product_details(system_code, lower(athlete))
  where athlete is not null;

-- Reference figure models are distinct from individual physical copies.
-- This table is not a Shopify product or a sellable inventory record.
create table tcg.reference_figure_products (
  provider text not null,
  system_code text not null references tcg.collectible_systems(code),
  language text not null check (length(btrim(language)) between 1 and 48),
  provider_id text not null check (length(btrim(provider_id)) between 1 and 160),
  name text not null check (length(btrim(name)) between 1 and 240),
  manufacturer text not null check (length(btrim(manufacturer)) between 1 and 160),
  franchise text,
  series_name text,
  figure_number text,
  manufacturer_sku text,
  barcode_gtin text check (barcode_gtin is null or barcode_gtin ~ '^[0-9]{8,14}$'),
  edition text,
  variant text not null default '',
  exclusive_to text,
  release_date date,
  source_url text not null check (source_url like 'https://%'),
  reference_image_url text check (reference_image_url is null or reference_image_url like 'https://%'),
  image_rights_status text not null default 'UNVERIFIED'
    check (image_rights_status in ('UNVERIFIED', 'APPROVED', 'DENIED')),
  image_rights_evidence_url text
    check (image_rights_evidence_url is null or image_rights_evidence_url like 'https://%'),
  image_r2_key text,
  image_sha256 text,
  attributes jsonb not null default '{}'::jsonb check (jsonb_typeof(attributes) = 'object'),
  refreshed_at timestamptz not null default now(),
  primary key (provider, system_code, language, provider_id),
  check ((image_r2_key is null) = (image_sha256 is null)),
  check (image_r2_key is null or
    (image_rights_status = 'APPROVED' and image_rights_evidence_url is not null
      and image_sha256 ~ '^[a-f0-9]{64}$'
      and image_r2_key = 'drop-rate/private-media/' || image_sha256 || '.webp'))
);
create index reference_figure_search_idx
  on tcg.reference_figure_products(system_code, lower(name));
create index reference_figure_series_idx
  on tcg.reference_figure_products(system_code, series_name, figure_number);

create function tcg_private.require_figure_reference_system()
returns trigger language plpgsql security invoker set search_path = pg_catalog as $$
begin
  if not exists (select 1 from tcg.collectible_systems
                 where code = new.system_code and system_kind = 'FIGURE') then
    raise exception 'Reference figure requires a FIGURE catalogue system'
      using errcode = '23514';
  end if;
  return new;
end;
$$;
revoke all on function tcg_private.require_figure_reference_system()
  from public, anon, authenticated;
grant execute on function tcg_private.require_figure_reference_system() to tcg_api;
create trigger reference_figure_system_kind
  before insert or update of system_code on tcg.reference_figure_products
  for each row execute function tcg_private.require_figure_reference_system();

-- Append-only raw sale/listing/guide evidence; a listing is NEVER a sold sale.
-- Market values are null until a separately reviewed pricing calculation runs.
create table tcg.reference_figure_market_observations (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  system_code text not null,
  language text not null,
  provider_id text not null,
  market_source text not null,
  observation_key text not null,
  evidence_kind text not null check (evidence_kind in ('SOLD', 'ACTIVE', 'GUIDE')),
  observed_at timestamptz not null,
  price_minor bigint not null check (price_minor > 0),
  currency text not null check (currency ~ '^[A-Z]{3}$'),
  shipping_minor bigint check (shipping_minor is null or shipping_minor >= 0),
  condition text,
  grade_company text,
  grade text,
  source_url text not null check (source_url like 'https://%'),
  raw_evidence jsonb not null default '{}'::jsonb check (jsonb_typeof(raw_evidence) = 'object'),
  created_at timestamptz not null default now(),
  unique(market_source, observation_key),
  foreign key (provider, system_code, language, provider_id)
    references tcg.reference_figure_products(provider, system_code, language, provider_id)
);
create index reference_figure_observations_time_idx
  on tcg.reference_figure_market_observations
  (provider, system_code, language, provider_id, observed_at desc);

create table tcg.reference_figure_market_values (
  provider text not null,
  system_code text not null,
  language text not null,
  provider_id text not null,
  market_value_gbp_minor bigint check (market_value_gbp_minor is null or market_value_gbp_minor > 0),
  price_method_version text,
  evidence_count integer not null default 0 check (evidence_count >= 0),
  priced_at timestamptz,
  expires_at timestamptz,
  primary key (provider, system_code, language, provider_id),
  foreign key (provider, system_code, language, provider_id)
    references tcg.reference_figure_products(provider, system_code, language, provider_id),
  check ((market_value_gbp_minor is null and price_method_version is null and priced_at is null and expires_at is null and evidence_count = 0)
      or (market_value_gbp_minor is not null and price_method_version is not null
        and priced_at is not null and expires_at > priced_at and evidence_count > 0))
);

-- The API role sees only authenticated reference facts, and can mutate only
-- as a platform administrator. Ingest cannot touch owner or inventory data.
do $$
declare t text;
begin
  foreach t in array array[
    'reference_card_product_details', 'reference_figure_products',
    'reference_figure_market_observations', 'reference_figure_market_values'
  ] loop
    execute format('alter table tcg.%I enable row level security', t);
    execute format('alter table tcg.%I force row level security', t);
    execute format('create policy %I on tcg.%I for all to postgres using (true) with check (true)', t || '_admin', t);
    execute format('create policy %I on tcg.%I for select to tcg_api using ((select tcg.current_user_id()) is not null)', t || '_read', t);
    execute format('revoke all on tcg.%I from public, anon, authenticated, tcg_api', t);
  end loop;
end $$;
create policy reference_card_product_details_write on tcg.reference_card_product_details
  for all to tcg_api using ((select tcg.is_platform_admin()))
  with check ((select tcg.is_platform_admin()));
create policy reference_figure_products_write on tcg.reference_figure_products
  for all to tcg_api using ((select tcg.is_platform_admin()))
  with check ((select tcg.is_platform_admin()));
create policy reference_figure_market_values_write on tcg.reference_figure_market_values
  for all to tcg_api using ((select tcg.is_platform_admin()))
  with check ((select tcg.is_platform_admin()));
create policy reference_figure_market_observations_insert on tcg.reference_figure_market_observations
  for insert to tcg_api with check ((select tcg.is_platform_admin()));

grant select, insert, update on tcg.reference_card_product_details,
  tcg.reference_figure_products, tcg.reference_figure_market_values to tcg_api;
grant select, insert on tcg.reference_figure_market_observations to tcg_api;
comment on table tcg.reference_figure_products is
  'Provider reference facts, not owner stock; R2 artwork requires rights evidence and never substitutes for physical Shopify photos.';
comment on table tcg.reference_figure_market_values is
  'Nullable verified GBP guides, not store price or owner inventory value.';

-- Independent sidecar publication. It cannot invalidate or replace the
-- production card/sealed R2 manifest, and never contains private owner data.
create table tcg_private.reference_figures_r2_publication (
  system_code text primary key references tcg.collectible_systems(code),
  generation bigint not null default 1 check (generation > 0),
  published_generation bigint,
  manifest jsonb,
  published_at timestamptz,
  check ((manifest is null) = (published_generation is null)),
  check (published_generation is null or published_generation <= generation)
);
insert into tcg_private.reference_figures_r2_publication(system_code)
values ('FUNKO_POP'), ('COLLECTIBLE_FIGURES');
alter table tcg_private.reference_figures_r2_publication enable row level security;
alter table tcg_private.reference_figures_r2_publication force row level security;
create policy reference_figures_r2_admin on tcg_private.reference_figures_r2_publication
  for all to postgres using (true) with check (true);
create policy reference_figures_r2_read on tcg_private.reference_figures_r2_publication
  for select to tcg_api using ((select tcg.current_user_id()) is not null);
create policy reference_figures_r2_write on tcg_private.reference_figures_r2_publication
  for update to tcg_api using ((select tcg.is_platform_admin()))
  with check ((select tcg.is_platform_admin()));
revoke all on tcg_private.reference_figures_r2_publication from public, anon, authenticated, tcg_api;
grant select on tcg_private.reference_figures_r2_publication to tcg_api;
grant update(published_generation, manifest, published_at)
  on tcg_private.reference_figures_r2_publication to tcg_api;

create function tcg_private.invalidate_reference_figures_r2()
returns trigger language plpgsql security definer set search_path = pg_catalog as $$
begin
  if TG_TABLE_SCHEMA <> 'tcg' or TG_TABLE_NAME not in
    ('reference_figure_products', 'reference_figure_market_values') then
    raise exception 'Unexpected figure-reference publication source';
  end if;
  if TG_OP = 'TRUNCATE' then
    update tcg_private.reference_figures_r2_publication
      set generation = generation + 1;
  elsif TG_OP = 'INSERT' then
    update tcg_private.reference_figures_r2_publication p
      set generation = p.generation + 1
    where exists (select 1 from new_rows n where n.system_code = p.system_code);
  elsif TG_OP = 'DELETE' then
    update tcg_private.reference_figures_r2_publication p
      set generation = p.generation + 1
    where exists (select 1 from old_rows o where o.system_code = p.system_code);
  elsif TG_OP = 'UPDATE' then
    update tcg_private.reference_figures_r2_publication p
      set generation = p.generation + 1
    where exists (select 1 from new_rows n where n.system_code = p.system_code)
       or exists (select 1 from old_rows o where o.system_code = p.system_code);
  end if;
  return null;
end;
$$;
revoke all on function tcg_private.invalidate_reference_figures_r2()
  from public, anon, authenticated, tcg_api;

do $$
declare table_name text;
begin
  foreach table_name in array array['reference_figure_products', 'reference_figure_market_values'] loop
    execute format('create trigger %I after insert on tcg.%I referencing new table as new_rows for each statement execute function tcg_private.invalidate_reference_figures_r2()', table_name || '_r2_insert', table_name);
    execute format('create trigger %I after update on tcg.%I referencing old table as old_rows new table as new_rows for each statement execute function tcg_private.invalidate_reference_figures_r2()', table_name || '_r2_update', table_name);
    execute format('create trigger %I after delete on tcg.%I referencing old table as old_rows for each statement execute function tcg_private.invalidate_reference_figures_r2()', table_name || '_r2_delete', table_name);
    execute format('create trigger %I after truncate on tcg.%I for each statement execute function tcg_private.invalidate_reference_figures_r2()', table_name || '_r2_truncate', table_name);
  end loop;
end $$;

commit;
