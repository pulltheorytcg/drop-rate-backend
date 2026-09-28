-- Durable automation-event outbox for n8n and other orchestration consumers.
-- Core business state remains in PostgreSQL/FastAPI. This table records immutable
-- domain-event envelopes plus mutable delivery metadata. n8n never receives direct
-- table access; workers use narrow SECURITY DEFINER functions.

create table tcg.automation_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references tcg.owners(id) on delete restrict,
  event_type text not null
    check (
      char_length(event_type) between 3 and 120
      and event_type ~ '^[a-z][a-z0-9_.-]+$'
    ),
  schema_version integer not null default 1
    check (schema_version between 1 and 1000),
  aggregate_type text not null
    check (
      char_length(aggregate_type) between 2 and 80
      and aggregate_type ~ '^[A-Z][A-Z0-9_]+$'
    ),
  aggregate_id text not null
    check (char_length(aggregate_id) between 1 and 255),
  idempotency_key text not null
    check (char_length(idempotency_key) between 8 and 255),
  payload jsonb not null
    check (jsonb_typeof(payload)='object'),
  status text not null default 'PENDING'
    check (status in ('PENDING','DISPATCHING','DELIVERED','DEAD_LETTER')),
  available_at timestamptz not null default clock_timestamp(),
  next_attempt_at timestamptz not null default clock_timestamp(),
  attempt_count integer not null default 0
    check (attempt_count >= 0),
  max_attempts integer not null default 8
    check (max_attempts between 1 and 50),
  leased_by text,
  lease_until timestamptz,
  last_error_code text,
  delivered_at timestamptz,
  dead_lettered_at timestamptz,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  constraint automation_events_idempotency_uidx unique(idempotency_key),
  constraint automation_events_lease_check check (
    (status='DISPATCHING' and leased_by is not null and lease_until is not null)
    or
    (status<>'DISPATCHING' and leased_by is null and lease_until is null)
  ),
  constraint automation_events_terminal_check check (
    (status='DELIVERED' and delivered_at is not null and dead_lettered_at is null)
    or
    (status='DEAD_LETTER' and dead_lettered_at is not null and delivered_at is null)
    or
    (status in ('PENDING','DISPATCHING') and delivered_at is null and dead_lettered_at is null)
  )
);

create index automation_events_due_idx
  on tcg.automation_events(next_attempt_at,created_at)
  where status='PENDING';

create index automation_events_lease_idx
  on tcg.automation_events(lease_until)
  where status='DISPATCHING';

create index automation_events_type_created_idx
  on tcg.automation_events(event_type,created_at desc);

create index automation_events_owner_created_idx
  on tcg.automation_events(owner_id,created_at desc)
  where owner_id is not null;

alter table tcg.automation_events enable row level security;
alter table tcg.automation_events force row level security;

revoke all on tcg.automation_events from public;
revoke all on tcg.automation_events from anon;
revoke all on tcg.automation_events from authenticated;
revoke all on tcg.automation_events from service_role;
revoke all on tcg.automation_events from tcg_api;
revoke all on tcg.automation_events from tcg_auditor;


create or replace function tcg.enqueue_automation_event(
  p_owner_id uuid,
  p_event_type text,
  p_schema_version integer,
  p_aggregate_type text,
  p_aggregate_id text,
  p_idempotency_key text,
  p_payload jsonb,
  p_available_at timestamptz default clock_timestamp()
)
returns table(event_id uuid, created boolean)
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
declare
  v_existing tcg.automation_events%rowtype;
  v_id uuid;
begin
  p_event_type := lower(btrim(coalesce(p_event_type,'')));
  p_aggregate_type := upper(btrim(coalesce(p_aggregate_type,'')));
  p_aggregate_id := btrim(coalesce(p_aggregate_id,''));
  p_idempotency_key := btrim(coalesce(p_idempotency_key,''));

  if char_length(p_event_type) < 3
     or char_length(p_event_type) > 120
     or p_event_type !~ '^[a-z][a-z0-9_.-]+$' then
    raise exception 'Invalid automation event type' using errcode='22023';
  end if;
  if p_schema_version < 1 or p_schema_version > 1000 then
    raise exception 'Invalid automation schema version' using errcode='22023';
  end if;
  if char_length(p_aggregate_type) < 2
     or char_length(p_aggregate_type) > 80
     or p_aggregate_type !~ '^[A-Z][A-Z0-9_]+$' then
    raise exception 'Invalid automation aggregate type' using errcode='22023';
  end if;
  if char_length(p_aggregate_id) < 1 or char_length(p_aggregate_id) > 255 then
    raise exception 'Invalid automation aggregate ID' using errcode='22023';
  end if;
  if char_length(p_idempotency_key) < 8 or char_length(p_idempotency_key) > 255 then
    raise exception 'Invalid automation idempotency key' using errcode='22023';
  end if;
  if p_payload is null or jsonb_typeof(p_payload) <> 'object' then
    raise exception 'Automation payload must be a JSON object' using errcode='22023';
  end if;
  if p_available_at is null then
    raise exception 'Automation available_at is required' using errcode='22023';
  end if;
  if p_owner_id is not null
     and not exists(select 1 from tcg.owners where id=p_owner_id) then
    raise exception 'Automation owner does not exist' using errcode='23503';
  end if;

  select * into v_existing
  from tcg.automation_events
  where idempotency_key=p_idempotency_key;

  if found then
    if v_existing.owner_id is not distinct from p_owner_id
       and v_existing.event_type=p_event_type
       and v_existing.schema_version=p_schema_version
       and v_existing.aggregate_type=p_aggregate_type
       and v_existing.aggregate_id=p_aggregate_id
       and v_existing.payload=p_payload then
      return query select v_existing.id,false;
      return;
    end if;
    raise exception 'Automation idempotency key reused with different payload'
      using errcode='23505';
  end if;

  v_id := gen_random_uuid();

  insert into tcg.automation_events(
    id,owner_id,event_type,schema_version,aggregate_type,aggregate_id,
    idempotency_key,payload,available_at,next_attempt_at
  ) values(
    v_id,p_owner_id,p_event_type,p_schema_version,p_aggregate_type,p_aggregate_id,
    p_idempotency_key,p_payload,p_available_at,p_available_at
  )
  on conflict(idempotency_key) do nothing;

  if found then
    return query select v_id,true;
    return;
  end if;

  -- A concurrent enqueue won the unique-key race. Re-read and enforce
  -- same-key/same-envelope semantics.
  select * into v_existing
  from tcg.automation_events
  where idempotency_key=p_idempotency_key;

  if v_existing.id is null then
    raise exception 'Automation enqueue conflict state missing' using errcode='55000';
  end if;

  if v_existing.owner_id is not distinct from p_owner_id
     and v_existing.event_type=p_event_type
     and v_existing.schema_version=p_schema_version
     and v_existing.aggregate_type=p_aggregate_type
     and v_existing.aggregate_id=p_aggregate_id
     and v_existing.payload=p_payload then
    return query select v_existing.id,false;
    return;
  end if;

  raise exception 'Automation idempotency key reused with different payload'
    using errcode='23505';
end;
$function$;

revoke all on function tcg.enqueue_automation_event(
  uuid,text,integer,text,text,text,jsonb,timestamptz
) from public;
grant execute on function tcg.enqueue_automation_event(
  uuid,text,integer,text,text,text,jsonb,timestamptz
) to tcg_api;


create or replace function tcg.claim_automation_events(
  p_worker_id text,
  p_limit integer default 20,
  p_lease_seconds integer default 120
)
returns table(
  event_id uuid,
  owner_id uuid,
  event_type text,
  schema_version integer,
  aggregate_type text,
  aggregate_id text,
  idempotency_key text,
  payload jsonb,
  attempt_count integer,
  max_attempts integer,
  created_at timestamptz
)
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
begin
  p_worker_id := btrim(coalesce(p_worker_id,''));
  if char_length(p_worker_id) < 3 or char_length(p_worker_id) > 120 then
    raise exception 'Invalid automation worker ID' using errcode='22023';
  end if;
  if p_limit < 1 or p_limit > 100 then
    raise exception 'Automation claim limit must be between 1 and 100' using errcode='22023';
  end if;
  if p_lease_seconds < 30 or p_lease_seconds > 900 then
    raise exception 'Automation lease must be between 30 and 900 seconds' using errcode='22023';
  end if;

  -- Expired leases are retryable. Exhausted leases become dead letters.
  update tcg.automation_events
     set status='DEAD_LETTER',
         leased_by=null,
         lease_until=null,
         dead_lettered_at=clock_timestamp(),
         last_error_code=coalesce(last_error_code,'LEASE_EXPIRED_MAX_ATTEMPTS'),
         updated_at=clock_timestamp()
   where status='DISPATCHING'
     and lease_until <= clock_timestamp()
     and attempt_count >= max_attempts;

  update tcg.automation_events
     set status='PENDING',
         leased_by=null,
         lease_until=null,
         next_attempt_at=clock_timestamp(),
         last_error_code=coalesce(last_error_code,'LEASE_EXPIRED'),
         updated_at=clock_timestamp()
   where status='DISPATCHING'
     and lease_until <= clock_timestamp()
     and attempt_count < max_attempts;

  return query
  with candidates as (
    select ae.id
    from tcg.automation_events ae
    where ae.status='PENDING'
      and ae.available_at <= clock_timestamp()
      and ae.next_attempt_at <= clock_timestamp()
      and ae.attempt_count < ae.max_attempts
    order by ae.next_attempt_at,ae.created_at,ae.id
    for update skip locked
    limit p_limit
  ), claimed as (
    update tcg.automation_events ae
       set status='DISPATCHING',
           leased_by=p_worker_id,
           lease_until=clock_timestamp()+make_interval(secs => p_lease_seconds),
           attempt_count=ae.attempt_count+1,
           updated_at=clock_timestamp()
      from candidates c
     where ae.id=c.id
    returning ae.*
  )
  select
    c.id,c.owner_id,c.event_type,c.schema_version,c.aggregate_type,
    c.aggregate_id,c.idempotency_key,c.payload,c.attempt_count,
    c.max_attempts,c.created_at
  from claimed c
  order by c.created_at,c.id;
end;
$function$;

revoke all on function tcg.claim_automation_events(text,integer,integer) from public;
grant execute on function tcg.claim_automation_events(text,integer,integer) to tcg_api;


create or replace function tcg.ack_automation_event(
  p_event_id uuid,
  p_worker_id text
)
returns boolean
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
begin
  update tcg.automation_events
     set status='DELIVERED',
         leased_by=null,
         lease_until=null,
         delivered_at=clock_timestamp(),
         last_error_code=null,
         updated_at=clock_timestamp()
   where id=p_event_id
     and status='DISPATCHING'
     and leased_by=btrim(coalesce(p_worker_id,''))
     and lease_until > clock_timestamp();

  return found;
end;
$function$;

revoke all on function tcg.ack_automation_event(uuid,text) from public;
grant execute on function tcg.ack_automation_event(uuid,text) to tcg_api;


create or replace function tcg.fail_automation_event(
  p_event_id uuid,
  p_worker_id text,
  p_error_code text,
  p_retry_after_seconds integer default 60,
  p_force_dead_letter boolean default false
)
returns text
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
declare
  v_event tcg.automation_events%rowtype;
  v_error text;
begin
  if p_retry_after_seconds < 5 or p_retry_after_seconds > 86400 then
    raise exception 'Automation retry delay must be between 5 and 86400 seconds'
      using errcode='22023';
  end if;

  v_error := upper(left(
    regexp_replace(btrim(coalesce(p_error_code,'DISPATCH_FAILED')),'[^A-Za-z0-9_.:-]+','_','g'),
    120
  ));
  if v_error='' then
    v_error := 'DISPATCH_FAILED';
  end if;

  select * into v_event
  from tcg.automation_events
  where id=p_event_id
    and status='DISPATCHING'
    and leased_by=btrim(coalesce(p_worker_id,''))
  for update;

  if not found then
    return 'NOT_OWNED';
  end if;

  if coalesce(p_force_dead_letter,false)
     or v_event.attempt_count >= v_event.max_attempts then
    update tcg.automation_events
       set status='DEAD_LETTER',
           leased_by=null,
           lease_until=null,
           dead_lettered_at=clock_timestamp(),
           last_error_code=v_error,
           updated_at=clock_timestamp()
     where id=p_event_id;
    return 'DEAD_LETTER';
  end if;

  update tcg.automation_events
     set status='PENDING',
         leased_by=null,
         lease_until=null,
         next_attempt_at=clock_timestamp()+make_interval(secs => p_retry_after_seconds),
         last_error_code=v_error,
         updated_at=clock_timestamp()
   where id=p_event_id;

  return 'RETRY';
end;
$function$;

revoke all on function tcg.fail_automation_event(uuid,text,text,integer,boolean) from public;
grant execute on function tcg.fail_automation_event(uuid,text,text,integer,boolean) to tcg_api;


-- Emit the first launch-domain event transactionally whenever physical inventory
-- enters APPROVED. The payload intentionally excludes cost, private notes and
-- customer/owner-sensitive data; consumers fetch current facts through FastAPI.
create or replace function tcg.emit_inventory_approved_event()
returns trigger
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
declare
  v_event_key text;
begin
  if new.status <> 'APPROVED' then
    return new;
  end if;
  if tg_op='UPDATE' and old.status='APPROVED' then
    return new;
  end if;

  v_event_key := 'inventory.approved:' || new.id::text || ':v' || new.version::text;

  perform *
  from tcg.enqueue_automation_event(
    new.owner_id,
    'inventory.approved',
    1,
    'INVENTORY_ITEM',
    new.id::text,
    v_event_key,
    jsonb_build_object(
      'inventory_id',new.id,
      'inventory_code',new.inventory_code,
      'catalogue_id',new.catalogue_id,
      'status',new.status,
      'version',new.version
    ),
    clock_timestamp()
  );

  return new;
end;
$function$;

revoke all on function tcg.emit_inventory_approved_event() from public;

create trigger inventory_items_emit_approved_event_insert
after insert
on tcg.inventory_items
for each row
execute function tcg.emit_inventory_approved_event();

create trigger inventory_items_emit_approved_event_update
after update of status
on tcg.inventory_items
for each row
execute function tcg.emit_inventory_approved_event();
