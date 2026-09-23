begin;

alter table tcg.inventory_items
    drop constraint if exists inventory_items_status_check;
alter table tcg.inventory_items
    add constraint inventory_items_status_check
        check (status in ('DRAFT', 'INSPECTION', 'APPROVED', 'SOLD', 'WITHDRAWN'));

create table tcg.orders (
    id uuid primary key default gen_random_uuid(),
    source text not null check (source in ('MANUAL', 'SHOPIFY')),
    source_reference text not null,
    order_number text,
    currency text not null default 'GBP' check (currency = 'GBP'),
    status text not null default 'PAID'
        check (status in ('PAID', 'PARTIALLY_REFUNDED', 'REFUNDED', 'CANCELLED')),
    placed_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (source, source_reference)
);

create table tcg.order_items (
    id uuid primary key default gen_random_uuid(),
    order_id uuid not null references tcg.orders(id),
    inventory_id uuid not null references tcg.inventory_items(id),
    owner_id uuid not null references tcg.owners(id),
    sale_price_minor bigint not null check (sale_price_minor >= 0),
    discount_minor bigint not null default 0 check (discount_minor >= 0),
    net_sale_minor bigint generated always as (sale_price_minor - discount_minor) stored,
    cost_basis_minor bigint not null check (cost_basis_minor >= 0),
    sold_at timestamptz not null,
    created_at timestamptz not null default now(),
    check (discount_minor <= sale_price_minor),
    unique (order_id, inventory_id)
);

create table tcg.payout_requests (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    payout_code text not null,
    amount_minor bigint not null check (amount_minor > 0),
    currency text not null default 'GBP' check (currency = 'GBP'),
    status text not null default 'REQUESTED'
        check (status in ('REQUESTED', 'APPROVED', 'PAID', 'REJECTED', 'CANCELLED')),
    requested_at timestamptz not null default now(),
    resolved_at timestamptz,
    notes text not null default '',
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, payout_code)
);

create table tcg.financial_ledger_entries (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    order_id uuid references tcg.orders(id),
    order_item_id uuid references tcg.order_items(id),
    payout_request_id uuid references tcg.payout_requests(id),
    entry_type text not null check (entry_type in (
        'SALE_REVENUE',
        'SHIPPING_REVENUE',
        'PLATFORM_FEE',
        'PAYMENT_FEE',
        'SHIPPING_COST',
        'REFUND',
        'ADJUSTMENT',
        'PAYOUT'
    )),
    amount_minor bigint not null check (amount_minor <> 0),
    currency text not null default 'GBP' check (currency = 'GBP'),
    funds_status text not null default 'AVAILABLE'
        check (funds_status in ('PENDING', 'AVAILABLE')),
    source_key text not null unique,
    occurred_at timestamptz not null default now(),
    available_at timestamptz,
    notes text not null default '',
    created_at timestamptz not null default now()
);

create index order_items_owner_sold_idx
    on tcg.order_items(owner_id, sold_at desc);
create index order_items_inventory_idx
    on tcg.order_items(inventory_id, sold_at desc);
create index financial_ledger_owner_status_idx
    on tcg.financial_ledger_entries(owner_id, funds_status, occurred_at desc);
create index financial_ledger_order_idx
    on tcg.financial_ledger_entries(order_id, order_item_id);
create index payout_requests_owner_status_idx
    on tcg.payout_requests(owner_id, status, requested_at desc);

alter table tcg.orders enable row level security;
alter table tcg.order_items enable row level security;
alter table tcg.payout_requests enable row level security;
alter table tcg.financial_ledger_entries enable row level security;

create policy admin_access on tcg.orders
    for all to postgres using (true) with check (true);
create policy api_insert on tcg.orders
    for insert to tcg_api with check (true);
create policy own_records on tcg.orders
    for select to tcg_api
    using (exists (
        select 1 from tcg.order_items oi
        where oi.order_id = orders.id
          and oi.owner_id in (select id from tcg.owners)
    ));
create policy api_update on tcg.orders
    for update to tcg_api
    using (exists (
        select 1 from tcg.order_items oi
        where oi.order_id = orders.id
          and oi.owner_id in (select id from tcg.owners)
    ))
    with check (true);

create policy admin_access on tcg.order_items
    for all to postgres using (true) with check (true);
create policy own_records on tcg.order_items
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

create policy admin_access on tcg.payout_requests
    for all to postgres using (true) with check (true);
create policy own_records on tcg.payout_requests
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

create policy admin_access on tcg.financial_ledger_entries
    for all to postgres using (true) with check (true);
create policy own_records on tcg.financial_ledger_entries
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

grant select, insert, update on tcg.orders to tcg_api;
grant select, insert on tcg.order_items to tcg_api;
grant select, insert, update on tcg.payout_requests to tcg_api;
grant select, insert on tcg.financial_ledger_entries to tcg_api;
revoke delete on tcg.orders, tcg.order_items, tcg.payout_requests, tcg.financial_ledger_entries from tcg_api;
revoke update on tcg.order_items, tcg.financial_ledger_entries from tcg_api;

create or replace function tcg.audit_finance_change()
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
revoke all on function tcg.audit_finance_change() from public;

create or replace function tcg.prevent_finance_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    raise exception '% is immutable; append a compensating finance record instead', tg_table_name
        using errcode = '55000';
end;
$$;
revoke all on function tcg.prevent_finance_mutation() from public;
grant execute on function tcg.prevent_finance_mutation() to tcg_api;

create trigger orders_audit
    after insert or update or delete on tcg.orders
    for each row execute function tcg.audit_finance_change();
create trigger order_items_audit
    after insert or update or delete on tcg.order_items
    for each row execute function tcg.audit_finance_change();
create trigger payout_requests_audit
    after insert or update or delete on tcg.payout_requests
    for each row execute function tcg.audit_finance_change();
create trigger financial_ledger_audit
    after insert or update or delete on tcg.financial_ledger_entries
    for each row execute function tcg.audit_finance_change();

create trigger order_items_immutable
    before update or delete on tcg.order_items
    for each row execute function tcg.prevent_finance_mutation();
create trigger financial_ledger_immutable
    before update or delete on tcg.financial_ledger_entries
    for each row execute function tcg.prevent_finance_mutation();

commit;
