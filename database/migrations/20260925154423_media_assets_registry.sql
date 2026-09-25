-- Storefront media registry.
-- Media only counts toward Shopify launch readiness after both rights and human
-- approval are verified and the Shopify file has reached READY state.

create table tcg.media_assets (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    catalogue_id uuid references tcg.catalogue_products(id),
    inventory_id uuid references tcg.inventory_items(id),
    scope text not null check (scope in ('CANONICAL_CARD','INVENTORY_ITEM')),
    media_kind text not null default 'IMAGE' check (media_kind in ('IMAGE')),
    side text not null default 'FRONT' check (side in ('FRONT','BACK','OTHER')),
    source_type text not null check (
        source_type in (
            'FOUNDER_UPLOAD',
            'CONSIGNOR_UPLOAD',
            'LICENSED_PROVIDER',
            'OFFICIAL_PROVIDER'
        )
    ),
    source_reference text not null check (nullif(btrim(source_reference),'') is not null),
    public_source_url text,
    rights_status text not null default 'PENDING'
        check (rights_status in ('PENDING','VERIFIED','REJECTED')),
    rights_basis text,
    approval_status text not null default 'PENDING'
        check (approval_status in ('PENDING','APPROVED','REJECTED')),
    alt_text text not null default '',
    content_sha256 text,
    shopify_file_gid text,
    shopify_file_status text not null default 'NOT_UPLOADED'
        check (shopify_file_status in ('NOT_UPLOADED','UPLOADED','PROCESSING','READY','FAILED')),
    shopify_error text,
    created_by_user_id uuid not null references auth.users(id),
    approved_by_user_id uuid references auth.users(id),
    approved_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    version integer not null default 1 check (version >= 1),

    check (
        (scope='CANONICAL_CARD' and catalogue_id is not null and inventory_id is null)
        or
        (scope='INVENTORY_ITEM' and inventory_id is not null and catalogue_id is null)
    ),
    check (
        public_source_url is null
        or public_source_url ~ '^https://'
    ),
    check (
        content_sha256 is null
        or content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    check (
        rights_status <> 'VERIFIED'
        or nullif(btrim(rights_basis),'') is not null
    ),
    check (
        approval_status <> 'APPROVED'
        or (
            rights_status='VERIFIED'
            and approved_by_user_id is not null
            and approved_at is not null
            and nullif(btrim(alt_text),'') is not null
        )
    ),
    check (
        (shopify_file_status='NOT_UPLOADED' and shopify_file_gid is null)
        or
        (
            shopify_file_status in ('UPLOADED','PROCESSING','READY','FAILED')
            and nullif(btrim(shopify_file_gid),'') is not null
        )
    )
);

create index media_assets_catalogue_ready_idx
    on tcg.media_assets(catalogue_id,side)
    where scope='CANONICAL_CARD'
      and approval_status='APPROVED'
      and rights_status='VERIFIED'
      and shopify_file_status='READY';

create index media_assets_inventory_ready_idx
    on tcg.media_assets(inventory_id,side)
    where scope='INVENTORY_ITEM'
      and approval_status='APPROVED'
      and rights_status='VERIFIED'
      and shopify_file_status='READY';

create index media_assets_owner_updated_idx
    on tcg.media_assets(owner_id,updated_at desc);

alter table tcg.media_assets enable row level security;
alter table tcg.media_assets force row level security;

revoke all on table tcg.media_assets from anon, authenticated;

create policy admin_access on tcg.media_assets
    for all to postgres using (true) with check (true);

create policy readable_assets on tcg.media_assets
    for select to tcg_api
    using (
        scope='CANONICAL_CARD'
        or owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=nullif(current_setting('tcg.user_id',true),'')::uuid
              and om.active
        )
    );

create policy own_asset_writes on tcg.media_assets
    for all to tcg_api
    using (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=nullif(current_setting('tcg.user_id',true),'')::uuid
              and om.active
        )
    )
    with check (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=nullif(current_setting('tcg.user_id',true),'')::uuid
              and om.active
        )
    );

grant select,insert,update on tcg.media_assets to tcg_api;
revoke delete on tcg.media_assets from tcg_api;

create trigger media_assets_audit
    after insert or update or delete on tcg.media_assets
    for each row execute function tcg.audit_change();
