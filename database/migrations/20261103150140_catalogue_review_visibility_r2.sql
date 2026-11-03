-- Keep shared catalogue snapshots consistent with reviewed Sports/Figures visibility.
-- Only public metadata status joins the existing immutable projection. No grants.
create or replace function tcg_private.invalidate_live_catalogue_r2()
returns trigger language plpgsql security definer set search_path=pg_catalog as $$
declare
  material_change boolean := false;
begin
  if TG_TABLE_SCHEMA <> 'tcg' then
    raise exception 'Unexpected R2 publication source';
  end if;
  if TG_OP = 'TRUNCATE' then
    material_change := true;
  elsif TG_OP = 'INSERT' then
    select exists(select 1 from new_rows) into material_change;
  elsif TG_OP = 'DELETE' then
    select exists(select 1 from old_rows) into material_change;
  elsif TG_OP = 'UPDATE' then
    if TG_TABLE_NAME = 'reference_cards' then
      select exists(
        select 1 from old_rows o full join new_rows n on o.provider = n.provider and o.system_code = n.system_code and o.language = n.language and o.provider_id = n.provider_id
        where row(o.provider,o.system_code,o.language,o.provider_id,o.set_id,o.name,o.card_number,o.rarity,o.image_url,o.source_url,o.number_key) is distinct from row(n.provider,n.system_code,n.language,n.provider_id,n.set_id,n.name,n.card_number,n.rarity,n.image_url,n.source_url,n.number_key)
      ) into material_change;
    elsif TG_TABLE_NAME = 'reference_sets' then
      select exists(
        select 1 from old_rows o full join new_rows n on o.provider = n.provider and o.system_code = n.system_code and o.language = n.language and o.set_id = n.set_id
        where row(o.provider,o.system_code,o.language,o.set_id,o.name,o.release_date,o.declared_card_count) is distinct from row(n.provider,n.system_code,n.language,n.set_id,n.name,n.release_date,n.declared_card_count)
      ) into material_change;
    elsif TG_TABLE_NAME = 'reference_sealed_products' then
      select exists(
        select 1 from old_rows o full join new_rows n on o.provider = n.provider and o.system_code = n.system_code and o.language = n.language and o.provider_id = n.provider_id
        where row(o.provider,o.system_code,o.language,o.provider_id,o.set_id,o.name,o.product_type,o.image_url,o.source_url) is distinct from row(n.provider,n.system_code,n.language,n.provider_id,n.set_id,n.name,n.product_type,n.image_url,n.source_url)
      ) into material_change;
    elsif TG_TABLE_NAME = 'catalogue_products' then
      select exists(
        select 1 from old_rows o full join new_rows n on o.id = n.id
        where row(o.id,o.product_type,o.game,o.name,o.set_name,o.card_number,o.variant,o.rarity,o.language) is distinct from row(n.id,n.product_type,n.game,n.name,n.set_name,n.card_number,n.variant,n.rarity,n.language)
      ) into material_change;
    elsif TG_TABLE_NAME = 'catalogue_product_profiles' then
      select exists(
        select 1 from old_rows o full join new_rows n on o.catalogue_id = n.catalogue_id
        where row(o.catalogue_id,o.system_code,o.collectible_type,o.set_code,o.release_date,o.identity_status) is distinct from row(n.catalogue_id,n.system_code,n.collectible_type,n.set_code,n.release_date,n.identity_status)
      ) into material_change;
    else
      raise exception 'Unexpected R2 publication source';
    end if;
  end if;
  if material_change then
    update tcg_private.live_catalogue_r2_publication
       set generation=generation+1 where singleton;
  end if;
  return null;
end;
$$;

revoke all on function tcg_private.invalidate_live_catalogue_r2()
  from public,anon,authenticated,tcg_api;

-- The v2 projection includes review state and excludes unreviewed manual identities.
update tcg_private.live_catalogue_r2_publication set generation=generation+1 where singleton;
