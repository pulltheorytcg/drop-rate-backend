begin;

create or replace function tcg.list_automation_dead_letters(
  p_limit integer default 100,
  p_offset integer default 0
)
returns table(
  event_id uuid,
  owner_id uuid,
  event_type text,
  schema_version integer,
  aggregate_type text,
  aggregate_id text,
  idempotency_key text,
  attempt_count integer,
  max_attempts integer,
  last_error_code text,
  created_at timestamptz,
  updated_at timestamptz,
  dead_lettered_at timestamptz
)
language plpgsql
security definer
set search_path=pg_catalog
stable
as $function$
begin
  if p_limit < 1 or p_limit > 200 then
    raise exception 'Automation dead-letter limit must be between 1 and 200'
      using errcode='22023';
  end if;
  if p_offset < 0 or p_offset > 1000000 then
    raise exception 'Automation dead-letter offset is invalid'
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
    ae.attempt_count,
    ae.max_attempts,
    ae.last_error_code,
    ae.created_at,
    ae.updated_at,
    ae.dead_lettered_at
  from tcg.automation_events ae
  where ae.status='DEAD_LETTER'
  order by ae.dead_lettered_at desc nulls last,ae.created_at,ae.id
  limit p_limit offset p_offset;
end;
$function$;

revoke all on function tcg.list_automation_dead_letters(integer,integer) from public;
revoke all on function tcg.list_automation_dead_letters(integer,integer)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.list_automation_dead_letters(integer,integer) to tcg_api;


create or replace function tcg.replay_dead_letter_automation_event(
  p_event_id uuid,
  p_actor_user_id uuid,
  p_reason text
)
returns jsonb
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_reason text := btrim(coalesce(p_reason,''));
  v_event tcg.automation_events%rowtype;
  v_actor text;
begin
  if p_event_id is null or p_actor_user_id is null then
    raise exception 'Event ID and actor user ID are required'
      using errcode='22023';
  end if;
  if char_length(v_reason) < 8 or char_length(v_reason) > 500 then
    raise exception 'Replay reason must be between 8 and 500 characters'
      using errcode='22023';
  end if;

  if not exists(
    select 1
    from tcg.owner_memberships m
    join tcg.owners o on o.id=m.owner_id
    where m.user_id=p_actor_user_id
      and m.active
      and m.role='PLATFORM_ADMIN'
      and o.active
      and o.owner_type='FOUNDER'
  ) then
    raise exception 'Platform administrator access required'
      using errcode='42501';
  end if;

  select *
    into v_event
    from tcg.automation_events
   where id=p_event_id
   for update;

  if not found then
    raise exception 'Automation event not found'
      using errcode='P0002';
  end if;

  if v_event.status <> 'DEAD_LETTER' then
    raise exception 'Only DEAD_LETTER automation events may be replayed'
      using errcode='55000';
  end if;

  v_actor := 'user:' || p_actor_user_id::text;

  update tcg.automation_events
     set status='PENDING',
         next_attempt_at=clock_timestamp(),
         attempt_count=0,
         leased_by=null,
         lease_until=null,
         last_error_code=null,
         dead_lettered_at=null,
         delivered_at=null,
         superseded_at=null,
         superseded_reason=null,
         updated_at=clock_timestamp()
   where id=p_event_id
     and status='DEAD_LETTER';

  if not found then
    raise exception 'Automation event changed during replay'
      using errcode='40001';
  end if;

  insert into tcg.audit_events(
    actor,request_id,action,entity_type,entity_id,old_values,new_values
  ) values (
    v_actor,
    null,
    'AUTOMATION_EVENT_REPLAYED',
    'AUTOMATION_EVENT',
    p_event_id,
    jsonb_build_object(
      'status',v_event.status,
      'attempt_count',v_event.attempt_count,
      'max_attempts',v_event.max_attempts,
      'last_error_code',v_event.last_error_code,
      'dead_lettered_at',v_event.dead_lettered_at
    ),
    jsonb_build_object(
      'status','PENDING',
      'attempt_count',0,
      'max_attempts',v_event.max_attempts,
      'replay_reason',v_reason
    )
  );

  return jsonb_build_object(
    'event_id',p_event_id,
    'event_type',v_event.event_type,
    'previous_status','DEAD_LETTER',
    'status','PENDING',
    'attempt_count',0,
    'max_attempts',v_event.max_attempts,
    'reason',v_reason
  );
end;
$function$;

revoke all on function tcg.replay_dead_letter_automation_event(uuid,uuid,text) from public;
revoke all on function tcg.replay_dead_letter_automation_event(uuid,uuid,text)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.replay_dead_letter_automation_event(uuid,uuid,text) to tcg_api;

commit;
