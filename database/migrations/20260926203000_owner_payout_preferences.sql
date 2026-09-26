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
