-- R2 is a byte store, not an alternative source of product identity, ownership,
-- pricing or media rights. A mirror is only usable while its original approved
-- asset is still active and its source URL is unchanged.
create table tcg.media_object_mirrors (
    id uuid primary key default gen_random_uuid(),
    media_asset_id uuid not null unique references tcg.media_assets(id) on delete restrict,
    source_url text not null check (source_url ~ '^https://[^[:space:]]+$'),
    object_key text not null check (
        object_key ~ '^[a-zA-Z0-9_-]+/private-media/[0-9a-f]{64}\.webp$'
    ),
    content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
    content_type text not null default 'image/webp' check (content_type = 'image/webp'),
    size_bytes integer not null check (size_bytes between 1 and 10000000),
    verified_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint mirror_key_matches_digest check (
        right(object_key, 69) = content_sha256 || '.webp'
    )
);

create index media_object_mirrors_verified_idx
    on tcg.media_object_mirrors(verified_at desc);

alter table tcg.media_object_mirrors enable row level security;
alter table tcg.media_object_mirrors force row level security;

revoke all on table tcg.media_object_mirrors from public, anon, authenticated;

-- The API's database role is backend-only. Never expose mirror metadata
-- through anon/authenticated PostgREST. No mirror grants approval to an asset.
create policy approved_media_mirror_read on tcg.media_object_mirrors
    for select to tcg_api using (exists (
        select 1 from tcg.media_assets m
        where m.id = media_asset_id
          and m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
          and m.side='FRONT' and m.media_kind='IMAGE'
          and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
          and m.rights_tier='STOREFRONT_ALLOWED'
          and m.source_status='ACTIVE' and m.revoked_at is null
          and m.source_type in ('OFFICIAL_PROVIDER','LICENSED_PROVIDER')
    ));

create policy approved_media_mirror_insert on tcg.media_object_mirrors
    for insert to tcg_api with check (exists (
        select 1 from tcg.media_assets m
        where m.id=media_asset_id
          and m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
          and m.side='FRONT' and m.media_kind='IMAGE'
          and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
          and m.rights_tier='STOREFRONT_ALLOWED'
          and m.source_status='ACTIVE' and m.revoked_at is null
          and m.public_source_url=source_url
          and m.source_type in ('OFFICIAL_PROVIDER','LICENSED_PROVIDER')
    ));

create policy approved_media_mirror_update on tcg.media_object_mirrors
    for update to tcg_api using (exists (
        select 1 from tcg.media_assets m
        where m.id=media_asset_id
          and m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
          and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
          and m.rights_tier='STOREFRONT_ALLOWED'
          and m.source_status='ACTIVE' and m.revoked_at is null
          and m.source_type in ('OFFICIAL_PROVIDER','LICENSED_PROVIDER')
    )) with check (exists (
        select 1 from tcg.media_assets m
        where m.id=media_asset_id
          and m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
          and m.side='FRONT' and m.media_kind='IMAGE'
          and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
          and m.rights_tier='STOREFRONT_ALLOWED'
          and m.source_status='ACTIVE' and m.revoked_at is null
          and m.public_source_url=source_url
          and m.source_type in ('OFFICIAL_PROVIDER','LICENSED_PROVIDER')
    ));

grant select,insert,update on tcg.media_object_mirrors to tcg_api;
revoke delete on tcg.media_object_mirrors from tcg_api;

-- Existing audit trigger records every insert/update under its request ID.
create trigger media_object_mirrors_audit
    after insert or update on tcg.media_object_mirrors
    for each row execute function tcg.audit_media_asset_change();
