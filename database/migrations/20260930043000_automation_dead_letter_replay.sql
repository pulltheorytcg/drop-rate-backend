begin;

create or replace function tcg.list_automation_outbox_events(
  p_status text default null,
  p_event_type text default null,
  p_limit integer default 100
)
returns table(
  event_id uuid,
  owner_id uuid,
  event_type text,
  schema_version integer,
  aggregate_type text,
  aggregate_id text,
  idempotency_key text,
  status text,
  attempt_count integer,
  max_attempts integer,
  available_at timestamptz,
  next_attempt_at timestamptz,
  created_at timestamptz,
  updated_at timestamptz,
  delivered_at timestamptz,
  dead_lettered_at timestamptz,
  superseded_at timestamptz,
  last_error_code text,
  superseded_reason text
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_status text := nullif(upper(btrim(coalesce(p_status,''))),'');
  v_event_type text := nullif(lower(btrim(coalesce(p_event_type,''))),'');
begin
  if p_limit < 1 or p_limit > 500 then
    raise exception 'Automation event list limit must be between 1 and 500'
      using errcode='22023';
  end if;
  if v_status is not null and v_status not in (
    'PENDING','DISPATCHING','DELIVERED','DEAD_LETTER','SUPERSEDED'
  ) then
    raise exception 'Invalid automation event status filter'
      using errcode='22023';
  end if;
  if v_event_type is not null
     and (
       char_length(v_event_type) < 3
       or char_length(v_event_type) > 120
       or v_event_type !~ '^[a-z][a-z0-9_.-]+$'
     ) then
    raise exception 'Invalid automation event type filter'
      using errcode='22023';
  end if;

  return query
  select
    ae.id,
    ae.owner_id,
    ae.event_type,
    ae.schema_version,
    ae.aggregate_type,
    ae.aggregate_id,
    ae.idempotency_key,
    ae.status,
    ae.attempt_count,
    ae.max_attempts,
    ae.available_at,
    ae.next_attempt_at,
    ae.created_at,
    ae.updated_at,
    ae.delivered_at,
    ae.dead_lettered_at,
    ae.superseded_at,
    ae.last_error_code,
    ae.superseded_reason
  from tcg.automation_events ae
  where (v_status is null or ae.status=v_status)
    and (v_event_type is null or ae.event_type=v_event_type)
  order by ae.created_at desc,ae.id desc
  limit p_limit;
end;
$function$;

revoke all on function tcg.list_automation_outbox_events(text,text,integer) from public;
revoke all on function tcg.list_automation_outbox_events(text,text,integer)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.list_automation_outbox_events(text,text,integer) to tcg_api;


create or replace function tcg.replay_dead_letter_automation_event(
  p_event_id uuid,
  p_reason text,
  p_actor text
)
returns jsonb
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_event tcg.automation_events%rowtype;
  v_reason text := btrim(coalesce(p_reason,''));
  v_actor text := btrim(coalesce(p_actor,''));
  v_before jsonb;
begin
  if char_length(v_reason) < 8 or char_length(v_reason) > 500 then
    raise exception 'Replay reason must be between 8 and 500 characters'
      using errcode='22023';
  end if;
  if char_length(v_actor) < 3 or char_length(v_actor) > 120 then
    raise exception 'Replay actor must be between 3 and 120 characters'
      using errcode='22023';
  end if;

  select * into v_event
  from tcg.automation_events
  where id=p_event_id
  for update;

  if not found then
    raise exception 'Automation event not found' using errcode='P0002';
  end if;
  if v_event.status <> 'DEAD_LETTER' then
    raise exception 'Only DEAD_LETTER automation events may be replayed'
      using errcode='22023';
  end if;
  if v_event.attempt_count >= 50 then
    raise exception 'Automation event replay attempt ceiling reached'
      using errcode='22023';
  end if;

  v_before := jsonb_build_object(
    'status',v_event.status,
    'attempt_count',v_event.attempt_count,
    'max_attempts',v_event.max_attempts,
    'dead_lettered_at',v_event.dead_lettered_at,
    'last_error_code',v_event.last_error_code,
    'next_attempt_at',v_event.next_attempt_at
  );

  update tcg.automation_events
     set status='PENDING',
         next_attempt_at=clock_timestamp(),
         max_attempts=greatest(max_attempts,attempt_count+1),
         leased_by=null,
         lease_until=null,
         dead_lettered_at=null,
         last_error_code='MANUAL_REPLAY_REQUESTED',
         updated_at=clock_timestamp()
   where id=p_event_id;

  insert into tcg.audit_events(
    actor,request_id,action,entity_type,entity_id,old_values,new_values
  )
  select
    v_actor,
    null,
    'AUTOMATION_EVENT_REPLAY_REQUESTED',
    'AUTOMATION_EVENT',
    ae.id,
    v_before,
    jsonb_build_object(
      'status',ae.status,
      'attempt_count',ae.attempt_count,
      'max_attempts',ae.max_attempts,
      'next_attempt_at',ae.next_attempt_at,
      'last_error_code',ae.last_error_code,
      'replay_reason',v_reason
    )
  from tcg.automation_events ae
  where ae.id=p_event_id;

  return (
    select jsonb_build_object(
      'event_id',ae.id,
      'status',ae.status,
      'event_type',ae.event_type,
      'attempt_count',ae.attempt_count,
      'max_attempts',ae.max_attempts,
      'next_attempt_at',ae.next_attempt_at,
      'replay_reason',v_reason
    )
    from tcg.automation_events ae
    where ae.id=p_event_id
  );
end;
$function$;

revoke all on function tcg.replay_dead_letter_automation_event(uuid,text,text) from public;
revoke all on function tcg.replay_dead_letter_automation_event(uuid,text,text)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.replay_dead_letter_automation_event(uuid,text,text) to tcg_api;

commit;
