-- Scheduled payout queue worker.
-- The scheduler only creates REQUESTED payout rows. It never moves money.
-- FastAPI/Python determines when a cycle is due; these database functions provide
-- a narrow privileged boundary and re-check financial invariants atomically.

alter table tcg.payout_requests
  add column if not exists request_origin text not null default 'MANUAL',
  add column if not exists schedule_cycle_key text,
  add column if not exists scheduled_for timestamptz;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname='payout_requests_origin_check'
      and conrelid='tcg.payout_requests'::regclass
  ) then
    alter table tcg.payout_requests
      add constraint payout_requests_origin_check
      check (request_origin in ('MANUAL','SCHEDULED'));
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname='payout_requests_schedule_fields_check'
      and conrelid='tcg.payout_requests'::regclass
  ) then
    alter table tcg.payout_requests
      add constraint payout_requests_schedule_fields_check
      check (
        (request_origin='MANUAL' and schedule_cycle_key is null and scheduled_for is null)
        or
        (
          request_origin='SCHEDULED'
          and schedule_cycle_key is not null
          and char_length(schedule_cycle_key) between 16 and 128
          and scheduled_for is not null
        )
      );
  end if;
end $$;

create unique index if not exists payout_requests_scheduled_cycle_uidx
  on tcg.payout_requests(owner_id,schedule_cycle_key)
  where request_origin='SCHEDULED';

create index if not exists payout_requests_scheduled_due_idx
  on tcg.payout_requests(request_origin,scheduled_for desc)
  where request_origin='SCHEDULED';

create or replace function tcg.payout_scheduler_candidates()
returns table(
  owner_id uuid,
  owner_type text,
  owner_active boolean,
  cadence text,
  weekday smallint,
  monthly_day smallint,
  fortnightly_anchor_date date,
  timezone text,
  preference_version integer,
  stripe_ready boolean,
  ledger_available_minor bigint,
  reserved_payout_minor bigint,
  available_to_withdraw_minor bigint
)
language sql
security definer
set search_path to 'pg_catalog'
stable
as $function$
  select
    o.id,
    o.owner_type,
    o.active,
    pp.cadence,
    pp.weekday,
    pp.monthly_day,
    pp.fortnightly_anchor_date,
    pp.timezone,
    pp.version,
    (
      sca.status='READY'
      and sca.payouts_enabled
      and sca.transfers_capability_status='ACTIVE'
    ) as stripe_ready,
    coalesce(ledger.available_minor,0)::bigint as ledger_available_minor,
    coalesce(reserved.amount_minor,0)::bigint as reserved_payout_minor,
    greatest(
      coalesce(ledger.available_minor,0) - coalesce(reserved.amount_minor,0),
      0
    )::bigint as available_to_withdraw_minor
  from tcg.payout_preferences pp
  join tcg.owners o on o.id=pp.owner_id
  left join tcg.stripe_connected_accounts sca on sca.owner_id=o.id
  left join lateral (
    select coalesce(sum(le.amount_minor),0)::bigint as available_minor
    from tcg.financial_ledger_entries le
    where le.owner_id=o.id and le.funds_status='AVAILABLE'
  ) ledger on true
  left join lateral (
    select coalesce(sum(pr.amount_minor),0)::bigint as amount_minor
    from tcg.payout_requests pr
    where pr.owner_id=o.id
      and pr.status in ('REQUESTED','APPROVED')
  ) reserved on true
  where pp.cadence <> 'MANUAL';
$function$;

revoke all on function tcg.payout_scheduler_candidates() from public;
grant execute on function tcg.payout_scheduler_candidates() to tcg_api;

create or replace function tcg.create_scheduled_payout_request(
  p_owner_id uuid,
  p_preference_version integer,
  p_cycle_key text,
  p_scheduled_for timestamptz,
  p_cadence text
)
returns table(
  payout_request_id uuid,
  created boolean,
  amount_minor bigint,
  payout_code text,
  reason text
)
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
declare
  v_owner_active boolean;
  v_pref record;
  v_stripe_ready boolean;
  v_ledger_available bigint;
  v_reserved bigint;
  v_available bigint;
  v_id uuid;
  v_code text;
  v_existing record;
begin
  if p_cycle_key is null or char_length(p_cycle_key) < 16 or char_length(p_cycle_key) > 128 then
    raise exception 'Invalid scheduled payout cycle key' using errcode='22023';
  end if;
  if p_scheduled_for is null or p_scheduled_for > clock_timestamp() then
    raise exception 'Scheduled payout cycle is not due' using errcode='22023';
  end if;
  if p_cadence not in ('DAILY','WEEKLY','FORTNIGHTLY','MONTHLY') then
    raise exception 'Invalid scheduled payout cadence' using errcode='22023';
  end if;

  select active into v_owner_active
  from tcg.owners
  where id=p_owner_id
  for update;

  if not found then
    return query select null::uuid,false,0::bigint,null::text,'OWNER_MISSING'::text;
    return;
  end if;
  if not v_owner_active then
    return query select null::uuid,false,0::bigint,null::text,'OWNER_INACTIVE'::text;
    return;
  end if;

  select * into v_pref
  from tcg.payout_preferences
  where owner_id=p_owner_id
  for update;

  if not found then
    return query select null::uuid,false,0::bigint,null::text,'PREFERENCE_MISSING'::text;
    return;
  end if;
  if v_pref.version <> p_preference_version or v_pref.cadence <> p_cadence then
    return query select null::uuid,false,0::bigint,null::text,'PREFERENCE_CHANGED'::text;
    return;
  end if;
  if v_pref.cadence='MANUAL' then
    return query select null::uuid,false,0::bigint,null::text,'MANUAL_ONLY'::text;
    return;
  end if;

  select
    (status='READY' and payouts_enabled and transfers_capability_status='ACTIVE')
  into v_stripe_ready
  from tcg.stripe_connected_accounts
  where owner_id=p_owner_id;

  if coalesce(v_stripe_ready,false) is not true then
    return query select null::uuid,false,0::bigint,null::text,'STRIPE_NOT_READY'::text;
    return;
  end if;

  select id,payout_code,amount_minor into v_existing
  from tcg.payout_requests
  where owner_id=p_owner_id
    and request_origin='SCHEDULED'
    and schedule_cycle_key=p_cycle_key
  limit 1;

  if found then
    return query select
      v_existing.id,false,v_existing.amount_minor,v_existing.payout_code,'DUPLICATE_CYCLE'::text;
    return;
  end if;

  select coalesce(sum(amount_minor),0)::bigint into v_ledger_available
  from tcg.financial_ledger_entries
  where owner_id=p_owner_id and funds_status='AVAILABLE';

  select coalesce(sum(amount_minor),0)::bigint into v_reserved
  from tcg.payout_requests
  where owner_id=p_owner_id and status in ('REQUESTED','APPROVED');

  v_available := greatest(coalesce(v_ledger_available,0)-coalesce(v_reserved,0),0);
  if v_available <= 0 then
    return query select null::uuid,false,0::bigint,null::text,'NO_AVAILABLE_BALANCE'::text;
    return;
  end if;

  v_id := gen_random_uuid();
  v_code := 'PAY-' || to_char(clock_timestamp() at time zone 'UTC','YYYY')
            || '-' || upper(substr(replace(v_id::text,'-',''),1,8));

  insert into tcg.payout_requests(
    id,owner_id,payout_code,amount_minor,currency,status,notes,
    request_origin,schedule_cycle_key,scheduled_for
  )
  values(
    v_id,p_owner_id,v_code,v_available,'GBP','REQUESTED',
    'Automatically queued from ' || p_cadence || ' payout preference',
    'SCHEDULED',p_cycle_key,p_scheduled_for
  )
  on conflict do nothing;

  if not found then
    select id,payout_code,amount_minor into v_existing
    from tcg.payout_requests
    where owner_id=p_owner_id
      and request_origin='SCHEDULED'
      and schedule_cycle_key=p_cycle_key
    limit 1;
    return query select
      v_existing.id,false,v_existing.amount_minor,v_existing.payout_code,'DUPLICATE_CYCLE'::text;
    return;
  end if;

  insert into tcg.audit_events(
    actor,request_id,action,entity_type,entity_id,old_values,new_values
  ) values(
    'system:payout_scheduler',
    p_cycle_key,
    'SCHEDULED_PAYOUT_REQUEST_CREATED',
    'PAYOUT_REQUEST',
    v_id,
    null,
    jsonb_build_object(
      'owner_id',p_owner_id,
      'amount_minor',v_available,
      'currency','GBP',
      'cadence',p_cadence,
      'scheduled_for',p_scheduled_for,
      'schedule_cycle_key',p_cycle_key
    )
  );

  return query select v_id,true,v_available,v_code,'CREATED'::text;
end;
$function$;

revoke all on function tcg.create_scheduled_payout_request(
  uuid,integer,text,timestamptz,text
) from public;
grant execute on function tcg.create_scheduled_payout_request(
  uuid,integer,text,timestamptz,text
) to tcg_api;
