begin;

-- Recognition Engine v1.
-- AI extracts observations; deterministic backend scoring chooses whether an exact
-- printing candidate is sufficiently evidenced. Recognition history is auditable
-- and never mutates inventory identity silently.

create table tcg.recognition_runs (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    inventory_id uuid references tcg.inventory_items(id),
    idempotency_key text not null,
    source_image_sha256 text,
    source_mime_type text,
    source_size_bytes integer check (
        source_size_bytes is null or source_size_bytes between 1 and 20000000
    ),
    status text not null default 'OBSERVING'
        check (status in (
            'OBSERVING',
            'CANDIDATES_READY',
            'EXACT_CANDIDATE',
            'NEEDS_REVIEW',
            'NO_MATCH',
            'FAILED'
        )),
    system_code text references tcg.collectible_systems(code),
    ai_provider text,
    ai_model text,
    ai_observation jsonb not null default '{}'::jsonb,
    provider_evidence jsonb not null default '{}'::jsonb,
    top_catalogue_id uuid references tcg.catalogue_products(id),
    top_score numeric(6,5) check (
        top_score is null or (top_score >= 0 and top_score <= 1)
    ),
    runner_up_score numeric(6,5) check (
        runner_up_score is null or (runner_up_score >= 0 and runner_up_score <= 1)
    ),
    score_margin numeric(6,5) check (
        score_margin is null or (score_margin >= 0 and score_margin <= 1)
    ),
    decision text check (
        decision is null or decision in (
            'EXACT_CANDIDATE',
            'NEEDS_REVIEW',
            'NO_MATCH',
            'FAILED'
        )
    ),
    decision_reasons jsonb not null default '[]'::jsonb,
    risk_flags jsonb not null default '[]'::jsonb,
    error_code text,
    error_detail text,
    created_by_user_id uuid not null references auth.users(id),
    started_at timestamptz not null default clock_timestamp(),
    completed_at timestamptz,
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    version integer not null default 1 check (version >= 1),
    unique (owner_id, idempotency_key),
    check (
        (status in ('OBSERVING','CANDIDATES_READY') and completed_at is null)
        or
        (status in ('EXACT_CANDIDATE','NEEDS_REVIEW','NO_MATCH','FAILED')
         and completed_at is not null)
    ),
    check (
        decision is null
        or status = decision
    ),
    check (
        status <> 'FAILED'
        or (error_code is not null and error_detail is not null)
    )
);

create index recognition_runs_owner_created_idx
    on tcg.recognition_runs(owner_id, created_at desc);
create index recognition_runs_inventory_created_idx
    on tcg.recognition_runs(inventory_id, created_at desc)
    where inventory_id is not null;
create index recognition_runs_decision_created_idx
    on tcg.recognition_runs(decision, created_at desc)
    where decision is not null;
create index recognition_runs_top_catalogue_idx
    on tcg.recognition_runs(top_catalogue_id, created_at desc)
    where top_catalogue_id is not null;
create index recognition_runs_created_by_user_idx
    on tcg.recognition_runs(created_by_user_id);

create table tcg.recognition_candidates (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references tcg.recognition_runs(id),
    candidate_key text not null,
    source_kind text not null
        check (source_kind in ('CATALOGUE','PROVIDER')),
    system_code text not null references tcg.collectible_systems(code),
    catalogue_id uuid references tcg.catalogue_products(id),
    provider text,
    provider_id text,
    provider_language text,
    rank integer not null check (rank >= 1),
    score numeric(6,5) not null check (score >= 0 and score <= 1),
    hard_rejected boolean not null default false,
    rejection_reasons jsonb not null default '[]'::jsonb,
    signals jsonb not null default '{}'::jsonb,
    candidate_snapshot jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default clock_timestamp(),
    unique (run_id, candidate_key),
    unique (run_id, rank),
    check (
        (source_kind='CATALOGUE' and catalogue_id is not null)
        or source_kind='PROVIDER'
    ),
    check (
        (provider is null and provider_id is null)
        or (provider is not null and provider_id is not null)
    )
);

create index recognition_candidates_catalogue_idx
    on tcg.recognition_candidates(catalogue_id, created_at desc)
    where catalogue_id is not null;
create index recognition_candidates_provider_idx
    on tcg.recognition_candidates(provider, provider_id)
    where provider_id is not null;

create table tcg.recognition_feedback (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references tcg.recognition_runs(id),
    owner_id uuid not null references tcg.owners(id),
    outcome text not null
        check (outcome in (
            'CONFIRMED_TOP',
            'CORRECTED_TO_CANDIDATE',
            'REJECTED_ALL'
        )),
    selected_catalogue_id uuid references tcg.catalogue_products(id),
    supersedes_feedback_id uuid references tcg.recognition_feedback(id),
    actor_user_id uuid not null references auth.users(id),
    notes text not null default '' check (length(notes) <= 2000),
    created_at timestamptz not null default clock_timestamp(),
    check (
        (outcome in ('CONFIRMED_TOP','CORRECTED_TO_CANDIDATE')
         and selected_catalogue_id is not null)
        or
        (outcome='REJECTED_ALL' and selected_catalogue_id is null)
    )
);

create index recognition_feedback_run_created_idx
    on tcg.recognition_feedback(run_id, created_at desc);
create index recognition_feedback_owner_created_idx
    on tcg.recognition_feedback(owner_id, created_at desc);
create index recognition_feedback_selected_catalogue_idx
    on tcg.recognition_feedback(selected_catalogue_id)
    where selected_catalogue_id is not null;
create index recognition_feedback_actor_idx
    on tcg.recognition_feedback(actor_user_id);
create index recognition_feedback_supersedes_idx
    on tcg.recognition_feedback(supersedes_feedback_id)
    where supersedes_feedback_id is not null;

-- Fast exact collector-number retrieval at scale.
create index catalogue_products_card_number_normalized_idx
    on tcg.catalogue_products (
        upper(regexp_replace(coalesce(card_number,''), '[^A-Za-z0-9]', '', 'g'))
    )
    where product_type='CARD';

alter table tcg.recognition_runs enable row level security;
alter table tcg.recognition_runs force row level security;
alter table tcg.recognition_candidates enable row level security;
alter table tcg.recognition_candidates force row level security;
alter table tcg.recognition_feedback enable row level security;
alter table tcg.recognition_feedback force row level security;

create policy admin_access on tcg.recognition_runs
    for all to postgres using (true) with check (true);
create policy api_read on tcg.recognition_runs
    for select to tcg_api
    using (tcg.current_access_role() is not null and owner_id in (
        select m.owner_id
        from tcg.owner_memberships m
        where m.user_id=tcg.current_user_id()
          and m.active
    ));
create policy api_insert on tcg.recognition_runs
    for insert to tcg_api
    with check (
        tcg.is_platform_admin()
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
        and created_by_user_id=tcg.current_user_id()
    );
create policy api_update on tcg.recognition_runs
    for update to tcg_api
    using (
        tcg.is_platform_admin()
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
    )
    with check (
        tcg.is_platform_admin()
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
    );

create policy admin_access on tcg.recognition_candidates
    for all to postgres using (true) with check (true);
create policy api_read on tcg.recognition_candidates
    for select to tcg_api
    using (exists (
        select 1
        from tcg.recognition_runs r
        join tcg.owner_memberships m on m.owner_id=r.owner_id
        where r.id=recognition_candidates.run_id
          and m.user_id=tcg.current_user_id()
          and m.active
    ));
create policy api_insert on tcg.recognition_candidates
    for insert to tcg_api
    with check (
        tcg.is_platform_admin()
        and exists (
            select 1
            from tcg.recognition_runs r
            join tcg.owner_memberships m on m.owner_id=r.owner_id
            where r.id=recognition_candidates.run_id
              and m.user_id=tcg.current_user_id()
              and m.active
        )
    );

create policy admin_access on tcg.recognition_feedback
    for all to postgres using (true) with check (true);
create policy api_read on tcg.recognition_feedback
    for select to tcg_api
    using (owner_id in (
        select m.owner_id
        from tcg.owner_memberships m
        where m.user_id=tcg.current_user_id()
          and m.active
    ));
create policy api_insert on tcg.recognition_feedback
    for insert to tcg_api
    with check (
        tcg.is_platform_admin()
        and actor_user_id=tcg.current_user_id()
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
    );

revoke all on tcg.recognition_runs,tcg.recognition_candidates,tcg.recognition_feedback
    from public,anon,authenticated;
grant select,insert,update on tcg.recognition_runs to tcg_api;
grant select,insert on tcg.recognition_candidates,tcg.recognition_feedback to tcg_api;
revoke delete on tcg.recognition_runs,tcg.recognition_candidates,tcg.recognition_feedback from tcg_api;
revoke update on tcg.recognition_feedback from tcg_api;
revoke update on tcg.recognition_candidates from tcg_api;

create or replace function tcg.validate_recognition_run()
returns trigger
language plpgsql
set search_path=pg_catalog
as $$
declare
    v_inventory_owner uuid;
    v_top_system text;
begin
    if new.inventory_id is not null then
        select i.owner_id into v_inventory_owner
        from tcg.inventory_items i
        where i.id=new.inventory_id;
        if v_inventory_owner is null then
            raise exception 'Recognition inventory item not found'
                using errcode='23503';
        end if;
        if v_inventory_owner <> new.owner_id then
            raise exception 'Recognition inventory ownership mismatch'
                using errcode='23514';
        end if;
    end if;

    if new.top_catalogue_id is not null then
        select pr.system_code into v_top_system
        from tcg.catalogue_product_profiles pr
        where pr.catalogue_id=new.top_catalogue_id;

        if v_top_system is null then
            raise exception 'Recognition top candidate has no collectible profile'
                using errcode='23503';
        end if;
        if new.system_code is null or v_top_system <> new.system_code then
            raise exception 'Recognition top candidate system mismatch'
                using errcode='23514';
        end if;
    end if;

    if new.decision='EXACT_CANDIDATE' and new.top_catalogue_id is null then
        raise exception 'Exact candidate decision requires a catalogue product'
            using errcode='23514';
    end if;

    return new;
end;
$$;
revoke all on function tcg.validate_recognition_run() from public;
grant execute on function tcg.validate_recognition_run() to tcg_api;

create trigger recognition_runs_validate
    before insert or update on tcg.recognition_runs
    for each row execute function tcg.validate_recognition_run();

create or replace function tcg.validate_recognition_candidate()
returns trigger
language plpgsql
set search_path=pg_catalog
as $$
declare
    v_run_system text;
    v_catalogue_system text;
begin
    select r.system_code into v_run_system
    from tcg.recognition_runs r
    where r.id=new.run_id;

    if v_run_system is null then
        raise exception 'Recognition run requires a resolved collectible system'
            using errcode='23514';
    end if;

    if v_run_system <> new.system_code then
        raise exception 'Recognition candidate system mismatch'
            using errcode='23514';
    end if;

    if new.catalogue_id is not null then
        select pr.system_code into v_catalogue_system
        from tcg.catalogue_product_profiles pr
        where pr.catalogue_id=new.catalogue_id;

        if v_catalogue_system is null then
            raise exception 'Recognition candidate has no collectible profile'
                using errcode='23503';
        end if;
        if v_catalogue_system <> new.system_code then
            raise exception 'Recognition candidate catalogue system mismatch'
                using errcode='23514';
        end if;
    end if;

    return new;
end;
$$;
revoke all on function tcg.validate_recognition_candidate() from public;
grant execute on function tcg.validate_recognition_candidate() to tcg_api;

create trigger recognition_candidates_validate
    before insert on tcg.recognition_candidates
    for each row execute function tcg.validate_recognition_candidate();

create or replace function tcg.prevent_recognition_candidate_mutation()
returns trigger
language plpgsql
set search_path=pg_catalog
as $$
begin
    raise exception 'Recognition candidate evidence is immutable'
        using errcode='55000';
end;
$$;
revoke all on function tcg.prevent_recognition_candidate_mutation() from public;
grant execute on function tcg.prevent_recognition_candidate_mutation() to tcg_api;

create trigger recognition_candidates_immutable
    before update or delete on tcg.recognition_candidates
    for each row execute function tcg.prevent_recognition_candidate_mutation();

create or replace function tcg.validate_recognition_feedback()
returns trigger
language plpgsql
set search_path=pg_catalog
as $$
declare
    v_run_owner uuid;
    v_top_catalogue uuid;
    v_run_status text;
begin
    select r.owner_id,r.top_catalogue_id,r.status
      into v_run_owner,v_top_catalogue,v_run_status
    from tcg.recognition_runs r
    where r.id=new.run_id;

    if v_run_owner is null then
        raise exception 'Recognition run not found'
            using errcode='23503';
    end if;
    if v_run_owner <> new.owner_id then
        raise exception 'Recognition feedback owner mismatch'
            using errcode='23514';
    end if;
    if v_run_status not in ('EXACT_CANDIDATE','NEEDS_REVIEW','NO_MATCH') then
        raise exception 'Only completed recognition runs can be labelled'
            using errcode='23514';
    end if;

    if new.selected_catalogue_id is not null and not exists (
        select 1
        from tcg.recognition_candidates c
        where c.run_id=new.run_id
          and c.catalogue_id=new.selected_catalogue_id
          and not c.hard_rejected
    ) then
        raise exception 'Human label must select a viable recognition candidate'
            using errcode='23514';
    end if;

    if new.outcome='CONFIRMED_TOP'
       and new.selected_catalogue_id is distinct from v_top_catalogue then
        raise exception 'Confirmed-top label must select the run top candidate'
            using errcode='23514';
    end if;

    if new.supersedes_feedback_id is not null and not exists (
        select 1
        from tcg.recognition_feedback f
        where f.id=new.supersedes_feedback_id
          and f.run_id=new.run_id
          and f.owner_id=new.owner_id
    ) then
        raise exception 'Superseded feedback must belong to the same recognition run'
            using errcode='23514';
    end if;

    return new;
end;
$$;
revoke all on function tcg.validate_recognition_feedback() from public;
grant execute on function tcg.validate_recognition_feedback() to tcg_api;

create trigger recognition_feedback_validate
    before insert on tcg.recognition_feedback
    for each row execute function tcg.validate_recognition_feedback();

create trigger recognition_feedback_immutable
    before update or delete on tcg.recognition_feedback
    for each row execute function tcg.prevent_recognition_candidate_mutation();

create or replace function tcg.audit_recognition_change()
returns trigger
language plpgsql
security definer
set search_path=pg_catalog
as $$
declare
    v_row jsonb;
    v_entity_id uuid;
begin
    v_row := case when tg_op='DELETE' then to_jsonb(old) else to_jsonb(new) end;
    v_entity_id := nullif(v_row->>'id','')::uuid;

    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values (
        coalesce(nullif(current_setting('tcg.user_id',true),''),session_user::text),
        nullif(current_setting('tcg.request_id',true),''),
        tg_op,
        tg_table_name,
        v_entity_id,
        case when tg_op='INSERT' then null else to_jsonb(old) end,
        case when tg_op='DELETE' then null else to_jsonb(new) end
    );
    return null;
end;
$$;
revoke all on function tcg.audit_recognition_change() from public;

create trigger recognition_runs_audit
    after insert or update or delete on tcg.recognition_runs
    for each row execute function tcg.audit_recognition_change();
create trigger recognition_candidates_audit
    after insert or update or delete on tcg.recognition_candidates
    for each row execute function tcg.audit_recognition_change();
create trigger recognition_feedback_audit
    after insert or update or delete on tcg.recognition_feedback
    for each row execute function tcg.audit_recognition_change();

commit;
