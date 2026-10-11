-- Drop Rate company-controlled checkout postage and owner net-charge accounting.
-- Never amend older owner shipping ledgers in this migration.
begin;

create table tcg.shopify_delivery_accounts (
    id uuid primary key default gen_random_uuid(),
    order_id uuid not null unique references tcg.orders(id) on delete restrict,
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

-- The only account view permitted to a seller. SECURITY DEFINER reads the
-- private company accounting row but returns exactly ONE net owner charge.
-- It cannot return customer payments, postage invoices, other owner records,
-- addresses, or buyer identity.
create function tcg.owner_net_shopify_postage(p_order_item_id uuid)
returns table (
    charge_policy text,
    net_shipping_charge_minor bigint,
    policy_status text
)
language plpgsql
stable
security definer
set search_path = pg_catalog
as $body$
declare
    v_owner_id uuid;
    v_memberships integer;
    v_order_id uuid;
    v_order_policy text;
    v_all_reconciled boolean;
    v_owner_postage bigint;
begin
    select count(*)::int, (array_agg(m.owner_id))[1]
    into v_memberships,v_owner_id
    from tcg.owner_memberships m
    join tcg.owners own on own.id=m.owner_id
    where m.user_id=tcg.current_user_id() and m.active and own.active;

    if v_memberships<>1 then
        return;
    end if;

    select oi.order_id,a.charge_policy
    into v_order_id,v_order_policy
    from tcg.order_items oi
    join tcg.orders o on o.id=oi.order_id
    join tcg.shopify_delivery_accounts a on a.order_id=o.id
    where oi.id=p_order_item_id
      and oi.owner_id=v_owner_id
      and o.source='SHOPIFY'
      and o.status='PAID';
    if not found then
        return;
    end if;

    if v_order_policy in (
        'COMPANY_FUNDED_CUSTOMER_PAID',
        'COMPANY_FUNDED_REVIEW'
    ) then
        return query select v_order_policy,0::bigint,'NO_SELLER_CHARGE'::text;
        return;
    end if;

    if v_order_policy<>'AUTOMATIC_FREE_UK_TRACKED_48' then
        return;
    end if;

    select
        coalesce(bool_and(rec.shipping_cost_reconciled_at is not null),false),
        coalesce(-sum(le.amount_minor),0)::bigint
    into v_all_reconciled,v_owner_postage
    from tcg.order_items oi
    left join tcg.order_item_reconciliations rec
      on rec.order_item_id=oi.id and rec.owner_id=v_owner_id
    left join tcg.financial_ledger_entries le
      on le.order_item_id=oi.id
     and le.owner_id=v_owner_id
     and le.entry_type='SHIPPING_COST'
    where oi.order_id=v_order_id and oi.owner_id=v_owner_id;

    if v_all_reconciled then
        return query select
            v_order_policy,
            greatest(v_owner_postage,0)::bigint,
            'AUTO_CHARGE_VERIFIED'::text;
    else
        return query select
            v_order_policy,null::bigint,'AUTO_CHARGE_PENDING'::text;
    end if;
end
$body$;

revoke all on function tcg.owner_net_shopify_postage(uuid) from public, anon, authenticated;
grant execute on function tcg.owner_net_shopify_postage(uuid) to tcg_api;

-- Even privileged repairs require append-only adjustment records and audit.
create trigger shopify_delivery_account_immutable
    before update or delete on tcg.shopify_delivery_accounts
    for each row execute function tcg.prevent_finance_mutation();
create trigger shopify_delivery_refund_immutable
    before update or delete on tcg.shopify_delivery_refunds
    for each row execute function tcg.prevent_finance_mutation();
create trigger shopify_postage_actual_cost_immutable
    before update or delete on tcg.shopify_postage_actual_costs
    for each row execute function tcg.prevent_finance_mutation();

commit;
