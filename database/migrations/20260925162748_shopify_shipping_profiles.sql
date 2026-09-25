begin;

create table tcg.shopify_shipping_profiles (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    profile_key text not null,
    label text not null check (btrim(label) <> ''),
    weight_value numeric(10,3) not null check (weight_value > 0),
    weight_unit text not null
        check (weight_unit in ('GRAMS','KILOGRAMS','OUNCES','POUNDS')),
    shipping_package_gid text,
    active boolean not null default true,
    notes text not null default '',
    version integer not null default 1 check (version >= 1),
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(owner_id, profile_key),
    check (profile_key ~ '^[A-Z][A-Z0-9_]{1,63}$'),
    check (
      shipping_package_gid is null
      or shipping_package_gid ~ '^gid://shopify/Package/[0-9]+$'
    )
);

create index shopify_shipping_profiles_owner_active_idx
    on tcg.shopify_shipping_profiles(owner_id, active, profile_key);

alter table tcg.shopify_shipping_profiles enable row level security;

create policy admin_access on tcg.shopify_shipping_profiles
    for all to postgres
    using (true)
    with check (true);

create policy own_records on tcg.shopify_shipping_profiles
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

revoke all on tcg.shopify_shipping_profiles from anon, authenticated;
grant select, insert, update on tcg.shopify_shipping_profiles to tcg_api;
revoke delete on tcg.shopify_shipping_profiles from tcg_api;

create trigger shopify_shipping_profiles_audit
    after insert or update or delete on tcg.shopify_shipping_profiles
    for each row execute function tcg.audit_change();

create function tcg.guard_shopify_shipping_profile_identity()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if old.owner_id is distinct from new.owner_id then
        raise exception 'Shipping profile owner is immutable once created'
            using errcode = '23514';
    end if;
    if old.profile_key is distinct from new.profile_key then
        raise exception 'Shipping profile key is immutable once created'
            using errcode = '23514';
    end if;
    return new;
end;
$$;

revoke all on function tcg.guard_shopify_shipping_profile_identity() from public;

create trigger shopify_shipping_profile_identity_guard
    before update of owner_id, profile_key on tcg.shopify_shipping_profiles
    for each row execute function tcg.guard_shopify_shipping_profile_identity();

commit;
