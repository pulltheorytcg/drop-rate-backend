-- Sellable listing, pooled ownership and reservation foundation.
-- The customer-facing listing is separated from exact physical Inventory IDs.

alter table tcg.inventory_items
  drop constraint if exists inventory_items_status_check;

alter table tcg.inventory_items
  add constraint inventory_items_status_check
  check (status = any (array[
    'DRAFT'::text,
    'INSPECTION'::text,
    'APPROVED'::text,
    'RESERVED'::text,
    'SOLD'::text,
    'WITHDRAWN'::text
  ]));

create table if not exists tcg.sellable_listings (
  id uuid primary key default gen_random_uuid(),
  listing_code text not null unique,
  catalogue_id uuid not null references tcg.catalogue_products(id),
  managed_by_owner_id uuid not null references tcg.owners(id),
  created_by_user_id uuid not null,
  listing_fingerprint text not null unique
    check (char_length(listing_fingerprint) = 64),
  product_type text not null
    check (product_type in ('CARD','SEALED','COLLECTION')),
  pooling_mode text not null
    check (pooling_mode in ('POOLED','UNIQUE')),
  language text,
  condition text,
  grading_company text,
  grade text,
  seal_status text,
  currency text not null default 'GBP'
    check (currency = 'GBP'),
  store_price_minor bigint not null
    check (store_price_minor >= 0),
  status text not null default 'ACTIVE'
    check (status in ('DRAFT','ACTIVE','PAUSED','ARCHIVED')),
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint sellable_listings_grade_pair_check
    check ((grading_company is null) = (grade is null)),
  constraint sellable_listings_pooling_shape_check
    check (
      pooling_mode <> 'POOLED'
      or (
        product_type = 'CARD'
        and grading_company is null
        and grade is null
        and seal_status is null
        and nullif(btrim(condition), '') is not null
        and nullif(btrim(language), '') is not null
      )
    )
);

create index if not exists sellable_listings_catalogue_status_idx
  on tcg.sellable_listings(catalogue_id,status);
create index if not exists sellable_listings_manager_status_idx
  on tcg.sellable_listings(managed_by_owner_id,status);

create table if not exists tcg.listing_inventory_members (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references tcg.sellable_listings(id),
  inventory_id uuid not null references tcg.inventory_items(id),
  owner_id uuid not null references tcg.owners(id),
  owner_context_user_id uuid not null,
  minimum_sale_price_minor bigint not null
    check (minimum_sale_price_minor >= 0),
  allocation_priority integer not null default 100
    check (allocation_priority > 0),
  state text not null default 'ACTIVE'
    check (state in ('ACTIVE','PAUSED','REMOVED')),
  eligible_since timestamptz not null default clock_timestamp(),
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  unique(listing_id,inventory_id)
);

create unique index if not exists listing_inventory_members_one_live_membership_idx
  on tcg.listing_inventory_members(inventory_id)
  where state <> 'REMOVED';
create index if not exists listing_inventory_members_listing_state_idx
  on tcg.listing_inventory_members(
    listing_id,state,allocation_priority,eligible_since,inventory_id
  );
create index if not exists listing_inventory_members_owner_state_idx
  on tcg.listing_inventory_members(owner_id,state);

create table if not exists tcg.inventory_reservations (
  id uuid primary key default gen_random_uuid(),
  reservation_code text not null unique,
  listing_id uuid not null references tcg.sellable_listings(id),
  inventory_id uuid not null references tcg.inventory_items(id),
  owner_id uuid not null references tcg.owners(id),
  owner_context_user_id uuid not null,
  source text not null
    check (source in ('SHOPIFY','MANUAL','TEST','SYSTEM')),
  source_reference text not null,
  source_line_reference text not null default '',
  allocation_index integer not null check (allocation_index > 0),
  status text not null default 'ACTIVE'
    check (status in ('ACTIVE','RELEASED','CONSUMED','EXPIRED')),
  sale_price_minor_snapshot bigint not null
    check (sale_price_minor_snapshot >= 0),
  acquisition_cost_minor_snapshot bigint not null
    check (acquisition_cost_minor_snapshot >= 0),
  minimum_sale_price_minor_snapshot bigint not null
    check (minimum_sale_price_minor_snapshot >= 0),
  allocation_priority_snapshot integer not null
    check (allocation_priority_snapshot > 0),
  inventory_version_snapshot integer not null
    check (inventory_version_snapshot > 0),
  reserved_at timestamptz not null default clock_timestamp(),
  expires_at timestamptz,
  released_at timestamptz,
  consumed_at timestamptz,
  notes text not null default '',
  created_at timestamptz not null default clock_timestamp(),
  unique(source,source_reference,source_line_reference,allocation_index),
  constraint inventory_reservations_state_time_check
    check (
      (status = 'ACTIVE' and released_at is null and consumed_at is null)
      or (status in ('RELEASED','EXPIRED') and released_at is not null and consumed_at is null)
      or (status = 'CONSUMED' and released_at is null and consumed_at is not null)
    )
);

create unique index if not exists inventory_reservations_one_active_per_item_idx
  on tcg.inventory_reservations(inventory_id)
  where status='ACTIVE';
create index if not exists inventory_reservations_listing_status_idx
  on tcg.inventory_reservations(listing_id,status,reserved_at);
create index if not exists inventory_reservations_owner_status_idx
  on tcg.inventory_reservations(owner_id,status,reserved_at);
create index if not exists inventory_reservations_source_idx
  on tcg.inventory_reservations(source,source_reference,source_line_reference);

alter table tcg.sellable_listings enable row level security;
alter table tcg.sellable_listings force row level security;
alter table tcg.listing_inventory_members enable row level security;
alter table tcg.listing_inventory_members force row level security;
alter table tcg.inventory_reservations enable row level security;
alter table tcg.inventory_reservations force row level security;

revoke all on table tcg.sellable_listings from public;
revoke all on table tcg.sellable_listings from anon, authenticated;
revoke all on table tcg.listing_inventory_members from public;
revoke all on table tcg.listing_inventory_members from anon, authenticated;
revoke all on table tcg.inventory_reservations from public;
revoke all on table tcg.inventory_reservations from anon, authenticated;

grant select,insert,update on table tcg.sellable_listings to tcg_api;
grant select,insert,update on table tcg.listing_inventory_members to tcg_api;
grant select,insert,update on table tcg.inventory_reservations to tcg_api;

drop policy if exists listing_internal_read on tcg.sellable_listings;
create policy listing_internal_read
  on tcg.sellable_listings for select to tcg_api
  using (true);

drop policy if exists listing_manager_insert on tcg.sellable_listings;
create policy listing_manager_insert
  on tcg.sellable_listings for insert to tcg_api
  with check (
    managed_by_owner_id in (select id from tcg.owners)
    and created_by_user_id = tcg.current_user_id()
  );

drop policy if exists listing_manager_update on tcg.sellable_listings;
create policy listing_manager_update
  on tcg.sellable_listings for update to tcg_api
  using (managed_by_owner_id in (select id from tcg.owners))
  with check (managed_by_owner_id in (select id from tcg.owners));

drop policy if exists listing_member_internal_read on tcg.listing_inventory_members;
create policy listing_member_internal_read
  on tcg.listing_inventory_members for select to tcg_api
  using (true);

drop policy if exists listing_member_owner_insert on tcg.listing_inventory_members;
create policy listing_member_owner_insert
  on tcg.listing_inventory_members for insert to tcg_api
  with check (
    owner_id in (select id from tcg.owners)
    and owner_context_user_id = tcg.current_user_id()
  );

drop policy if exists listing_member_owner_update on tcg.listing_inventory_members;
create policy listing_member_owner_update
  on tcg.listing_inventory_members for update to tcg_api
  using (owner_id in (select id from tcg.owners))
  with check (owner_id in (select id from tcg.owners));

drop policy if exists reservation_internal_read on tcg.inventory_reservations;
create policy reservation_internal_read
  on tcg.inventory_reservations for select to tcg_api
  using (true);

drop policy if exists reservation_owner_insert on tcg.inventory_reservations;
create policy reservation_owner_insert
  on tcg.inventory_reservations for insert to tcg_api
  with check (
    owner_id in (select id from tcg.owners)
    and owner_context_user_id = tcg.current_user_id()
  );

drop policy if exists reservation_owner_update on tcg.inventory_reservations;
create policy reservation_owner_update
  on tcg.inventory_reservations for update to tcg_api
  using (owner_id in (select id from tcg.owners))
  with check (owner_id in (select id from tcg.owners));

create or replace function tcg.protect_reserved_inventory()
returns trigger
language plpgsql
set search_path to 'pg_catalog'
as $function$
begin
  if old.status = 'RESERVED' then
    if current_setting('tcg.allow_reserved_transition', true) = 'on'
       and new.status in ('APPROVED','SOLD')
       and new.version = old.version + 1
       and (to_jsonb(new) - 'status' - 'version' - 'updated_at')
           = (to_jsonb(old) - 'status' - 'version' - 'updated_at') then
      return new;
    end if;
    raise exception 'Reserved inventory is immutable; use the reservation workflow'
      using errcode = '55000';
  end if;

  if new.status = 'RESERVED' and old.status <> 'RESERVED' then
    if current_setting('tcg.allow_reserved_transition', true) = 'on'
       and old.status = 'APPROVED'
       and new.version = old.version + 1
       and (to_jsonb(new) - 'status' - 'version' - 'updated_at')
           = (to_jsonb(old) - 'status' - 'version' - 'updated_at') then
      return new;
    end if;
    raise exception 'Inventory can only be reserved through the reservation workflow'
      using errcode = '55000';
  end if;

  return new;
end;
$function$;

drop trigger if exists inventory_reserved_guard on tcg.inventory_items;
create trigger inventory_reserved_guard
before update on tcg.inventory_items
for each row execute function tcg.protect_reserved_inventory();

drop trigger if exists sellable_listings_audit on tcg.sellable_listings;
create trigger sellable_listings_audit
after insert or update or delete on tcg.sellable_listings
for each row execute function tcg.audit_change();

drop trigger if exists listing_inventory_members_audit on tcg.listing_inventory_members;
create trigger listing_inventory_members_audit
after insert or update or delete on tcg.listing_inventory_members
for each row execute function tcg.audit_change();

drop trigger if exists inventory_reservations_audit on tcg.inventory_reservations;
create trigger inventory_reservations_audit
after insert or update or delete on tcg.inventory_reservations
for each row execute function tcg.audit_change();
