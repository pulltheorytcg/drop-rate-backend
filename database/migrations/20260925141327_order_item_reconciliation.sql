-- Track whether Shopify-derived fees and actual postage costs have been
-- reconciled for each financial order item. This is metadata, not a replacement
-- for the append-only financial ledger.

create table tcg.order_item_reconciliations (
    order_item_id uuid primary key references tcg.order_items(id),
    order_id uuid not null references tcg.orders(id),
    owner_id uuid not null references tcg.owners(id),
    fees_reconciled_at timestamptz,
    fees_source text,
    shipping_cost_reconciled_at timestamptz,
    shipping_cost_source text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    version integer not null default 1 check (version >= 1),
    check (
        (fees_reconciled_at is null and fees_source is null)
        or
        (fees_reconciled_at is not null and nullif(btrim(fees_source), '') is not null)
    ),
    check (
        (shipping_cost_reconciled_at is null and shipping_cost_source is null)
        or
        (
            shipping_cost_reconciled_at is not null
            and nullif(btrim(shipping_cost_source), '') is not null
        )
    )
);

create index order_item_reconciliations_owner_idx
    on tcg.order_item_reconciliations(owner_id, updated_at desc);
create index order_item_reconciliations_order_idx
    on tcg.order_item_reconciliations(order_id);

alter table tcg.order_item_reconciliations enable row level security;

create policy admin_access on tcg.order_item_reconciliations
    for all to postgres using (true) with check (true);

create policy own_records on tcg.order_item_reconciliations
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

grant select, insert, update on tcg.order_item_reconciliations to tcg_api;
revoke delete on tcg.order_item_reconciliations from tcg_api;

create trigger order_item_reconciliations_audit
    after insert or update or delete on tcg.order_item_reconciliations
    for each row execute function tcg.audit_finance_change();
