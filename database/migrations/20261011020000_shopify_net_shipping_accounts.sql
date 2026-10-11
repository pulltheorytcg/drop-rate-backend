-- Drop Rate company-controlled checkout postage and owner net-charge accounting.
-- Never amend older owner shipping ledgers in this migration.
begin;

create table tcg.shopify_delivery_accounts (
    order_id uuid primary key references tcg.orders(id) on delete restrict,
    shopify_order_reference text not null unique,
    customer_shipping_paid_minor bigint not null check (customer_shipping_paid_minor >= 0),
    qualifying_merchandise_minor bigint not null check (qualifying_merchandise_minor >= 0),
    delivery_service text not null check (length(btrim(delivery_service)) > 0),
    destination_country text not null check (destination_country ~ '^[A-Z]{2}$'),
    evidence_status text not null check (evidence_status in (
        'VERIFIED_SHIPPING_LINES', 'NEEDS_REVIEW'
    )),
    charge_policy text not null check (charge_policy in (
        'COMPANY_FUNDED_CUSTOMER_PAID',
        'AUTOMATIC_FREE_UK_TRACKED_48',
        'COMPANY_FUNDED_REVIEW'
    )),
    source_webhook_id text not null unique,
    created_at timestamptz not null default now(),
    check (
        charge_policy <> 'AUTOMATIC_FREE_UK_TRACKED_48'
        or (
            evidence_status='VERIFIED_SHIPPING_LINES'
            and customer_shipping_paid_minor=0
            and qualifying_merchandise_minor>=5000
            and destination_country='GB'
            and delivery_service='Royal Mail Tracked 48'
        )
    ),
    check (
        charge_policy <> 'COMPANY_FUNDED_CUSTOMER_PAID'
        or customer_shipping_paid_minor>0
    )
);

create table tcg.shopify_delivery_refunds (
    id uuid primary key default gen_random_uuid(),
    order_id uuid not null references tcg.shopify_delivery_accounts(order_id) on delete restrict,
    shopify_refund_id text not null unique check (btrim(shopify_refund_id) <> ''),
    amount_minor bigint not null check (amount_minor > 0),
    created_at timestamptz not null default now()
);

create table tcg.shopify_postage_actual_costs (
    id uuid primary key default gen_random_uuid(),
    order_id uuid not null references tcg.shopify_delivery_accounts(order_id) on delete restrict,
    owner_id uuid not null references tcg.owners(id) on delete restrict,
    carrier_label_reference text not null unique
        check (length(btrim(carrier_label_reference)) between 3 and 160),
    verified_postage_minor bigint not null check (verified_postage_minor >= 0),
    owner_net_charge_minor bigint not null check (
        owner_net_charge_minor >= 0
        and owner_net_charge_minor <= verified_postage_minor
    ),
    source_kind text not null default 'FOUNDER_VERIFIED_CARRIER_RECORD'
        check (source_kind in (
            'FOUNDER_VERIFIED_CARRIER_RECORD', 'VERIFIED_SHOPIFY_LABEL_RECEIPT'
        )),
    created_at timestamptz not null default now(),
    unique (order_id, owner_id)
);

create index shopify_delivery_refunds_order_idx
    on tcg.shopify_delivery_refunds (order_id, created_at);
create index shopify_postage_actual_costs_order_idx
    on tcg.shopify_postage_actual_costs (order_id, owner_id);

alter table tcg.shopify_delivery_accounts enable row level security;
alter table tcg.shopify_delivery_refunds enable row level security;
alter table tcg.shopify_postage_actual_costs enable row level security;
create policy admin_pg on tcg.shopify_delivery_accounts
    for all to postgres using (true) with check (true);
create policy admin_pg on tcg.shopify_delivery_refunds
    for all to postgres using (true) with check (true);
create policy admin_pg on tcg.shopify_postage_actual_costs
    for all to postgres using (true) with check (true);
create policy platform_read on tcg.shopify_delivery_accounts
    for select to tcg_api using (tcg.is_platform_admin());
create policy platform_insert on tcg.shopify_delivery_accounts
    for insert to tcg_api with check (tcg.is_platform_admin());
create policy platform_read on tcg.shopify_delivery_refunds
    for select to tcg_api using (tcg.is_platform_admin());
create policy platform_insert on tcg.shopify_delivery_refunds
    for insert to tcg_api with check (tcg.is_platform_admin());
create policy platform_read on tcg.shopify_postage_actual_costs
    for select to tcg_api using (tcg.is_platform_admin());
create policy platform_insert on tcg.shopify_postage_actual_costs
    for insert to tcg_api with check (tcg.is_platform_admin());

revoke all on tcg.shopify_delivery_accounts from public, anon, authenticated;
revoke all on tcg.shopify_delivery_refunds from public, anon, authenticated;
revoke all on tcg.shopify_postage_actual_costs from public, anon, authenticated;
grant select, insert on tcg.shopify_delivery_accounts to tcg_api;
grant select, insert on tcg.shopify_delivery_refunds to tcg_api;
grant select, insert on tcg.shopify_postage_actual_costs to tcg_api;

create trigger shopify_delivery_accounts_audit
    after insert on tcg.shopify_delivery_accounts
    for each row execute function tcg.audit_finance_change();
create trigger shopify_delivery_refunds_audit
    after insert on tcg.shopify_delivery_refunds
    for each row execute function tcg.audit_finance_change();
create trigger shopify_postage_actual_costs_audit
    after insert on tcg.shopify_postage_actual_costs
    for each row execute function tcg.audit_finance_change();

commit;
