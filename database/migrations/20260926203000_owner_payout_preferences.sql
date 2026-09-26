-- Owner-selectable payout cadence.
-- Drop Rate remains the source of truth for payout timing and eligibility.
-- Stripe executes payouts only after deterministic backend checks.

create table if not exists tcg.payout_preferences (
  owner_id uuid primary key references tcg.owners(id),
  cadence text not null default 'MANUAL'
    check (cadence in ('MANUAL','DAILY','WEEKLY','FORTNIGHTLY','MONTHLY')),
  weekday smallint
    check (weekday is null or weekday between 0 and 6),
  monthly_day smallint
    check (monthly_day is null or monthly_day between 1 and 31),
  fortnightly_anchor_date date,
  timezone text not null default 'Europe/London'
    check (timezone = 'Europe/London'),
  updated_by_user_id uuid,
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  check (
    (cadence in ('MANUAL','DAILY') and weekday is null and monthly_day is null and fortnightly_anchor_date is null)
    or (cadence = 'WEEKLY' and weekday is not null and monthly_day is null and fortnightly_anchor_date is null)
    or (cadence = 'FORTNIGHTLY' and weekday is not null and monthly_day is null and fortnightly_anchor_date is not null)
    or (cadence = 'MONTHLY' and weekday is null and monthly_day is not null and fortnightly_anchor_date is null)
  )
);

create index if not exists payout_preferences_cadence_idx
  on tcg.payout_preferences(cadence, updated_at desc);

alter table tcg.payout_preferences enable row level security;
alter table tcg.payout_preferences force row level security;

revoke all on table tcg.payout_preferences from public;
revoke all on table tcg.payout_preferences from anon, authenticated;
grant select,insert,update on table tcg.payout_preferences to tcg_api;

drop policy if exists payout_preferences_owner_scope on tcg.payout_preferences;
create policy payout_preferences_owner_scope
  on tcg.payout_preferences for all to tcg_api
  using (
    owner_id in (select o.id from tcg.owners o)
  )
  with check (
    owner_id in (select o.id from tcg.owners o)
  );


create or replace function tcg.audit_payout_preference_change()
returns trigger
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
begin
  insert into tcg.audit_events(
    actor,request_id,action,entity_type,entity_id,old_values,new_values
  ) values(
    coalesce(nullif(current_setting('tcg.user_id',true),''),session_user::text),
    nullif(current_setting('tcg.request_id',true),''),
    'PAYOUT_PREFERENCE_CHANGED',
    'OWNER',
    new.owner_id,
    case when tg_op='UPDATE' then jsonb_build_object(
      'cadence',old.cadence,
      'weekday',old.weekday,
      'monthly_day',old.monthly_day,
      'fortnightly_anchor_date',old.fortnightly_anchor_date
    ) else null end,
    jsonb_build_object(
      'cadence',new.cadence,
      'weekday',new.weekday,
      'monthly_day',new.monthly_day,
      'fortnightly_anchor_date',new.fortnightly_anchor_date
    )
  );
  return null;
end;
$function$;

drop trigger if exists payout_preferences_audit on tcg.payout_preferences;
create trigger payout_preferences_audit
after insert or update on tcg.payout_preferences
for each row execute function tcg.audit_payout_preference_change();
