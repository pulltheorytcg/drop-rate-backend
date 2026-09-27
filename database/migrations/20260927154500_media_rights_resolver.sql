begin;

-- Existing-image-first storefront media governance.
-- Public availability is never treated as permission. A media asset must carry
-- an explicit rights tier and, for reusable canonical storefront media, an
-- exact language/variant match plus permission evidence.

alter table tcg.media_assets
    add column rights_tier text not null default 'INTERNAL_REFERENCE_ONLY',
    add column source_provider text,
    add column provider_asset_id text,
    add column media_language text,
    add column media_variant text not null default '',
    add column permission_evidence_url text,
    add column source_status text not null default 'ACTIVE',
    add column source_status_note text,
    add column source_checked_at timestamptz,
    add column rights_verified_at timestamptz,
    add column revoked_at timestamptz,
    add column revoked_by_user_id uuid references auth.users(id),
    add column revocation_reason text;

alter table tcg.media_assets
    add constraint media_assets_rights_tier_check
    check (
        rights_tier in (
            'STOREFRONT_ALLOWED',
            'MARKETPLACE_NATIVE_ONLY',
            'INTERNAL_REFERENCE_ONLY',
            'FIRST_PARTY_CAPTURE'
        )
    ),
    add constraint media_assets_source_status_check
    check (source_status in ('ACTIVE','DEAD','REVOKED')),
    add constraint media_assets_permission_evidence_url_check
    check (
        permission_evidence_url is null
        or permission_evidence_url ~ '^https://'
    ),
    add constraint media_assets_first_party_scope_check
    check (
        rights_tier <> 'FIRST_PARTY_CAPTURE'
        or scope = 'INVENTORY_ITEM'
    ),
    add constraint media_assets_storefront_canonical_identity_check
    check (
        not (
            scope='CANONICAL_CARD'
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
    ),
    add constraint media_assets_revocation_state_check
    check (
        (
            source_status='REVOKED'
            and revoked_at is not null
            and revoked_by_user_id is not null
            and nullif(btrim(revocation_reason),'') is not null
        )
        or
        (
            source_status <> 'REVOKED'
            and revoked_at is null
            and revoked_by_user_id is null
            and revocation_reason is null
        )
    );

create index media_assets_revoked_by_user_idx
    on tcg.media_assets(revoked_by_user_id)
    where revoked_by_user_id is not null;

create index media_assets_storefront_resolver_idx
    on tcg.media_assets(
        catalogue_id,
        lower(media_language),
        lower(media_variant),
        side
    )
    where scope='CANONICAL_CARD'
      and rights_tier='STOREFRONT_ALLOWED'
      and source_status='ACTIVE'
      and approval_status='APPROVED'
      and rights_status='VERIFIED'
      and shopify_file_status='READY';

-- A catalogue row can occasionally serve inventory whose explicit language
-- differs from a legacy catalogue language. Uniqueness therefore includes the
-- source image's declared language and variant rather than just catalogue ID.
drop index if exists tcg.media_assets_canonical_live_side_uidx;

create unique index media_assets_canonical_live_side_uidx
    on tcg.media_assets(
        owner_id,
        catalogue_id,
        lower(coalesce(media_language,'')),
        lower(coalesce(media_variant,'')),
        side
    )
    where scope='CANONICAL_CARD'
      and approval_status <> 'REJECTED'
      and shopify_file_status <> 'FAILED'
      and source_status <> 'REVOKED';

commit;
