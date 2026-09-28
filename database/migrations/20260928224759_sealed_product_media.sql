begin;

alter table tcg.media_assets
    drop constraint if exists media_assets_scope_check;
alter table tcg.media_assets
    add constraint media_assets_scope_check
    check (
        scope in ('CANONICAL_CARD','CANONICAL_PRODUCT','INVENTORY_ITEM')
    );

alter table tcg.media_assets
    drop constraint if exists media_assets_check;
alter table tcg.media_assets
    add constraint media_assets_check
    check (
        (
            scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
            and catalogue_id is not null
            and inventory_id is null
        )
        or
        (
            scope='INVENTORY_ITEM'
            and inventory_id is not null
            and catalogue_id is null
        )
    );

alter table tcg.media_assets
    drop constraint if exists media_assets_capture_context_check;
alter table tcg.media_assets
    add constraint media_assets_capture_context_check
    check (
        capture_context is null
        or capture_context in (
            'RAW_UNSLEEVED',
            'PENNY_SLEEVE',
            'TOP_LOADER',
            'GRADED_SLAB',
            'SEALED_PRODUCT'
        )
    );

alter table tcg.media_assets
    drop constraint if exists media_assets_storefront_canonical_identity_check;
alter table tcg.media_assets
    add constraint media_assets_storefront_canonical_identity_check
    check (
        not (
            scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
            and rights_tier='STOREFRONT_ALLOWED'
            and approval_status='APPROVED'
        )
        or (
            nullif(btrim(media_language),'') is not null
            and (
                nullif(btrim(rights_basis),'') is not null
                or permission_evidence_url is not null
            )
        )
    );

commit;
