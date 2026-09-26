alter table tcg.stripe_webhook_events
  add column if not exists attempt_count integer not null default 0
    check (attempt_count >= 0),
  add column if not exists last_attempt_at timestamptz;

create or replace function tcg.validate_stripe_payout_execution_consistency()
returns trigger
language plpgsql
set search_path to 'pg_catalog'
as $function$
declare
  request_owner uuid;
  request_amount bigint;
  request_currency text;
  account_owner uuid;
begin
  select owner_id, amount_minor, currency
  into request_owner, request_amount, request_currency
  from tcg.payout_requests
  where id = new.payout_request_id;

  if request_owner is null then
    raise exception 'Payout request does not exist'
      using errcode='23503';
  end if;

  select owner_id
  into account_owner
  from tcg.stripe_connected_accounts
  where id = new.connected_account_id;

  if account_owner is null then
    raise exception 'Stripe connected account does not exist'
      using errcode='23503';
  end if;

  if request_owner is distinct from new.owner_id
     or account_owner is distinct from new.owner_id
     or request_amount is distinct from new.amount_minor
     or request_currency is distinct from new.currency then
    raise exception 'Stripe payout execution does not match payout request owner or amount'
      using errcode='23514';
  end if;

  return new;
end;
$function$;

drop trigger if exists stripe_payout_execution_consistency_guard
  on tcg.stripe_payout_executions;
create trigger stripe_payout_execution_consistency_guard
before insert or update on tcg.stripe_payout_executions
for each row execute function tcg.validate_stripe_payout_execution_consistency();
