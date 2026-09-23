begin;

create table tcg.storage_locations (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    code text not null,
    label text not null,
    location_type text not null
        check (location_type in ('BINDER', 'BOX', 'SHELF', 'DRAWER', 'VAULT', 'DISPLAY', 'OTHER')),
    active boolean not null default true,
    notes text not null default '',
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, code),
    check (code ~ '^[A-Z0-9]+(?:-[A-Z0-9]+)*(?:/[A-Z0-9]+(?:-[A-Z0-9]+)*)*$')
);

alter table tcg.inventory_items
    add column storage_location_id uuid references tcg.storage_locations(id);

create index storage_locations_owner_active_idx
    on tcg.storage_locations(owner_id, active, code);

create index inventory_storage_location_idx
    on tcg.inventory_items(storage_location_id)
    where storage_location_id is not null;

alter table tcg.storage_locations enable row level security;

create policy admin_access on tcg.storage_locations
    for all to postgres
    using (true)
    with check (true);

create policy own_records on tcg.storage_locations
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

grant select, insert, update, delete on tcg.storage_locations to tcg_api;

create function tcg.audit_storage_location_change()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, tcg
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

create trigger storage_locations_audit
    after insert or update or delete on tcg.storage_locations
    for each row execute function tcg.audit_storage_location_change();

create function tcg.guard_storage_location_code()
returns trigger
language plpgsql
set search_path = pg_catalog, tcg
as $$
begin
    if old.code is distinct from new.code then
        raise exception 'Storage location code is immutable once created'
            using errcode = '23514';
    end if;
    return new;
end;
$$;

create trigger storage_location_code_guard
    before update of code on tcg.storage_locations
    for each row execute function tcg.guard_storage_location_code();

create function tcg.sync_inventory_storage_location()
returns trigger
language plpgsql
set search_path = pg_catalog, tcg
as $$
declare
    location_code text;
begin
    if new.storage_location_id is null then
        new.location := null;
        return new;
    end if;

    select code into location_code
    from tcg.storage_locations
    where id = new.storage_location_id
      and owner_id = new.owner_id
      and active;

    if location_code is null then
        raise exception 'Storage location is missing, inactive, or belongs to another owner'
            using errcode = '23514';
    end if;

    new.location := location_code;
    return new;
end;
$$;

create trigger inventory_storage_location_sync
    before insert or update of storage_location_id on tcg.inventory_items
    for each row execute function tcg.sync_inventory_storage_location();

commit;
