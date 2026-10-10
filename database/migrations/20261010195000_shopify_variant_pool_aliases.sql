-- Historical product/variant references remain routable after an approved pool
-- replaces duplicate Shopify storefront offers. An alias never creates stock.
begin;

create table if not exists tcg.shopify_variant_pool_aliases (
  legacy_variant_gid text primary key,
  legacy_product_gid text not null,
  legacy_sku text not null,
  inventory_id uuid not null references tcg.inventory_items(id) on delete restrict,
  owner_id uuid not null references tcg.owners(id) on delete restrict,
  created_by_user_id uuid not null,
  shop_domain text not null,
  pooled_variant_gid text not null,
  pooled_product_gid text not null,
  listing_key text not null,
  retired_at timestamptz not null default clock_timestamp(),
  created_at timestamptz not null default clock_timestamp(),
  constraint pool_alias_legacy_variant_format
    check (legacy_variant_gid ~ '^gid://shopify/ProductVariant/[0-9]+$'),
  constraint pool_alias_pooled_variant_format
    check (pooled_variant_gid ~ '^gid://shopify/ProductVariant/[0-9]+$'),
  constraint pool_alias_product_format
    check (legacy_product_gid ~ '^gid://shopify/Product/[0-9]+$'
           and pooled_product_gid ~ '^gid://shopify/Product/[0-9]+$'),
  -- The original pooled anchor can retain its Shopify variant ID while its
  -- SKU changes. It still needs an immutable original-SKU alias for pre-cutover orders.
  constraint pool_alias_pool_key
    check (listing_key like 'shopify-pool:%'),
  constraint pool_alias_nonempty_sku
    check (btrim(legacy_sku) <> ''),
  constraint pool_alias_unique_inventory
    unique(inventory_id,legacy_variant_gid)
);

create index if not exists shopify_variant_pool_alias_inventory_idx
  on tcg.shopify_variant_pool_aliases(inventory_id,owner_id);
create index if not exists shopify_variant_pool_alias_pooled_idx
  on tcg.shopify_variant_pool_aliases(pooled_variant_gid,listing_key);

alter table tcg.shopify_variant_pool_aliases enable row level security;

-- Webhooks look up legacy variants before an actor can be resolved, mirroring
-- the internal lookup-only policy of tcg.shopify_inventory_links. The tcg
-- schema is not exposed to PostgREST and anonymous users have no table grants.
drop policy if exists internal_shopify_variant_alias_lookup on tcg.shopify_variant_pool_aliases;
create policy internal_shopify_variant_alias_lookup
  on tcg.shopify_variant_pool_aliases for select to tcg_api using (true);

drop policy if exists admin_shopify_variant_alias_insert on tcg.shopify_variant_pool_aliases;
create policy admin_shopify_variant_alias_insert
  on tcg.shopify_variant_pool_aliases for insert to tcg_api
  with check (tcg.is_platform_admin());

revoke all on tcg.shopify_variant_pool_aliases from public,anon,authenticated,service_role,tcg_auditor;
grant select,insert on tcg.shopify_variant_pool_aliases to tcg_api;

comment on table tcg.shopify_variant_pool_aliases is
  'Immutable read-only history for delayed Shopify webhooks on pooled variants; not sellable stock';

commit;
