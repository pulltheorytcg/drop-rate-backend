create table tcg.ebay_inventory_links (
    id uuid primary key default gen_random_uuid(),
    inventory_id uuid not null unique references tcg.inventory_items(id),
    owner_id uuid not null references tcg.owners(id),
    created_by_user_id uuid not null references auth.users(id),
    sku text not null unique check (btrim(sku) <> '' and length(sku) <= 50),
    marketplace_id text not null check (btrim(marketplace_id) <> ''),
    category_id text not null check (btrim(category_id) <> ''),
    offer_id text unique,
    listing_id text unique,
    state text not null default 'DRAFT'
        check (state in ('DRAFT','PUBLISHING','LIVE','WITHDRAWN','SOLD','ERROR')),
    listed_price_minor bigint not null check (listed_price_minor >= 100),
    currency text not null default 'GBP' check (currency='GBP'),
    markup_bps integer not null default 0 check (markup_bps between 0 and 10000),
    inventory_version_snapshot integer not null check (inventory_version_snapshot >= 1),
    withdrawal_reason text,
    last_error_code text,
    published_at timestamptz,
    withdrawn_at timestamptz,
    sold_at timestamptz,
    last_verified_at timestamptz,
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    check (offer_id is null or btrim(offer_id) <> ''),
    check (listing_id is null or btrim(listing_id) <> '')
);

create index ebay_inventory_links_owner_state_idx
    on tcg.ebay_inventory_links(owner_id,state,updated_at desc);
create index ebay_inventory_links_listing_idx
    on tcg.ebay_inventory_links(listing_id)
    where listing_id is not null;

alter table tcg.ebay_inventory_links enable row level security;
alter table tcg.ebay_inventory_links force row level security;

create policy ebay_inventory_links_postgres
    on tcg.ebay_inventory_links for all to postgres
    using (true) with check (true);
create policy ebay_inventory_links_api_read
    on tcg.ebay_inventory_links for select to tcg_api
    using (true);
create policy ebay_inventory_links_api_insert
    on tcg.ebay_inventory_links for insert to tcg_api
    with check (owner_id in (select id from tcg.owners));
create policy ebay_inventory_links_api_update
    on tcg.ebay_inventory_links for update to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

revoke all on table tcg.ebay_inventory_links from anon, authenticated;
grant select,insert,update on table tcg.ebay_inventory_links to tcg_api;
revoke delete on table tcg.ebay_inventory_links from tcg_api;

create or replace function tcg.guard_ebay_inventory_link_identity()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if old.inventory_id is distinct from new.inventory_id
       or old.owner_id is distinct from new.owner_id
       or old.sku is distinct from new.sku then
        raise exception 'eBay inventory link identity is immutable once created'
            using errcode='23514';
    end if;
    return new;
end;
$$;
revoke all on function tcg.guard_ebay_inventory_link_identity() from public;

create trigger ebay_inventory_link_identity_guard
    before update of inventory_id,owner_id,sku
    on tcg.ebay_inventory_links
    for each row execute function tcg.guard_ebay_inventory_link_identity();

create or replace function tcg.audit_ebay_inventory_link_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values(
        coalesce(nullif(pg_catalog.current_setting('tcg.user_id',true),''),session_user::text),
        nullif(pg_catalog.current_setting('tcg.request_id',true),''),
        tg_op,
        tg_table_name,
        case when tg_op='DELETE' then old.id else new.id end,
        case when tg_op='INSERT' then null else pg_catalog.to_jsonb(old) end,
        case when tg_op='DELETE' then null else pg_catalog.to_jsonb(new) end
    );
    return null;
end;
$$;
revoke all on function tcg.audit_ebay_inventory_link_change() from public;

create trigger ebay_inventory_links_audit
    after insert or update or delete on tcg.ebay_inventory_links
    for each row execute function tcg.audit_ebay_inventory_link_change();

create table tcg.ebay_order_item_links (
    id uuid primary key default gen_random_uuid(),
    order_id uuid not null references tcg.orders(id),
    order_item_id uuid not null unique references tcg.order_items(id),
    inventory_id uuid not null references tcg.inventory_items(id),
    owner_id uuid not null references tcg.owners(id),
    created_by_user_id uuid not null references auth.users(id),
    ebay_order_id text not null check (btrim(ebay_order_id) <> ''),
    ebay_line_item_id text not null check (btrim(ebay_line_item_id) <> ''),
    ebay_listing_id text not null check (btrim(ebay_listing_id) <> ''),
    created_at timestamptz not null default clock_timestamp(),
    unique(ebay_order_id,ebay_line_item_id)
);

create index ebay_order_item_links_owner_idx
    on tcg.ebay_order_item_links(owner_id,created_at desc);
create index ebay_order_item_links_order_idx
    on tcg.ebay_order_item_links(ebay_order_id);

alter table tcg.ebay_order_item_links enable row level security;
alter table tcg.ebay_order_item_links force row level security;

create policy ebay_order_item_links_postgres
    on tcg.ebay_order_item_links for all to postgres
    using (true) with check (true);
create policy ebay_order_item_links_api_read
    on tcg.ebay_order_item_links for select to tcg_api
    using (true);
create policy ebay_order_item_links_api_insert
    on tcg.ebay_order_item_links for insert to tcg_api
    with check (owner_id in (select id from tcg.owners));

revoke all on table tcg.ebay_order_item_links from anon, authenticated;
grant select,insert on table tcg.ebay_order_item_links to tcg_api;
revoke update,delete on table tcg.ebay_order_item_links from tcg_api;

create table tcg.ebay_webhook_events (
    notification_id text primary key check (btrim(notification_id) <> ''),
    topic text not null check (btrim(topic) <> ''),
    order_id text not null check (btrim(order_id) <> ''),
    payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
    status text not null default 'RECEIVED'
        check (status in ('RECEIVED','PROCESSED','FAILED')),
    last_error_code text,
    received_at timestamptz not null default clock_timestamp(),
    processed_at timestamptz
);

create index ebay_webhook_events_order_idx
    on tcg.ebay_webhook_events(order_id,received_at desc);
create index ebay_webhook_events_status_idx
    on tcg.ebay_webhook_events(status,received_at desc);

alter table tcg.ebay_webhook_events enable row level security;
alter table tcg.ebay_webhook_events force row level security;

create policy ebay_webhook_events_postgres
    on tcg.ebay_webhook_events for all to postgres
    using (true) with check (true);
create policy ebay_webhook_events_api_read
    on tcg.ebay_webhook_events for select to tcg_api
    using (true);
create policy ebay_webhook_events_api_insert
    on tcg.ebay_webhook_events for insert to tcg_api
    with check (true);
create policy ebay_webhook_events_api_update
    on tcg.ebay_webhook_events for update to tcg_api
    using (true) with check (true);

revoke all on table tcg.ebay_webhook_events from anon, authenticated;
grant select,insert,update on table tcg.ebay_webhook_events to tcg_api;
revoke delete on table tcg.ebay_webhook_events from tcg_api;

alter table tcg.orders drop constraint orders_source_check;
alter table tcg.orders
    add constraint orders_source_check
    check (source in ('MANUAL','SHOPIFY','EBAY'));
