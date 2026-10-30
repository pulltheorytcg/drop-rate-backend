-- Shared catalogue content can be delivered from verified R2 objects. Keep the
-- source tables and all transactional data intact; this is a reversible cutover.
create schema if not exists tcg_private;
grant usage on schema tcg_private to tcg_api;

create table tcg_private.live_catalogue_r2_publication (
  singleton boolean primary key default true check (singleton),
  generation bigint not null default 1 check (generation > 0),
  published_generation bigint,
  manifest jsonb,
  published_at timestamptz,
  check ((manifest is null) = (published_generation is null)),
  check (published_generation is null or published_generation <= generation)
);
insert into tcg_private.live_catalogue_r2_publication(singleton) values(true);
alter table tcg_private.live_catalogue_r2_publication enable row level security;
alter table tcg_private.live_catalogue_r2_publication force row level security;
create policy publication_admin on tcg_private.live_catalogue_r2_publication
  for all to postgres using(true) with check(true);
create policy publication_read on tcg_private.live_catalogue_r2_publication
  for select to tcg_api using(tcg.current_access_role() is not null);
create policy publication_write on tcg_private.live_catalogue_r2_publication
  for update to tcg_api using(tcg.is_platform_admin()) with check(tcg.is_platform_admin());
grant select on tcg_private.live_catalogue_r2_publication to tcg_api;
grant update(published_generation,manifest,published_at)
  on tcg_private.live_catalogue_r2_publication to tcg_api;
revoke all on tcg_private.live_catalogue_r2_publication from public,anon,authenticated;

-- Trigger-only privilege: any already-authorized source write invalidates the
-- shared publication atomically, including writes by non-admin intake paths.
-- The caller cannot invoke this function or choose a relation/statement.
create function tcg_private.invalidate_live_catalogue_r2()
returns trigger language plpgsql security definer set search_path=pg_catalog as $$
begin
  update tcg_private.live_catalogue_r2_publication
    set generation=generation+1 where singleton;
  return null;
end;
$$;
revoke all on function tcg_private.invalidate_live_catalogue_r2() from public,anon,authenticated,tcg_api;

create trigger live_catalogue_r2_changed after insert or update or delete or truncate
  on tcg.reference_cards for each statement execute function tcg_private.invalidate_live_catalogue_r2();
create trigger live_catalogue_r2_changed after insert or update or delete or truncate
  on tcg.reference_sets for each statement execute function tcg_private.invalidate_live_catalogue_r2();
create trigger live_catalogue_r2_changed after insert or update or delete or truncate
  on tcg.reference_sealed_products for each statement execute function tcg_private.invalidate_live_catalogue_r2();
create trigger live_catalogue_r2_changed after insert or update or delete or truncate
  on tcg.catalogue_products for each statement execute function tcg_private.invalidate_live_catalogue_r2();
create trigger live_catalogue_r2_changed after insert or update or delete or truncate
  on tcg.catalogue_product_profiles for each statement execute function tcg_private.invalidate_live_catalogue_r2();
