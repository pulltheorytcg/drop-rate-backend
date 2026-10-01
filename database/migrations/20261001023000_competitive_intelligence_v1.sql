begin;

create table tcg.competitors (
    id uuid primary key default gen_random_uuid(),
    competitor_key text not null unique
        check (
            char_length(competitor_key) between 2 and 80
            and competitor_key ~ '^[a-z0-9][a-z0-9-]+$'
        ),
    name text not null check (char_length(name) between 1 and 200),
    tier text not null
        check (tier in ('MARKET_LEADER','DIRECT','EMERGING')),
    website_url text
        check (website_url is null or website_url ~ '^https://'),
    status text not null default 'APPROVED'
        check (status in ('APPROVED','PAUSED','REJECTED')),
    notes text not null default '' check (char_length(notes) <= 2000),
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    version integer not null default 1 check (version >= 1)
);

create index competitors_status_tier_idx
    on tcg.competitors(status,tier,created_at desc);
create index competitors_created_by_user_idx
    on tcg.competitors(created_by_user_id);

create table tcg.competitor_sources (
    id uuid primary key default gen_random_uuid(),
    competitor_id uuid not null references tcg.competitors(id),
    source_key text not null unique
        check (char_length(source_key) between 2 and 255),
    source_type text not null
        check (source_type in (
            'WEBSITE','SOCIAL','NEWSLETTER','REVIEWS',
            'MARKETPLACE','SEARCH','OTHER'
        )),
    collection_method text not null
        check (collection_method in (
            'OFFICIAL_API','PUBLIC_API','PUBLIC_FEED',
            'PUBLIC_PAGE','SUBSCRIBED_EMAIL','MANUAL_REVIEW'
        )),
    source_url text
        check (source_url is null or source_url ~ '^https://'),
    rights_status text not null default 'REFERENCE_ONLY'
        check (rights_status in (
            'REFERENCE_ONLY','PERMITTED_REUSE','OWNED','PUBLIC_DOMAIN'
        )),
    terms_review_status text not null default 'PENDING'
        check (terms_review_status in (
            'PENDING','REVIEWED','NOT_REQUIRED','BLOCKED'
        )),
    terms_reviewed_at timestamptz,
    terms_reviewed_by_user_id uuid references auth.users(id),
    terms_review_notes text not null default ''
        check (char_length(terms_review_notes) <= 2000),
    status text not null default 'PENDING'
        check (status in ('PENDING','ACTIVE','PAUSED','BLOCKED')),
    poll_interval_minutes integer
        check (
            poll_interval_minutes is null
            or poll_interval_minutes between 60 and 10080
        ),
    rate_limit_notes text not null default ''
        check (char_length(rate_limit_notes) <= 2000),
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    version integer not null default 1 check (version >= 1),
    unique (id,competitor_id),
    check (
        status <> 'ACTIVE'
        or terms_review_status in ('REVIEWED','NOT_REQUIRED')
    ),
    check (
        terms_review_status <> 'REVIEWED'
        or (
            terms_reviewed_at is not null
            and terms_reviewed_by_user_id is not null
        )
    ),
    check (
        collection_method <> 'MANUAL_REVIEW'
        or terms_review_status <> 'REVIEWED'
    ),
    check (
        terms_review_status <> 'NOT_REQUIRED'
        or collection_method='MANUAL_REVIEW'
    )
);

create index competitor_sources_competitor_status_idx
    on tcg.competitor_sources(competitor_id,status,created_at desc);
create index competitor_sources_terms_reviewer_idx
    on tcg.competitor_sources(terms_reviewed_by_user_id)
    where terms_reviewed_by_user_id is not null;
create index competitor_sources_created_by_user_idx
    on tcg.competitor_sources(created_by_user_id);

create table tcg.competitive_observations (
    id uuid primary key default gen_random_uuid(),
    competitor_id uuid not null references tcg.competitors(id),
    source_id uuid not null,
    dedupe_key text not null unique
        check (char_length(dedupe_key) between 1 and 255),
    observation_type text not null
        check (observation_type in (
            'PRODUCT_LAUNCH','PRICE','PROMOTION','STOCK',
            'MERCHANDISING','CRO','SEO','CONTENT','SOCIAL',
            'CHANNEL','REVIEW','CUSTOMER_PAIN','OTHER'
        )),
    subject text not null check (char_length(subject) between 1 and 500),
    source_url text
        check (source_url is null or source_url ~ '^https://'),
    facts jsonb not null default '{}'::jsonb
        check (jsonb_typeof(facts)='object'),
    evidence jsonb not null default '[]'::jsonb
        check (jsonb_typeof(evidence)='array'),
    confidence numeric(6,5) not null
        check (confidence between 0 and 1),
    relevance numeric(6,5) not null
        check (relevance between 0 and 1),
    rights_status text not null
        check (rights_status in (
            'REFERENCE_ONLY','PERMITTED_REUSE','OWNED','PUBLIC_DOMAIN'
        )),
    observed_at timestamptz not null,
    source_published_at timestamptz,
    actor_type text not null default 'HUMAN'
        check (actor_type in ('HUMAN','SYSTEM')),
    created_by_user_id uuid references auth.users(id),
    created_at timestamptz not null default clock_timestamp(),
    foreign key (source_id,competitor_id)
        references tcg.competitor_sources(id,competitor_id),
    check (
        (actor_type='HUMAN' and created_by_user_id is not null)
        or
        (actor_type='SYSTEM' and created_by_user_id is null)
    )
);

create index competitive_observations_competitor_time_idx
    on tcg.competitive_observations(competitor_id,observed_at desc);
create index competitive_observations_source_time_idx
    on tcg.competitive_observations(source_id,observed_at desc);
create index competitive_observations_type_time_idx
    on tcg.competitive_observations(observation_type,observed_at desc);
create index competitive_observations_created_by_user_idx
    on tcg.competitive_observations(created_by_user_id)
    where created_by_user_id is not null;

create table tcg.competitive_opportunities (
    id uuid primary key default gen_random_uuid(),
    opportunity_key text not null unique
        check (char_length(opportunity_key) between 2 and 255),
    opportunity_type text not null
        check (opportunity_type in (
            'CONTENT','CRO','SEO','MERCHANDISING',
            'ACQUISITION','CHANNEL'
        )),
    subject text not null check (char_length(subject) between 1 and 500),
    hypothesis text not null check (char_length(hypothesis) between 1 and 3000),
    state text not null
        check (state in (
            'WATCH','QUALIFIED','DISMISSED','HANDED_OFF','EXPIRED'
        )),
    score numeric(6,5) not null check (score between 0 and 1),
    reasons jsonb not null default '[]'::jsonb
        check (jsonb_typeof(reasons)='array'),
    independent_sources integer not null check (independent_sources >= 0),
    independent_origins integer not null check (independent_origins >= 0),
    competitor_sources integer not null check (competitor_sources >= 0),
    non_competitor_sources integer not null check (non_competitor_sources >= 0),
    qualification_version text not null default 'competitive-intelligence-v1'
        check (char_length(qualification_version) between 1 and 100),
    created_by_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    version integer not null default 1 check (version >= 1)
);

create index competitive_opportunities_state_score_idx
    on tcg.competitive_opportunities(state,score desc,created_at desc);
create index competitive_opportunities_created_by_user_idx
    on tcg.competitive_opportunities(created_by_user_id);

create table tcg.competitive_opportunity_evidence (
    id uuid primary key default gen_random_uuid(),
    opportunity_id uuid not null references tcg.competitive_opportunities(id),
    origin text not null
        check (origin in ('COMPETITOR','INTERNAL','MARKET','SOCIAL','OFFICIAL')),
    source_key text not null check (char_length(source_key) between 1 and 255),
    competitor_observation_id uuid references tcg.competitive_observations(id),
    confidence numeric(6,5) not null check (confidence between 0 and 1),
    relevance numeric(6,5) not null check (relevance between 0 and 1),
    rights_status text not null
        check (rights_status in (
            'REFERENCE_ONLY','PERMITTED_REUSE','OWNED','PUBLIC_DOMAIN'
        )),
    evidence jsonb not null default '{}'::jsonb
        check (jsonb_typeof(evidence)='object'),
    created_at timestamptz not null default clock_timestamp(),
    unique (opportunity_id,source_key),
    check (
        (origin='COMPETITOR' and competitor_observation_id is not null)
        or
        (origin<>'COMPETITOR' and competitor_observation_id is null)
    )
);

create index competitive_opportunity_evidence_opportunity_idx
    on tcg.competitive_opportunity_evidence(opportunity_id,origin);
create index competitive_opportunity_evidence_observation_idx
    on tcg.competitive_opportunity_evidence(competitor_observation_id)
    where competitor_observation_id is not null;

create or replace function tcg.prevent_competitive_evidence_mutation()
returns trigger
language plpgsql
set search_path=pg_catalog
as $$
begin
    raise exception 'Competitive intelligence evidence is immutable'
        using errcode='55000';
end;
$$;

revoke all on function tcg.prevent_competitive_evidence_mutation() from public;
revoke all on function tcg.prevent_competitive_evidence_mutation()
    from anon,authenticated,service_role;
grant execute on function tcg.prevent_competitive_evidence_mutation() to tcg_api;

create trigger competitive_observations_immutable
    before update or delete on tcg.competitive_observations
    for each row execute function tcg.prevent_competitive_evidence_mutation();

create trigger competitive_opportunity_evidence_immutable
    before update or delete on tcg.competitive_opportunity_evidence
    for each row execute function tcg.prevent_competitive_evidence_mutation();

create or replace function tcg.audit_competitive_intelligence_change()
returns trigger
language plpgsql
security definer
set search_path=pg_catalog
as $$
declare
    v_old jsonb := case when tg_op='INSERT' then null else to_jsonb(old) end;
    v_new jsonb := case when tg_op='DELETE' then null else to_jsonb(new) end;
    v_row jsonb := coalesce(v_new,v_old);
    v_entity_id uuid := nullif(v_row->>'id','')::uuid;
    v_actor text := coalesce(
        nullif(current_setting('tcg.user_id',true),''),
        session_user::text
    );
begin
    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values (
        v_actor,
        nullif(current_setting('tcg.request_id',true),''),
        'COMPETITIVE_INTELLIGENCE_' || tg_op,
        upper(tg_table_name),
        v_entity_id,
        v_old,
        v_new
    );
    return null;
end;
$$;

revoke all on function tcg.audit_competitive_intelligence_change() from public;
revoke all on function tcg.audit_competitive_intelligence_change()
    from anon,authenticated,service_role;
grant execute on function tcg.audit_competitive_intelligence_change() to tcg_api;

create trigger competitors_audit
    after insert or update or delete on tcg.competitors
    for each row execute function tcg.audit_competitive_intelligence_change();
create trigger competitor_sources_audit
    after insert or update or delete on tcg.competitor_sources
    for each row execute function tcg.audit_competitive_intelligence_change();
create trigger competitive_observations_audit
    after insert or update or delete on tcg.competitive_observations
    for each row execute function tcg.audit_competitive_intelligence_change();
create trigger competitive_opportunities_audit
    after insert or update or delete on tcg.competitive_opportunities
    for each row execute function tcg.audit_competitive_intelligence_change();
create trigger competitive_opportunity_evidence_audit
    after insert or update or delete on tcg.competitive_opportunity_evidence
    for each row execute function tcg.audit_competitive_intelligence_change();

alter table tcg.competitors enable row level security;
alter table tcg.competitors force row level security;
alter table tcg.competitor_sources enable row level security;
alter table tcg.competitor_sources force row level security;
alter table tcg.competitive_observations enable row level security;
alter table tcg.competitive_observations force row level security;
alter table tcg.competitive_opportunities enable row level security;
alter table tcg.competitive_opportunities force row level security;
alter table tcg.competitive_opportunity_evidence enable row level security;
alter table tcg.competitive_opportunity_evidence force row level security;

create policy admin_access on tcg.competitors
    for all to postgres using (true) with check (true);
create policy api_access on tcg.competitors
    for all to tcg_api
    using (tcg.is_platform_admin())
    with check (tcg.is_platform_admin());

create policy admin_access on tcg.competitor_sources
    for all to postgres using (true) with check (true);
create policy api_access on tcg.competitor_sources
    for all to tcg_api
    using (tcg.is_platform_admin())
    with check (tcg.is_platform_admin());

create policy admin_access on tcg.competitive_observations
    for all to postgres using (true) with check (true);
create policy api_read on tcg.competitive_observations
    for select to tcg_api
    using (tcg.is_platform_admin());
create policy api_insert on tcg.competitive_observations
    for insert to tcg_api
    with check (tcg.is_platform_admin());

create policy admin_access on tcg.competitive_opportunities
    for all to postgres using (true) with check (true);
create policy api_access on tcg.competitive_opportunities
    for all to tcg_api
    using (tcg.is_platform_admin())
    with check (tcg.is_platform_admin());

create policy admin_access on tcg.competitive_opportunity_evidence
    for all to postgres using (true) with check (true);
create policy api_read on tcg.competitive_opportunity_evidence
    for select to tcg_api
    using (tcg.is_platform_admin());
create policy api_insert on tcg.competitive_opportunity_evidence
    for insert to tcg_api
    with check (tcg.is_platform_admin());

revoke all on tcg.competitors,
              tcg.competitor_sources,
              tcg.competitive_observations,
              tcg.competitive_opportunities,
              tcg.competitive_opportunity_evidence
    from public,anon,authenticated,service_role;

grant select,insert,update on tcg.competitors,
                              tcg.competitor_sources,
                              tcg.competitive_opportunities
    to tcg_api;

grant select,insert on tcg.competitive_observations,
                       tcg.competitive_opportunity_evidence
    to tcg_api;

revoke delete on tcg.competitors,
                 tcg.competitor_sources,
                 tcg.competitive_observations,
                 tcg.competitive_opportunities,
                 tcg.competitive_opportunity_evidence
    from tcg_api;

revoke update on tcg.competitive_observations,
                 tcg.competitive_opportunity_evidence
    from tcg_api;

commit;
