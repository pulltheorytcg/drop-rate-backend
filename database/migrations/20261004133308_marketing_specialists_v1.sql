-- Additive backend-only state. Nothing here changes inventory or financial data.
create table tcg.marketing_specialist_jobs (
    id uuid not null,
    revision integer not null default 1 check (revision = 1),
    created_by uuid not null references auth.users(id),
    input jsonb not null check (jsonb_typeof(input) = 'object' and octet_length(input::text) <= 131072),
    input_sha256 text not null check (input_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz not null default now(),
    primary key (id, revision),
    unique (id, revision, created_by)
);
create table tcg.marketing_specialist_runs (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null,
    revision integer not null check (revision = 1),
    stage text not null check (stage in ('research','brief','copywriting','design','social_management')),
    created_by uuid not null,
    input jsonb not null check (jsonb_typeof(input) = 'object' and octet_length(input::text) <= 262144),
    input_sha256 text not null check (input_sha256 ~ '^[0-9a-f]{64}$'),
    prompt_version text not null check (length(prompt_version) between 1 and 100),
    prompt_sha256 text not null check (prompt_sha256 ~ '^[0-9a-f]{64}$'),
    model text not null check (length(model) between 1 and 100),
    state text not null default 'RUNNING' check (state in ('RUNNING','PREPARED','NEEDS_REVIEW','AWAITING_MEDIA','FAILED','UNKNOWN')),
    output jsonb,
    output_sha256 text,
    usage jsonb not null default '{}'::jsonb check (jsonb_typeof(usage) = 'object'),
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    unique (job_id, revision, stage),
    foreign key (job_id, revision, created_by) references tcg.marketing_specialist_jobs(id, revision, created_by),
    check ((state = 'RUNNING' and output is null and output_sha256 is null and finished_at is null)
       or (state <> 'RUNNING' and jsonb_typeof(output) = 'object' and output is not null
           and output_sha256 is not null and output_sha256 ~ '^[0-9a-f]{64}$'
           and finished_at is not null and finished_at >= started_at)),
    check (output is null or octet_length(output::text) <= 262144)
);
create index marketing_specialist_jobs_actor_time on tcg.marketing_specialist_jobs(created_by, created_at);
create index marketing_specialist_runs_actor_time on tcg.marketing_specialist_runs(created_by, started_at);

alter table tcg.marketing_specialist_jobs enable row level security;
alter table tcg.marketing_specialist_jobs force row level security;
alter table tcg.marketing_specialist_runs enable row level security;
alter table tcg.marketing_specialist_runs force row level security;
revoke all on tcg.marketing_specialist_jobs, tcg.marketing_specialist_runs from public, anon, authenticated;
grant select on tcg.marketing_specialist_jobs, tcg.marketing_specialist_runs to tcg_api;
grant insert(id,revision,created_by,input,input_sha256) on tcg.marketing_specialist_jobs to tcg_api;
grant insert(job_id,revision,stage,created_by,input,input_sha256,prompt_version,prompt_sha256,model) on tcg.marketing_specialist_runs to tcg_api;
grant update(state,output,output_sha256,usage,finished_at) on tcg.marketing_specialist_runs to tcg_api;
create policy marketing_jobs_read on tcg.marketing_specialist_jobs for select to tcg_api
    using (created_by = tcg.current_user_id() and tcg.is_platform_admin());
create policy marketing_jobs_insert on tcg.marketing_specialist_jobs for insert to tcg_api
    with check (created_by = tcg.current_user_id() and tcg.is_platform_admin());
create policy marketing_runs_read on tcg.marketing_specialist_runs for select to tcg_api
    using (created_by = tcg.current_user_id() and tcg.is_platform_admin());
create policy marketing_runs_insert on tcg.marketing_specialist_runs for insert to tcg_api
    with check (created_by = tcg.current_user_id() and tcg.is_platform_admin() and state = 'RUNNING');
create policy marketing_runs_update on tcg.marketing_specialist_runs for update to tcg_api
    using (created_by = tcg.current_user_id() and tcg.is_platform_admin())
    with check (created_by = tcg.current_user_id() and tcg.is_platform_admin());

create function tcg.marketing_specialist_history_guard() returns trigger
language plpgsql security invoker set search_path = pg_catalog, tcg as $$
begin
    if tg_op = 'DELETE' or tg_table_name = 'marketing_specialist_jobs' then
        raise exception using errcode = '55000', message = 'Marketing history is immutable';
    end if;
    if old.state <> 'RUNNING' or new.state = 'RUNNING'
       or (to_jsonb(old) - array['state','output','output_sha256','usage','finished_at'])
          is distinct from
          (to_jsonb(new) - array['state','output','output_sha256','usage','finished_at']) then
        raise exception using errcode = '55000', message = 'Invalid marketing run transition';
    end if;
    return new;
end;
$$;
revoke all on function tcg.marketing_specialist_history_guard() from public, anon, authenticated;
grant execute on function tcg.marketing_specialist_history_guard() to tcg_api;
create trigger marketing_jobs_immutable before update or delete on tcg.marketing_specialist_jobs
    for each row execute function tcg.marketing_specialist_history_guard();
create trigger marketing_runs_immutable before update or delete on tcg.marketing_specialist_runs
    for each row execute function tcg.marketing_specialist_history_guard();
