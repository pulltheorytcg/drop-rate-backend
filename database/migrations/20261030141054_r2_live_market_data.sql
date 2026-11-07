-- Independently version shared price inputs; source caches remain authoritative.
-- Never invalidate static card identities merely because a market quote changes.
create schema if not exists tcg_private;
grant usage on schema tcg_private to tcg_api;

create table tcg_private.live_catalogue_r2_market_publication (
  singleton boolean primary key default true check (singleton),
  generation bigint not null default 1 check (generation > 0),
  published_generation bigint,
  manifest jsonb,
  published_at timestamptz,
  check ((manifest is null) = (published_generation is null)),
  check (published_generation is null or published_generation <= generation)
);
insert into tcg_private.live_catalogue_r2_market_publication(singleton) values(true);
alter table tcg_private.live_catalogue_r2_market_publication enable row level security;
alter table tcg_private.live_catalogue_r2_market_publication force row level security;
create policy publication_admin on tcg_private.live_catalogue_r2_market_publication
  for all to postgres using(true) with check(true);
create policy publication_read on tcg_private.live_catalogue_r2_market_publication
  for select to tcg_api using(tcg.current_access_role() is not null);
create policy publication_write on tcg_private.live_catalogue_r2_market_publication
  for update to tcg_api using(tcg.is_platform_admin()) with check(tcg.is_platform_admin());
grant select on tcg_private.live_catalogue_r2_market_publication to tcg_api;
grant update(published_generation,manifest,published_at)
  on tcg_private.live_catalogue_r2_market_publication to tcg_api;
revoke all on tcg_private.live_catalogue_r2_market_publication from public,anon,authenticated;


create function tcg_private.invalidate_live_catalogue_r2_market()
returns trigger language plpgsql security definer set search_path=pg_catalog as $$
declare material_change boolean := false;
begin
  if TG_TABLE_SCHEMA <> 'tcg' or TG_TABLE_NAME not in
    ('reference_market_prices','reference_catalogue_prices',
     'reference_sealed_market_prices','reference_asking_prices') then
    raise exception 'Unexpected R2 market source';
  end if;
  if TG_OP = 'TRUNCATE' then
    material_change := true;
  elsif TG_OP = 'INSERT' then
    select exists(select 1 from new_rows) into material_change;
  elsif TG_OP = 'DELETE' then
    select exists(select 1 from old_rows) into material_change;
  elsif TG_OP = 'UPDATE' then
    select exists(
      (select * from old_rows except select * from new_rows)
      union all (select * from new_rows except select * from old_rows)
    ) into material_change;
  end if;
  if material_change then
    update tcg_private.live_catalogue_r2_market_publication
      set generation=generation+1 where singleton;
  end if;
  return null;
end;
$$;
revoke all on function tcg_private.invalidate_live_catalogue_r2_market()
  from public,anon,authenticated,tcg_api;

create trigger live_catalogue_r2_market_insert after insert on tcg.reference_market_prices
  referencing new table as new_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_update after update on tcg.reference_market_prices
  referencing old table as old_rows new table as new_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_delete after delete on tcg.reference_market_prices
  referencing old table as old_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_truncate after truncate on tcg.reference_market_prices

  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_insert after insert on tcg.reference_catalogue_prices
  referencing new table as new_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_update after update on tcg.reference_catalogue_prices
  referencing old table as old_rows new table as new_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_delete after delete on tcg.reference_catalogue_prices
  referencing old table as old_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_truncate after truncate on tcg.reference_catalogue_prices

  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_insert after insert on tcg.reference_sealed_market_prices
  referencing new table as new_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_update after update on tcg.reference_sealed_market_prices
  referencing old table as old_rows new table as new_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_delete after delete on tcg.reference_sealed_market_prices
  referencing old table as old_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_truncate after truncate on tcg.reference_sealed_market_prices

  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_insert after insert on tcg.reference_asking_prices
  referencing new table as new_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_update after update on tcg.reference_asking_prices
  referencing old table as old_rows new table as new_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_delete after delete on tcg.reference_asking_prices
  referencing old table as old_rows
  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();

create trigger live_catalogue_r2_market_truncate after truncate on tcg.reference_asking_prices

  for each statement execute function tcg_private.invalidate_live_catalogue_r2_market();
