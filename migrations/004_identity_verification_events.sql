-- Immutable physical-card identity verification evidence.
-- Production schema was applied via Supabase SQL before this migration was committed.
-- App access is owner-scoped, SELECT/INSERT only; no UPDATE/DELETE grants.

create table if not exists tcg.identity_verification_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references tcg.owners(id),
  inventory_id uuid not null references tcg.inventory_items(id),
  catalogue_id uuid not null references tcg.catalogue_products(id),
  event_type text not null check (event_type in ('CONFIRMED','REVOKED')),
  actor_user_id uuid not null,
  verification_method text not null check (
    verification_method in ('PHYSICAL_REVIEW','CORRECTION','SYSTEM_INVALIDATION')
  ),
  inventory_version integer not null check (inventory_version >= 1),
  catalogue_snapshot jsonb not null,
  physical_snapshot jsonb not null,
  notes text not null default '',
  created_at timestamptz not null default clock_timestamp()
);

create index if not exists identity_verification_events_owner_created_idx
  on tcg.identity_verification_events(owner_id, created_at desc);
create index if not exists identity_verification_events_inventory_created_idx
  on tcg.identity_verification_events(inventory_id, created_at desc);
create index if not exists identity_verification_events_catalogue_created_idx
  on tcg.identity_verification_events(catalogue_id, created_at desc);

alter table tcg.identity_verification_events enable row level security;
alter table tcg.identity_verification_events force row level security;

revoke all on table tcg.identity_verification_events from public;
revoke all on table tcg.identity_verification_events from anon, authenticated;
grant select, insert on table tcg.identity_verification_events to tcg_api;

drop policy if exists admin_access on tcg.identity_verification_events;
create policy admin_access
  on tcg.identity_verification_events
  for all
  to postgres
  using (true)
  with check (true);

drop policy if exists own_verification_read on tcg.identity_verification_events;
create policy own_verification_read
  on tcg.identity_verification_events
  for select
  to tcg_api
  using (owner_id in (select id from tcg.owners));

drop policy if exists own_verification_insert on tcg.identity_verification_events;
create policy own_verification_insert
  on tcg.identity_verification_events
  for insert
  to tcg_api
  with check (owner_id in (select id from tcg.owners));

create or replace function tcg.invalidate_identity_on_catalogue_change()
returns trigger
language plpgsql
set search_path = pg_catalog, tcg
as $$
begin
  if new.catalogue_id is distinct from old.catalogue_id then
    new.identity_confirmed := false;
  end if;
  return new;
end
$$;

drop trigger if exists inventory_identity_invalidation on tcg.inventory_items;
create trigger inventory_identity_invalidation
before update of catalogue_id on tcg.inventory_items
for each row execute function tcg.invalidate_identity_on_catalogue_change();
