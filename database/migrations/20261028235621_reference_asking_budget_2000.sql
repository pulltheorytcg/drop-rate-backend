-- Expand the durable UTC-day reservation budget without resetting prior usage.
-- Provider quota checks and headroom remain additional application safeguards.
begin;

alter table tcg.reference_asking_runs
  drop constraint reference_asking_runs_requests_check;
alter table tcg.reference_asking_runs
  add constraint reference_asking_runs_requests_check
  check(requests between 0 and 2000);

create or replace function tcg.guard_reference_asking_run() returns trigger
language plpgsql security invoker set search_path=pg_catalog as $$
declare used integer;
begin
 if not coalesce(tcg.is_platform_admin(),false)
    or new.actor_user_id is distinct from tcg.current_user_id() then
   raise exception 'ASKING_RUN_ADMIN_REQUIRED' using errcode='42501';
 end if;
 if TG_OP='INSERT' then
   if new.requests<>0 or new.status<>'RUNNING' then
     raise exception 'ASKING_RUN_MUST_START_EMPTY';
   end if;
   return new;
 end if;
 if (new.id,new.actor_user_id,new.started_at,new.budget_day)
      is distinct from (old.id,old.actor_user_id,old.started_at,old.budget_day)
    or old.status<>'RUNNING' then
   raise exception 'ASKING_RUN_IDENTITY_OR_FINAL_STATE_IMMUTABLE';
 end if;
 if new.requests not in (old.requests,old.requests+1) then
   raise exception 'ASKING_REQUEST_COUNTER_MUST_INCREMENT_BY_ONE';
 end if;
 if new.requests=old.requests+1 then
   if new.status<>'RUNNING'
      or new.budget_day<>(clock_timestamp() at time zone 'UTC')::date then
     raise exception 'ASKING_REQUEST_RUN_NOT_CURRENT';
   end if;
   perform pg_advisory_xact_lock(hashtextextended('tcg.reference_asking_daily_budget',0));
   select coalesce(sum(requests),0)::integer into used
     from tcg.reference_asking_runs where budget_day=new.budget_day;
   if used>=2000 then
     raise exception 'ASKING_DAILY_REQUEST_BUDGET_EXHAUSTED';
   end if;
 end if;
 return new;
end;$$;
revoke all on function tcg.guard_reference_asking_run() from public,anon,authenticated,tcg_api;

comment on table tcg.reference_asking_runs is
 'Durable UTC-day request reservations, including failed attempts; global hard cap 2000. Commit each reservation before HTTP.';

commit;
