-- Shared catalogue display, not cross-owner physical-photo access or writes.
-- CANONICAL_CARD already has a shared SELECT policy in the media registry.
-- Extend ONLY approved, rights-verified canonical PRODUCT references to active
-- workspace members. Keep the existing owner-write policies unchanged.
create policy shared_canonical_product_images on tcg.media_assets
    for select to tcg_api
    using (
        scope = 'CANONICAL_PRODUCT'
        and inventory_id is null
        and catalogue_id is not null
        and media_kind = 'IMAGE'
        and approval_status = 'APPROVED'
        and rights_status = 'VERIFIED'
        and rights_tier = 'STOREFRONT_ALLOWED'
        and source_status = 'ACTIVE'
        and revoked_at is null
        and exists (
            select 1 from tcg.owner_memberships membership
            join tcg.owners owner_record on owner_record.id=membership.owner_id
            where membership.user_id=tcg.current_user_id()
              and membership.active and owner_record.active
        )
    );
