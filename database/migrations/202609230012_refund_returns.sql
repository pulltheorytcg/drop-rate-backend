begin;

create table tcg.refund_events (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    order_id uuid not null references tcg.orders(id),
    order_item_id uuid not null references tcg.order_items(id),
    inventory_id uuid not null references tcg.inventory_items(id),
    source_reference text not null,
    amount_minor bigint not null check (amount_minor > 0),
    currency text not null default 'GBP' check (currency = 'GBP'),
    return_to_stock boolean not null default false,
    reason text not null default '',
    occurred_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    unique (order_item_id, source_reference)
);

create index refund_events_owner_time_idx
    on tcg.refund_events(owner_id, occurred_at desc);
create index refund_events_order_idx
    on tcg.refund_events(order_id, order_item_id, occurred_at desc);
create index refund_events_inventory_idx
    on tcg.refund_events(inventory_id, occurred_at desc);

alter table tcg.refund_events enable row level security;

create policy admin_access on tcg.refund_events
    for all to postgres using (true) with check (true);
create policy own_records on tcg.refund_events
    for select to tcg_api
    using (owner_id in (select id from tcg.owners));
create policy own_insert on tcg.refund_events
    for insert to tcg_api
    with check (owner_id in (select id from tcg.owners));

grant select, insert on tcg.refund_events to tcg_api;
revoke update, delete on tcg.refund_events from tcg_api;

create trigger refund_events_audit
    after insert or update or delete on tcg.refund_events
    for each row execute function tcg.audit_finance_change();
create trigger refund_events_immutable
    before update or delete on tcg.refund_events
    for each row execute function tcg.prevent_finance_mutation();

create or replace function tcg.protect_sold_inventory()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    if old.status = 'SOLD' then
        if current_setting('tcg.allow_sold_return', true) = 'on'
           and new.status = 'INSPECTION'
           and new.version = old.version + 1
           and (to_jsonb(new) - 'status' - 'version' - 'updated_at')
               = (to_jsonb(old) - 'status' - 'version' - 'updated_at') then
            return new;
        end if;
        raise exception 'Sold inventory is immutable; use the refund/return workflow'
            using errcode = '55000';
    end if;
    return new;
end;
$$;
revoke all on function tcg.protect_sold_inventory() from public;
grant execute on function tcg.protect_sold_inventory() to tcg_api;

commit;
