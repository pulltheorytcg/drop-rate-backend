-- Allow verified platform administrators to inspect and decide *only* exact
-- physical photographs submitted by consignment comic owners. A consignor
-- retains their existing owner-scoped access; this is not a storefront grant.
-- The API additionally restricts decisions to PENDING assets and the verified
-- founder roster, and each update passes through the existing audit trigger.

create policy platform_admin_consignor_comic_photo_read
on tcg.media_assets for select to tcg_api
using (
    (select tcg.is_platform_admin())
    and scope='INVENTORY_ITEM'
    and source_type='CONSIGNOR_UPLOAD'
    and rights_tier='FIRST_PARTY_CAPTURE'
    and exists (
        select 1 from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.owners o on o.id=i.owner_id
        where i.id=media_assets.inventory_id
          and i.owner_id=media_assets.owner_id
          and o.owner_type='CONSIGNOR'
          and p.product_type='COMIC'
    )
);

create policy platform_admin_consignor_comic_photo_update
on tcg.media_assets for update to tcg_api
using (
    (select tcg.is_platform_admin())
    and scope='INVENTORY_ITEM'
    and source_type='CONSIGNOR_UPLOAD'
    and rights_tier='FIRST_PARTY_CAPTURE'
    and exists (
        select 1 from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.owners o on o.id=i.owner_id
        where i.id=media_assets.inventory_id
          and i.owner_id=media_assets.owner_id
          and o.owner_type='CONSIGNOR'
          and p.product_type='COMIC'
    )
)
with check (
    (select tcg.is_platform_admin())
    and scope='INVENTORY_ITEM'
    and source_type='CONSIGNOR_UPLOAD'
    and rights_tier='FIRST_PARTY_CAPTURE'
    and exists (
        select 1 from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.owners o on o.id=i.owner_id
        where i.id=media_assets.inventory_id
          and i.owner_id=media_assets.owner_id
          and o.owner_type='CONSIGNOR'
          and p.product_type='COMIC'
    )
);

-- A broader review role must never be able to move a media record onto a
-- different seller or printing. These columns are immutable for every media
-- record; a replacement photograph is a new audited asset, not reassignment.
create function tcg.prevent_media_asset_identity_reassignment()
returns trigger language plpgsql security invoker
set search_path to 'pg_catalog'
as $function$
begin
    if (old.owner_id,old.inventory_id,old.catalogue_id,old.scope,old.source_type,old.rights_tier)
       is distinct from
       (new.owner_id,new.inventory_id,new.catalogue_id,new.scope,new.source_type,new.rights_tier) then
        raise exception 'Media owner and physical identity cannot be reassigned';
    end if;
    return new;
end;
$function$;

revoke all on function tcg.prevent_media_asset_identity_reassignment() from public;
create trigger media_asset_identity_immutable
before update on tcg.media_assets
for each row execute function tcg.prevent_media_asset_identity_reassignment();
