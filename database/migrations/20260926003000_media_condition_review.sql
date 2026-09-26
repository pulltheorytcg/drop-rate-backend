begin;

alter table tcg.media_assets
    add column capture_context text,
    add column shopify_cdn_url text;

alter table tcg.media_assets
    add constraint media_assets_capture_context_check
    check (
        capture_context is null
        or capture_context in ('RAW_UNSLEEVED','PENNY_SLEEVE','TOP_LOADER','GRADED_SLAB')
    ),
    add constraint media_assets_shopify_cdn_url_check
    check (shopify_cdn_url is null or shopify_cdn_url ~ '^https://');

alter table tcg.inventory_items
    add column condition_review_status text not null default 'NOT_REVIEWED'
        check (
            condition_review_status in (
                'NOT_REVIEWED',
                'NEEDS_REVIEW',
                'NEEDS_RESHOOT',
                'VERIFIED_NEAR_MINT',
                'VERIFIED_GRADED',
                'REJECTED_BELOW_NEAR_MINT'
            )
        ),
    add column condition_verified_at timestamptz,
    add column condition_verified_by_user_id uuid references auth.users(id);

alter table tcg.inventory_items
    add constraint inventory_condition_review_verification_check
    check (
        (
            condition_review_status in ('VERIFIED_NEAR_MINT','VERIFIED_GRADED')
            and condition_verified_at is not null
            and condition_verified_by_user_id is not null
        )
        or
        (
            condition_review_status not in ('VERIFIED_NEAR_MINT','VERIFIED_GRADED')
            and condition_verified_at is null
            and condition_verified_by_user_id is null
        )
    );

create table tcg.condition_review_events (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    inventory_id uuid not null references tcg.inventory_items(id),
    front_media_asset_id uuid not null references tcg.media_assets(id),
    back_media_asset_id uuid not null references tcg.media_assets(id),
    decision text not null check (
        decision in (
            'APPROVE_NEAR_MINT',
            'VERIFY_GRADED',
            'REJECT_BELOW_NEAR_MINT',
            'NEEDS_RESHOOT'
        )
    ),
    observed_condition text check (
        observed_condition is null
        or observed_condition in (
            'Near Mint',
            'Lightly Played',
            'Moderately Played',
            'Heavily Played',
            'Damaged'
        )
    ),
    reshoot_side text check (
        reshoot_side is null or reshoot_side in ('FRONT','BACK','BOTH')
    ),
    notes text not null default '',
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default now()
);

create index inventory_condition_verified_by_user_idx
    on tcg.inventory_items(condition_verified_by_user_id)
    where condition_verified_by_user_id is not null;

create index condition_review_events_inventory_created_idx
    on tcg.condition_review_events(inventory_id,created_at desc);
create index condition_review_events_owner_created_idx
    on tcg.condition_review_events(owner_id,created_at desc);
create index condition_review_events_front_media_idx
    on tcg.condition_review_events(front_media_asset_id);
create index condition_review_events_back_media_idx
    on tcg.condition_review_events(back_media_asset_id);
create index condition_review_events_created_by_user_idx
    on tcg.condition_review_events(created_by_user_id);

alter table tcg.condition_review_events enable row level security;
alter table tcg.condition_review_events force row level security;
revoke all on table tcg.condition_review_events from anon, authenticated;

create policy admin_access on tcg.condition_review_events
    for all to postgres using (true) with check (true);

create policy own_condition_review_reads on tcg.condition_review_events
    for select to tcg_api
    using (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=(select nullif(current_setting('tcg.user_id',true),'')::uuid)
              and om.active
        )
    );

create policy own_condition_review_inserts on tcg.condition_review_events
    for insert to tcg_api
    with check (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id=(select nullif(current_setting('tcg.user_id',true),'')::uuid)
              and om.active
        )
    );

grant select,insert on tcg.condition_review_events to tcg_api;
revoke update,delete on tcg.condition_review_events from tcg_api;

commit;
