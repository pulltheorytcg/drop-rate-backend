-- Shopify physical-inventory linkage for deterministic sale allocation.
-- Production schema is applied through Supabase before this migration is committed.

create table if not exists tcg.shopify_inventory_links (
  id uuid primary key default gen_random_uuid(),
  inventory_id uuid not null unique references tcg.inventory_items(id),
  owner_id uuid not null references tcg.owners(id),
  created_by_user_id uuid not null,
  listing_key text not null,
  allocation_priority integer not null check (allocation_priority > 0),
  shop_domain text not null,
  shopify_product_gid text not null,
  shopify_variant_gid text not null,
  shopify_inventory_item_gid text not null,
  shopify_location_gid text not null,
  shopify_publication_gid text,
  sku text not null,
  sync_state text not null default 'DRAFT'
    check (sync_state in ('DRAFT','PUBLISHED','SOLD','ARCHIVED','ERROR')),
  test_mode boolean not null default true,
  synced_price_minor bigint not null check (synced_price_minor >= 0),
  linked_at timestamptz not null default clock_timestamp(),
  last_synced_at timestamptz not null default clock_timestamp(),
  sold_at timestamptz,
  version integer not null default 1 check (version > 0),
  unique(listing_key, allocation_priority)
);

create index if not exists shopify_inventory_links_variant_state_idx
  on tcg.shopify_inventory_links(shopify_variant_gid, sync_state, allocation_priority);
create index if not exists shopify_inventory_links_owner_state_idx
  on tcg.shopify_inventory_links(owner_id, sync_state);

alter table tcg.shopify_inventory_links enable row level security;
alter table tcg.shopify_inventory_links force row level security;

revoke all on table tcg.shopify_inventory_links from public;
revoke all on table tcg.shopify_inventory_links from anon, authenticated;
grant select, insert, update on table tcg.shopify_inventory_links to tcg_api;

drop policy if exists internal_link_lookup on tcg.shopify_inventory_links;
create policy internal_link_lookup
  on tcg.shopify_inventory_links for select to tcg_api using (true);

drop policy if exists own_link_insert on tcg.shopify_inventory_links;
create policy own_link_insert
  on tcg.shopify_inventory_links for insert to tcg_api
  with check (owner_id in (select id from tcg.owners));

drop policy if exists own_link_update on tcg.shopify_inventory_links;
create policy own_link_update
  on tcg.shopify_inventory_links for update to tcg_api
  using (owner_id in (select id from tcg.owners))
  with check (owner_id in (select id from tcg.owners));

create table if not exists tcg.shopify_order_item_links (
  id uuid primary key default gen_random_uuid(),
  order_item_id uuid not null unique references tcg.order_items(id),
  owner_id uuid not null references tcg.owners(id),
  created_by_user_id uuid not null,
  shopify_order_id text not null,
  shopify_line_item_id text not null,
  shopify_variant_gid text not null,
  allocation_index integer not null check (allocation_index > 0),
  created_at timestamptz not null default clock_timestamp(),
  unique(shopify_order_id, shopify_line_item_id, allocation_index)
);

create index if not exists shopify_order_item_links_order_line_idx
  on tcg.shopify_order_item_links(shopify_order_id, shopify_line_item_id);
create index if not exists shopify_order_item_links_owner_idx
  on tcg.shopify_order_item_links(owner_id);

alter table tcg.shopify_order_item_links enable row level security;
alter table tcg.shopify_order_item_links force row level security;

revoke all on table tcg.shopify_order_item_links from public;
revoke all on table tcg.shopify_order_item_links from anon, authenticated;
grant select, insert on table tcg.shopify_order_item_links to tcg_api;

drop policy if exists internal_order_link_lookup on tcg.shopify_order_item_links;
create policy internal_order_link_lookup
  on tcg.shopify_order_item_links for select to tcg_api using (true);

drop policy if exists own_order_link_insert on tcg.shopify_order_item_links;
create policy own_order_link_insert
  on tcg.shopify_order_item_links for insert to tcg_api
  with check (owner_id in (select id from tcg.owners));
