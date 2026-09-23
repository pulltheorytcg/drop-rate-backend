begin;

alter table tcg.inventory_items
    add column if not exists market_value_minor bigint check (market_value_minor is null or market_value_minor >= 0),
    add column if not exists recommended_retail_minor bigint check (recommended_retail_minor is null or recommended_retail_minor >= 0),
    add column if not exists pricing_updated_at timestamptz;

create table tcg.market_source_mappings (
    id uuid primary key default gen_random_uuid(),
    catalogue_id uuid not null references tcg.catalogue_products(id),
    source text not null check (source in ('EBAY', 'COLLECTR', 'TCGPLAYER', 'CARDMARKET', 'MANUAL')),
    source_product_id text not null,
    source_variant_id text,
    match_status text not null default 'REVIEW'
        check (match_status in ('REVIEW', 'VERIFIED', 'REJECTED')),
    match_confidence numeric(5,4) not null default 0
        check (match_confidence >= 0 and match_confidence <= 1),
    metadata jsonb not null default '{}'::jsonb,
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index market_source_mapping_identity_key
    on tcg.market_source_mappings(source, source_product_id, coalesce(source_variant_id, ''));
create index market_source_mapping_catalogue_idx
    on tcg.market_source_mappings(catalogue_id, source, match_status);

create table tcg.market_observations (
    id uuid primary key default gen_random_uuid(),
    catalogue_id uuid not null references tcg.catalogue_products(id),
    source text not null check (source in ('EBAY', 'COLLECTR', 'TCGPLAYER', 'CARDMARKET', 'MANUAL')),
    source_record_key text not null,
    observation_type text not null
        check (observation_type in ('SOLD', 'ACTIVE', 'MARKET_AGGREGATE', 'PRICE_GUIDE')),
    observed_at timestamptz not null,
    price_minor bigint not null check (price_minor > 0),
    shipping_minor bigint check (shipping_minor is null or shipping_minor >= 0),
    currency text not null check (char_length(currency) = 3),
    price_gbp_minor bigint not null check (price_gbp_minor > 0),
    shipping_gbp_minor bigint check (shipping_gbp_minor is null or shipping_gbp_minor >= 0),
    fx_rate_to_gbp numeric(18,8) not null check (fx_rate_to_gbp > 0),
    condition text,
    grading_company text,
    grade text,
    language text,
    seal_status text check (seal_status is null or seal_status in ('SEALED', 'UNSEALED')),
    source_country text check (source_country is null or char_length(source_country) = 2),
    sample_size integer not null default 1 check (sample_size >= 1),
    evidence_quality numeric(5,4) not null default 1
        check (evidence_quality >= 0 and evidence_quality <= 1),
    metadata jsonb not null default '{}'::jsonb,
    ingested_at timestamptz not null default now(),
    check ((grading_company is null) = (grade is null)),
    unique (source, source_record_key)
);

create index market_observations_catalogue_time_idx
    on tcg.market_observations(catalogue_id, observed_at desc);
create index market_observations_comparable_idx
    on tcg.market_observations(
        catalogue_id, condition, grading_company, grade, language, seal_status, observed_at desc
    );
create index market_observations_source_time_idx
    on tcg.market_observations(source, observed_at desc);

create table tcg.pricing_policies (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null unique references tcg.owners(id),
    auto_reprice_enabled boolean not null default false,
    min_confidence numeric(5,4) not null default 0.8000
        check (min_confidence >= 0 and min_confidence <= 1),
    min_sources integer not null default 2 check (min_sources >= 1),
    max_auto_change_pct numeric(7,3) not null default 10.000 check (max_auto_change_pct > 0),
    high_value_review_minor bigint not null default 50000 check (high_value_review_minor >= 0),
    min_price_change_minor bigint not null default 100 check (min_price_change_minor >= 0),
    min_price_change_pct numeric(7,3) not null default 2.000 check (min_price_change_pct >= 0),
    max_volatility_pct numeric(7,3) not null default 20.000 check (max_volatility_pct >= 0),
    retail_multiplier numeric(8,4) not null default 1.0000 check (retail_multiplier > 0),
    quick_sale_multiplier numeric(8,4) not null default 0.9200 check (quick_sale_multiplier > 0),
    acquisition_multiplier numeric(8,4) not null default 0.7000 check (acquisition_multiplier > 0),
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table tcg.pricing_snapshots (
    id uuid primary key default gen_random_uuid(),
    inventory_id uuid not null references tcg.inventory_items(id),
    catalogue_id uuid not null references tcg.catalogue_products(id),
    owner_id uuid not null references tcg.owners(id),
    market_value_minor bigint not null check (market_value_minor >= 0),
    recommended_retail_minor bigint not null check (recommended_retail_minor >= 0),
    quick_sale_minor bigint not null check (quick_sale_minor >= 0),
    target_acquisition_minor bigint not null check (target_acquisition_minor >= 0),
    confidence numeric(5,4) not null check (confidence >= 0 and confidence <= 1),
    source_count integer not null check (source_count >= 0),
    observation_count integer not null check (observation_count >= 0),
    sold_observation_count integer not null check (sold_observation_count >= 0),
    volatility_pct numeric(9,4) not null default 0 check (volatility_pct >= 0),
    newest_observation_at timestamptz,
    algorithm_version text not null,
    evidence jsonb not null default '{}'::jsonb,
    auto_publish_eligible boolean not null default false,
    block_reasons jsonb not null default '[]'::jsonb,
    calculated_at timestamptz not null default now()
);

create index pricing_snapshots_inventory_time_idx
    on tcg.pricing_snapshots(inventory_id, calculated_at desc);
create index pricing_snapshots_owner_time_idx
    on tcg.pricing_snapshots(owner_id, calculated_at desc);

alter table tcg.inventory_items
    add column if not exists latest_pricing_snapshot_id uuid references tcg.pricing_snapshots(id);

alter table tcg.market_source_mappings enable row level security;
alter table tcg.market_observations enable row level security;
alter table tcg.pricing_policies enable row level security;
alter table tcg.pricing_snapshots enable row level security;

create policy admin_access on tcg.market_source_mappings
    for all to postgres using (true) with check (true);
create policy api_access on tcg.market_source_mappings
    for all to tcg_api using (true) with check (true);

create policy admin_access on tcg.market_observations
    for all to postgres using (true) with check (true);
create policy api_read on tcg.market_observations
    for select to tcg_api using (true);
create policy api_insert on tcg.market_observations
    for insert to tcg_api with check (true);

create policy admin_access on tcg.pricing_policies
    for all to postgres using (true) with check (true);
create policy own_records on tcg.pricing_policies
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

create policy admin_access on tcg.pricing_snapshots
    for all to postgres using (true) with check (true);
create policy own_records on tcg.pricing_snapshots
    for select to tcg_api
    using (owner_id in (select id from tcg.owners));
create policy own_insert on tcg.pricing_snapshots
    for insert to tcg_api
    with check (owner_id in (select id from tcg.owners));

grant select, insert, update on tcg.market_source_mappings to tcg_api;
grant select, insert on tcg.market_observations to tcg_api;
grant select, insert, update on tcg.pricing_policies to tcg_api;
grant select, insert on tcg.pricing_snapshots to tcg_api;
revoke delete on tcg.market_source_mappings, tcg.market_observations, tcg.pricing_policies, tcg.pricing_snapshots from tcg_api;
revoke update on tcg.market_observations, tcg.pricing_snapshots from tcg_api;

create or replace function tcg.audit_market_change()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog
as $$
begin
    insert into tcg.audit_events(
        actor, request_id, action, entity_type, entity_id, old_values, new_values
    ) values (
        coalesce(nullif(current_setting('tcg.user_id', true), ''), session_user::text),
        nullif(current_setting('tcg.request_id', true), ''),
        tg_op,
        tg_table_name,
        case when tg_op = 'DELETE' then old.id else new.id end,
        case when tg_op = 'INSERT' then null else to_jsonb(old) end,
        case when tg_op = 'DELETE' then null else to_jsonb(new) end
    );
    return null;
end;
$$;
revoke all on function tcg.audit_market_change() from public;

create or replace function tcg.prevent_market_history_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    raise exception '% is immutable; append a new observation/snapshot instead', tg_table_name
        using errcode = '55000';
end;
$$;
revoke all on function tcg.prevent_market_history_mutation() from public;
grant execute on function tcg.prevent_market_history_mutation() to tcg_api;

create trigger market_source_mappings_audit
    after insert or update or delete on tcg.market_source_mappings
    for each row execute function tcg.audit_market_change();
create trigger market_observations_audit
    after insert or update or delete on tcg.market_observations
    for each row execute function tcg.audit_market_change();
create trigger pricing_policies_audit
    after insert or update or delete on tcg.pricing_policies
    for each row execute function tcg.audit_market_change();
create trigger pricing_snapshots_audit
    after insert or update or delete on tcg.pricing_snapshots
    for each row execute function tcg.audit_market_change();

create trigger market_observations_immutable
    before update or delete on tcg.market_observations
    for each row execute function tcg.prevent_market_history_mutation();
create trigger pricing_snapshots_immutable
    before update or delete on tcg.pricing_snapshots
    for each row execute function tcg.prevent_market_history_mutation();

commit;
