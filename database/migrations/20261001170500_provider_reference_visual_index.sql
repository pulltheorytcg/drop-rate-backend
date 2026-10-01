begin;

create table tcg.recognition_provider_reference_fingerprints (
    id uuid primary key default gen_random_uuid(),
    provider text not null,
    system_code text not null references tcg.collectible_systems(code),
    language text not null,
    provider_id text not null,
    fingerprint_version text not null
        check (length(fingerprint_version) between 1 and 80),
    source_hashes bit(256)[] not null
        check (cardinality(source_hashes) between 1 and 16),
    image_url text not null
        check (image_url like 'https://%'),
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    version integer not null default 1 check (version >= 1),
    unique (
        provider,system_code,language,provider_id,fingerprint_version
    ),
    foreign key (provider,system_code,language,provider_id)
        references tcg.reference_cards(provider,system_code,language,provider_id)
);

create index recognition_provider_reference_fingerprints_lookup_idx
    on tcg.recognition_provider_reference_fingerprints(
        system_code,language,fingerprint_version
    );

create index recognition_provider_reference_fingerprints_creator_idx
    on tcg.recognition_provider_reference_fingerprints(created_by_user_id);

alter table tcg.recognition_provider_reference_fingerprints enable row level security;
alter table tcg.recognition_provider_reference_fingerprints force row level security;

create policy admin_access on tcg.recognition_provider_reference_fingerprints
    for all to postgres using (true) with check (true);

create policy api_read on tcg.recognition_provider_reference_fingerprints
    for select to tcg_api
    using (tcg.is_platform_admin());

create policy api_insert on tcg.recognition_provider_reference_fingerprints
    for insert to tcg_api
    with check (
        tcg.is_platform_admin()
        and created_by_user_id=tcg.current_user_id()
    );

create policy api_update on tcg.recognition_provider_reference_fingerprints
    for update to tcg_api
    using (tcg.is_platform_admin())
    with check (tcg.is_platform_admin());

revoke all on tcg.recognition_provider_reference_fingerprints
    from public,anon,authenticated;
grant select,insert,update on tcg.recognition_provider_reference_fingerprints to tcg_api;
revoke delete on tcg.recognition_provider_reference_fingerprints from tcg_api;

create trigger recognition_provider_reference_fingerprints_audit
    after insert or update or delete on tcg.recognition_provider_reference_fingerprints
    for each row execute function tcg.audit_recognition_change();

create or replace function tcg.recognition_provider_reference_visual_hints(
    p_system_code text,
    p_language text,
    p_source_hashes text[],
    p_max_candidates integer default 24,
    p_min_similarity numeric default 0.40
)
returns table(
    provider text,
    system_code text,
    language text,
    provider_id text,
    set_id text,
    set_name text,
    name text,
    card_number text,
    finish text,
    rarity text,
    image_url text,
    source_url text,
    evidence jsonb,
    similarity numeric
)
language sql
stable
security definer
set search_path=pg_catalog
as $$
    with source_hashes as materialized (
        select ('x' || lower(value))::bit(256) as hash
        from unnest(coalesce(p_source_hashes,array[]::text[])) value
        where value ~ '^[0-9A-Fa-f]{64}$'
    ),
    scored as materialized (
        select
            rf.provider,
            rf.system_code,
            rf.language,
            rf.provider_id,
            min(bit_count(reference_hash # source_hash.hash))::integer as hamming
        from tcg.recognition_provider_reference_fingerprints rf
        join tcg.reference_cards c
          on c.provider=rf.provider
         and c.system_code=rf.system_code
         and c.language=rf.language
         and c.provider_id=rf.provider_id
        join tcg.reference_sets s
          on s.provider=c.provider
         and s.system_code=c.system_code
         and s.language=c.language
         and s.set_id=c.set_id
        cross join lateral unnest(rf.source_hashes) reference_hash
        cross join source_hashes source_hash
        where rf.fingerprint_version='dhash16-multicrop-rotate-v1'
          and rf.system_code=p_system_code
          and (
              p_language is null
              or btrim(p_language)=''
              or p_language='Unknown'
              or rf.language in (p_language,'Unknown')
          )
          and c.image_url=rf.image_url
          and c.image_url is not null
          and (s.release_date is null or s.release_date<=current_date)
        group by rf.provider,rf.system_code,rf.language,rf.provider_id
    ),
    ranked as (
        select
            scored.*,
            round((1.0 - scored.hamming::numeric / 256.0),5) as similarity
        from scored
        where scored.hamming <=
            floor((1.0 - least(greatest(coalesce(p_min_similarity,0.40),0),1)) * 256)
        order by scored.hamming,scored.provider,scored.provider_id
        limit least(greatest(coalesce(p_max_candidates,24),1),50)
    )
    select
        c.provider,
        c.system_code,
        c.language,
        c.provider_id,
        c.set_id,
        s.name as set_name,
        c.name,
        c.card_number,
        c.finish,
        c.rarity,
        c.image_url,
        c.source_url,
        c.evidence,
        ranked.similarity
    from ranked
    join tcg.reference_cards c
      on c.provider=ranked.provider
     and c.system_code=ranked.system_code
     and c.language=ranked.language
     and c.provider_id=ranked.provider_id
    join tcg.reference_sets s
      on s.provider=c.provider
     and s.system_code=c.system_code
     and s.language=c.language
     and s.set_id=c.set_id
    order by ranked.hamming,c.provider,c.provider_id
$$;

revoke all on function tcg.recognition_provider_reference_visual_hints(
    text,text,text[],integer,numeric
) from public,anon,authenticated,service_role;
grant execute on function tcg.recognition_provider_reference_visual_hints(
    text,text,text[],integer,numeric
) to tcg_api;

commit;
