begin;

create table tcg.purchase_lots (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    lot_code text not null,
    description text not null,
    source text,
    purchase_date date,
    purchase_price_minor bigint not null check (purchase_price_minor >= 0),
    fees_minor bigint not null default 0 check (fees_minor >= 0),
    shipping_minor bigint not null default 0 check (shipping_minor >= 0),
    total_cost_minor bigint generated always as
        (purchase_price_minor + fees_minor + shipping_minor) stored,
    currency text not null default 'GBP' check (char_length(currency) = 3),
    allocation_method text not null default 'MANUAL'
        check (allocation_method in ('MANUAL', 'EQUAL', 'VALUE_WEIGHTED')),
    notes text not null default '',
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, lot_code)
);

alter table tcg.inventory_items
    add column purchase_lot_id uuid references tcg.purchase_lots(id);

create index purchase_lots_owner_created_idx
    on tcg.purchase_lots(owner_id, created_at desc);

create index inventory_purchase_lot_idx
    on tcg.inventory_items(purchase_lot_id)
    where purchase_lot_id is not null;

alter table tcg.purchase_lots enable row level security;

create policy admin_access on tcg.purchase_lots
    for all to postgres
    using (true)
    with check (true);

create policy own_records on tcg.purchase_lots
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

grant select, insert, update, delete on tcg.purchase_lots to tcg_api;

create function tcg.audit_purchase_lot_change()
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
        TG_OP,
        TG_TABLE_NAME,
        case when TG_OP = 'DELETE' then OLD.id else NEW.id end,
        case when TG_OP = 'INSERT' then null else to_jsonb(OLD) end,
        case when TG_OP = 'DELETE' then null else to_jsonb(NEW) end
    );
    return null;
end;
$$;

revoke all on function tcg.audit_purchase_lot_change() from public;

create trigger purchase_lots_audit
    after insert or update or delete on tcg.purchase_lots
    for each row execute function tcg.audit_purchase_lot_change();

commit;
