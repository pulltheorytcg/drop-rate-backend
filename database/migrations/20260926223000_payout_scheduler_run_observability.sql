-- Durable observability for the payout scheduler.
-- Run records are operational metadata only; payout decisions remain in deterministic business logic.

create table if not exists tcg.payout_scheduler_runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz not null default clock_timestamp(),
  finished_at timestamptz,
  status text not null default 'RUNNING'
    check (status in ('RUNNING','SUCCESS','FAILED')),
  checked_count integer not null default 0 check (checked_count >= 0),
  created_count integer not null default 0 check (created_count >= 0),
  duplicate_count integer not null default 0 check (duplicate_count >= 0),
  no_balance_count integer not null default 0 check (no_balance_count >= 0),
  stripe_not_ready_count integer not null default 0 check (stripe_not_ready_count >= 0),
  owner_inactive_count integer not null default 0 check (owner_inactive_count >= 0),
  preference_changed_count integer not null default 0 check (preference_changed_count >= 0),
  not_yet_due_count integer not null default 0 check (not_yet_due_count >= 0),
  error_count integer not null default 0 check (error_count >= 0),
  error_code text,
  run_at timestamptz,
  created_at timestamptz not null default clock_timestamp()
);

create index if not exists payout_scheduler_runs_started_idx
  on tcg.payout_scheduler_runs(started_at desc);

alter table tcg.payout_scheduler_runs enable row level security;
alter table tcg.payout_scheduler_runs force row level security;

revoke all on tcg.payout_scheduler_runs from public;
revoke all on tcg.payout_scheduler_runs from anon;
revoke all on tcg.payout_scheduler_runs from authenticated;
revoke all on tcg.payout_scheduler_runs from service_role;
revoke all on tcg.payout_scheduler_runs from tcg_api;
revoke all on tcg.payout_scheduler_runs from tcg_auditor;

create or replace function tcg.start_payout_scheduler_run()
returns uuid
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
declare
  v_id uuid;
begin
  insert into tcg.payout_scheduler_runs default values
  returning id into v_id;
  return v_id;
end;
$function$;

create or replace function tcg.finish_payout_scheduler_run(
  p_run_id uuid,
  p_status text,
  p_checked integer,
  p_created integer,
  p_duplicate integer,
  p_no_balance integer,
  p_stripe_not_ready integer,
  p_owner_inactive integer,
  p_preference_changed integer,
  p_not_yet_due integer,
  p_error_count integer,
  p_error_code text,
  p_run_at timestamptz
)
returns boolean
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
begin
  if p_status not in ('SUCCESS','FAILED') then
    raise exception 'Invalid scheduler run status' using errcode='22023';
  end if;

  update tcg.payout_scheduler_runs
     set finished_at=clock_timestamp(),
         status=p_status,
         checked_count=greatest(coalesce(p_checked,0),0),
         created_count=greatest(coalesce(p_created,0),0),
         duplicate_count=greatest(coalesce(p_duplicate,0),0),
         no_balance_count=greatest(coalesce(p_no_balance,0),0),
         stripe_not_ready_count=greatest(coalesce(p_stripe_not_ready,0),0),
         owner_inactive_count=greatest(coalesce(p_owner_inactive,0),0),
         preference_changed_count=greatest(coalesce(p_preference_changed,0),0),
         not_yet_due_count=greatest(coalesce(p_not_yet_due,0),0),
         error_count=greatest(coalesce(p_error_count,0),0),
         error_code=nullif(left(coalesce(p_error_code,''),120),''),
         run_at=p_run_at
   where id=p_run_id
     and status='RUNNING';

  return found;
end;
$function$;

create or replace function tcg.fail_stale_payout_scheduler_runs(
  p_older_than interval default interval '30 minutes'
)
returns integer
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
declare
  v_count integer;
begin
  if p_older_than < interval '5 minutes' then
    raise exception 'Stale scheduler threshold is too small' using errcode='22023';
  end if;

  update tcg.payout_scheduler_runs
     set finished_at=clock_timestamp(),
         status='FAILED',
         error_count=greatest(error_count,1),
         error_code='STALE_RUN'
   where status='RUNNING'
     and started_at < clock_timestamp() - p_older_than;

  get diagnostics v_count = row_count;
  return v_count;
end;
$function$;

revoke all on function tcg.start_payout_scheduler_run() from public;
revoke all on function tcg.finish_payout_scheduler_run(uuid,text,integer,integer,integer,integer,integer,integer,integer,integer,integer,text,timestamptz) from public;
revoke all on function tcg.fail_stale_payout_scheduler_runs(interval) from public;

grant execute on function tcg.start_payout_scheduler_run() to tcg_api;
grant execute on function tcg.finish_payout_scheduler_run(uuid,text,integer,integer,integer,integer,integer,integer,integer,integer,integer,text,timestamptz) to tcg_api;
grant execute on function tcg.fail_stale_payout_scheduler_runs(interval) to tcg_api;
