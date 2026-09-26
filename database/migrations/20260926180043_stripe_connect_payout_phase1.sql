-- Stripe Connect payout control plane, phase 1.
-- Shopify remains the customer checkout. Drop Rate remains the deterministic
-- source of truth for owner balances and settlement eligibility.

alter table tcg.payout_requests
  add column if not exists approved_at timestamptz,
  add column if not exists approved_by_user_id uuid,
  add column if not exists rejected_reason text;

create table if not exists tcg.stripe_connected_accounts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null unique references tcg.owners(id),
  created_by_user_id uuid not null,
  stripe_account_id text not null unique
    check (stripe_account_id ~ '^acct_[A-Za-z0-9]+$'),
  livemode boolean not null default false,
  account_type text not null default 'EXPRESS'
    check (account_type in ('EXPRESS')),
  country text,
  status text not null default 'CREATED'
    check (status in ('CREATED','ONBOARDING','RESTRICTED','READY','DISCONNECTED','ERROR')),
  details_submitted boolean not null default false,
  charges_enabled boolean not null default false,
  payouts_enabled boolean not null default false,
  transfers_capability_status text not null default 'UNREQUESTED'
    check (transfers_capability_status in ('UNREQUESTED','PENDING','ACTIVE','INACTIVE')),
  requirements_currently_due text[] not null default '{}',
  requirements_eventually_due text[] not null default '{}',
  requirements_past_due text[] not null default '{}',
  disabled_reason text,
  last_error_code text,
  last_synced_at timestamptz,
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp()
);

create index if not exists stripe_connected_accounts_status_idx
  on tcg.stripe_connected_accounts(status,payouts_enabled,transfers_capability_status);

create table if not exists tcg.stripe_payout_executions (
  id uuid primary key default gen_random_uuid(),
  payout_request_id uuid not null unique references tcg.payout_requests(id),
  owner_id uuid not null references tcg.owners(id),
  connected_account_id uuid not null references tcg.stripe_connected_accounts(id),
  idempotency_key text not null unique
    check (char_length(idempotency_key) between 16 and 255),
  amount_minor bigint not null check (amount_minor > 0),
  currency text not null default 'GBP' check (currency='GBP'),
  state text not null default 'PREPARED'
    check (state in (
      'PREPARED','BLOCKED','TRANSFERRED','PAYOUT_PENDING',
      'PAID','FAILED','REVERSED','CANCELLED'
    )),
  stripe_transfer_id text unique,
  stripe_payout_id text unique,
  transfer_group text not null,
  blocked_reason text,
  last_error_code text,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  submitted_at timestamptz,
  resolved_at timestamptz,
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp()
);

create index if not exists stripe_payout_executions_owner_state_idx
  on tcg.stripe_payout_executions(owner_id,state,created_at desc);

create table if not exists tcg.stripe_webhook_events (
  id uuid primary key default gen_random_uuid(),
  stripe_event_id text not null unique check (stripe_event_id ~ '^evt_[A-Za-z0-9]+$'),
  event_type text not null,
  connected_account_id text,
  livemode boolean not null,
  payload_sha256 text not null check (char_length(payload_sha256)=64),
  processing_status text not null default 'RECEIVED'
    check (processing_status in ('RECEIVED','PROCESSED','FAILED','IGNORED')),
  last_error_code text,
  received_at timestamptz not null default clock_timestamp(),
  processed_at timestamptz,
  version integer not null default 1 check (version > 0)
);

create index if not exists stripe_webhook_events_type_time_idx
  on tcg.stripe_webhook_events(event_type,received_at desc);

alter table tcg.stripe_connected_accounts enable row level security;
alter table tcg.stripe_connected_accounts force row level security;
alter table tcg.stripe_payout_executions enable row level security;
alter table tcg.stripe_payout_executions force row level security;
alter table tcg.stripe_webhook_events enable row level security;
alter table tcg.stripe_webhook_events force row level security;

revoke all on table tcg.stripe_connected_accounts from public;
revoke all on table tcg.stripe_connected_accounts from anon, authenticated;
revoke all on table tcg.stripe_payout_executions from public;
revoke all on table tcg.stripe_payout_executions from anon, authenticated;
revoke all on table tcg.stripe_webhook_events from public;
revoke all on table tcg.stripe_webhook_events from anon, authenticated;

grant select,insert,update on table tcg.stripe_connected_accounts to tcg_api;
grant select,insert,update on table tcg.stripe_payout_executions to tcg_api;
grant select,insert,update on table tcg.stripe_webhook_events to tcg_api;

drop policy if exists stripe_connected_accounts_internal on tcg.stripe_connected_accounts;
create policy stripe_connected_accounts_internal
  on tcg.stripe_connected_accounts for all to tcg_api
  using (true) with check (true);

drop policy if exists stripe_payout_executions_internal on tcg.stripe_payout_executions;
create policy stripe_payout_executions_internal
  on tcg.stripe_payout_executions for all to tcg_api
  using (true) with check (true);

drop policy if exists stripe_webhook_events_internal on tcg.stripe_webhook_events;
create policy stripe_webhook_events_internal
  on tcg.stripe_webhook_events for all to tcg_api
  using (true) with check (true);

create or replace function tcg.protect_stripe_payout_execution_identity()
returns trigger
language plpgsql
set search_path to 'pg_catalog'
as $function$
begin
  if new.payout_request_id is distinct from old.payout_request_id
     or new.owner_id is distinct from old.owner_id
     or new.connected_account_id is distinct from old.connected_account_id
     or new.idempotency_key is distinct from old.idempotency_key
     or new.amount_minor is distinct from old.amount_minor
     or new.currency is distinct from old.currency
     or new.transfer_group is distinct from old.transfer_group then
    raise exception 'Stripe payout execution identity is immutable'
      using errcode='55000';
  end if;
  return new;
end;
$function$;

drop trigger if exists stripe_payout_execution_identity_guard
  on tcg.stripe_payout_executions;
create trigger stripe_payout_execution_identity_guard
before update on tcg.stripe_payout_executions
for each row execute function tcg.protect_stripe_payout_execution_identity();
