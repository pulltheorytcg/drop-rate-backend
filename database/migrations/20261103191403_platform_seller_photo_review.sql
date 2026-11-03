-- Extend the existing founder-reviewed consignment photograph workflow to the
-- supported physical product families. No role, membership, table grant,
-- inventory state, condition decision or publication permission is changed.
-- The existing roster-verified is_platform_admin() remains the authority.
-- Legacy comic policies/routes remain available and comic-only.
begin;

create policy platform_admin_submitted_seller_photo_read
on tcg.media_assets for select to tcg_api
using (
    (select tcg.is_platform_admin())
    and scope='INVENTORY_ITEM'
    and source_type='CONSIGNOR_UPLOAD'
    and rights_tier='FIRST_PARTY_CAPTURE'
    and source_provider='Drop Rate'
    and exists (
        select 1 from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.owners o on o.id=i.owner_id
        where i.id=media_assets.inventory_id
          and i.owner_id=media_assets.owner_id
          and o.owner_type='CONSIGNOR' and o.active
          and i.status in ('DRAFT','INSPECTION','APPROVED')
          and p.product_type in ('CARD','COMIC','SEALED','FIGURE','COLLECTION')
    )
);

create policy platform_admin_submitted_seller_photo_update
on tcg.media_assets for update to tcg_api
using (
    (select tcg.is_platform_admin())
    and scope='INVENTORY_ITEM'
    and source_type='CONSIGNOR_UPLOAD'
    and rights_tier='FIRST_PARTY_CAPTURE'
    and source_provider='Drop Rate'
    and exists (
        select 1 from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.owners o on o.id=i.owner_id
        where i.id=media_assets.inventory_id
          and i.owner_id=media_assets.owner_id
          and o.owner_type='CONSIGNOR' and o.active
          and i.status in ('DRAFT','INSPECTION','APPROVED')
          and p.product_type in ('CARD','COMIC','SEALED','FIGURE','COLLECTION')
    )
)
with check (
    (select tcg.is_platform_admin())
    and scope='INVENTORY_ITEM'
    and source_type='CONSIGNOR_UPLOAD'
    and rights_tier='FIRST_PARTY_CAPTURE'
    and source_provider='Drop Rate'
    and exists (
        select 1 from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.owners o on o.id=i.owner_id
        where i.id=media_assets.inventory_id
          and i.owner_id=media_assets.owner_id
          and o.owner_type='CONSIGNOR' and o.active
          and i.status in ('DRAFT','INSPECTION','APPROVED')
          and p.product_type in ('CARD','COMIC','SEALED','FIGURE','COLLECTION')
    )
);

-- media_asset_identity_immutable and media_assets_audit remain unchanged.
-- API review decisions additionally require PENDING/ACTIVE, optimistic version,
-- a matching capture fingerprint/context, an inspected READY image and rights.
commit;
