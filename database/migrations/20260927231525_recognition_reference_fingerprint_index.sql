begin;

create table tcg.recognition_reference_fingerprints (
    id uuid primary key default gen_random_uuid(),
    catalogue_id uuid not null references tcg.catalogue_products(id),
    media_asset_id uuid not null references tcg.media_assets(id),
    system_code text not null references tcg.collectible_systems(code),
    fingerprint_version text not null
        check (length(fingerprint_version) between 1 and 80),
    source_fingerprints jsonb not null
        check (
            jsonb_typeof(source_fingerprints)='array'
            and jsonb_array_length(source_fingerprints) between 1 and 16
        ),
    trust_level text not null
        check (trust_level in ('PROVISIONAL','VERIFIED')),
    media_asset_version integer not null check (media_asset_version >= 1),
    source_url text not null check (length(source_url) between 1 and 2000),
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    version integer not null default 1 check (version >= 1),
    unique (media_asset_id, fingerprint_version)
);

create index recognition_reference_fingerprints_catalogue_idx
    on tcg.recognition_reference_fingerprints(catalogue_id, trust_level);
create index recognition_reference_fingerprints_system_idx
    on tcg.recognition_reference_fingerprints(system_code, trust_level);

alter table tcg.recognition_reference_fingerprints enable row level security;
alter table tcg.recognition_reference_fingerprints force row level security;

create policy admin_access on tcg.recognition_reference_fingerprints
    for all to postgres using (true) with check (true);

create policy api_read on tcg.recognition_reference_fingerprints
    for select to tcg_api
    using (tcg.is_platform_admin());

create policy api_insert on tcg.recognition_reference_fingerprints
    for insert to tcg_api
    with check (
        tcg.is_platform_admin()
        and created_by_user_id=tcg.current_user_id()
    );

create policy api_update on tcg.recognition_reference_fingerprints
    for update to tcg_api
    using (tcg.is_platform_admin())
    with check (
        tcg.is_platform_admin()
        and created_by_user_id=tcg.current_user_id()
    );

revoke all on tcg.recognition_reference_fingerprints
    from public,anon,authenticated;
grant select,insert,update on tcg.recognition_reference_fingerprints to tcg_api;
revoke delete on tcg.recognition_reference_fingerprints from tcg_api;

create trigger recognition_reference_fingerprints_audit
    after insert or update or delete on tcg.recognition_reference_fingerprints
    for each row execute function tcg.audit_recognition_change();

commit;
