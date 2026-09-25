begin;

alter table tcg.shopify_shipping_profiles
    add column package_length_mm numeric(10,2),
    add column package_width_mm numeric(10,2),
    add column package_height_mm numeric(10,2),
    add column empty_package_weight_grams numeric(10,3),
    add column carrier text,
    add column service_name text,
    add constraint shopify_shipping_profiles_package_length_positive
        check (package_length_mm is null or package_length_mm > 0),
    add constraint shopify_shipping_profiles_package_width_positive
        check (package_width_mm is null or package_width_mm > 0),
    add constraint shopify_shipping_profiles_package_height_positive
        check (package_height_mm is null or package_height_mm > 0),
    add constraint shopify_shipping_profiles_empty_weight_positive
        check (
            empty_package_weight_grams is null
            or empty_package_weight_grams > 0
        ),
    add constraint shopify_shipping_profiles_carrier_not_blank
        check (carrier is null or btrim(carrier) <> ''),
    add constraint shopify_shipping_profiles_service_not_blank
        check (service_name is null or btrim(service_name) <> '');

create table tcg.fulfilment_cost_components (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null,
    shipping_profile_key text not null,
    component_key text not null,
    label text not null check (btrim(label) <> ''),
    quantity numeric(10,3) not null default 1 check (quantity > 0),
    native_unit_cost_minor bigint not null check (native_unit_cost_minor >= 0),
    native_currency text not null
        check (native_currency ~ '^[A-Z]{3}$'),
    accounting_unit_cost_minor_gbp bigint
        check (
            accounting_unit_cost_minor_gbp is null
            or accounting_unit_cost_minor_gbp >= 0
        ),
    active boolean not null default true,
    notes text not null default '',
    version integer not null default 1 check (version >= 1),
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(owner_id, shipping_profile_key, component_key),
    foreign key (owner_id, shipping_profile_key)
        references tcg.shopify_shipping_profiles(owner_id, profile_key)
        on delete restrict,
    check (component_key ~ '^[A-Z][A-Z0-9_]{1,63}$'),
    check (
        native_currency <> 'GBP'
        or accounting_unit_cost_minor_gbp = native_unit_cost_minor
    )
);

create index fulfilment_cost_components_owner_active_idx
    on tcg.fulfilment_cost_components(
        owner_id,
        shipping_profile_key,
        active,
        component_key
    );

alter table tcg.fulfilment_cost_components enable row level security;

create policy admin_access on tcg.fulfilment_cost_components
    for all to postgres
    using (true)
    with check (true);

create policy own_records on tcg.fulfilment_cost_components
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

revoke all on tcg.fulfilment_cost_components from anon, authenticated;
grant select, insert, update on tcg.fulfilment_cost_components to tcg_api;
revoke delete on tcg.fulfilment_cost_components from tcg_api;

create function tcg.audit_fulfilment_cost_component_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $audit$
begin
    insert into tcg.audit_events(
        actor, request_id, action, entity_type, entity_id, old_values, new_values
    ) values (
        coalesce(
            nullif(pg_catalog.current_setting('tcg.user_id', true), ''),
            session_user::text
        ),
        nullif(pg_catalog.current_setting('tcg.request_id', true), ''),
        tg_op,
        tg_table_name,
        case when tg_op = 'DELETE' then old.id else new.id end,
        case when tg_op = 'INSERT' then null else pg_catalog.to_jsonb(old) end,
        case when tg_op = 'DELETE' then null else pg_catalog.to_jsonb(new) end
    );
    return null;
end;
$audit$;

revoke all on function tcg.audit_fulfilment_cost_component_change() from public;

create trigger fulfilment_cost_components_audit
    after insert or update or delete on tcg.fulfilment_cost_components
    for each row execute function tcg.audit_fulfilment_cost_component_change();

create function tcg.guard_fulfilment_cost_component_identity()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if old.owner_id is distinct from new.owner_id then
        raise exception 'Fulfilment cost owner is immutable once created'
            using errcode = '23514';
    end if;
    if old.shipping_profile_key is distinct from new.shipping_profile_key then
        raise exception 'Fulfilment shipping profile is immutable once created'
            using errcode = '23514';
    end if;
    if old.component_key is distinct from new.component_key then
        raise exception 'Fulfilment component key is immutable once created'
            using errcode = '23514';
    end if;
    return new;
end;
$$;

revoke all on function tcg.guard_fulfilment_cost_component_identity() from public;

create trigger fulfilment_cost_component_identity_guard
    before update of owner_id, shipping_profile_key, component_key
    on tcg.fulfilment_cost_components
    for each row execute function tcg.guard_fulfilment_cost_component_identity();

commit;
