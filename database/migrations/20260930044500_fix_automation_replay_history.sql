begin;

create or replace function tcg.replay_dead_letter_automation_event(
  p_event_id uuid,
  p_actor_user_id uuid,
  p_reason text,
  p_request_id text
)
returns jsonb
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_reason text := btrim(coalesce(p_reason,''));
  v_request_id text := nullif(btrim(coalesce(p_request_id,'')),'');
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
  if v_request_id is not null and char_length(v_request_id) > 255 then
    raise exception 'Replay request ID must be at most 255 characters'
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
  if v_event.attempt_count >= 50 then
    raise exception 'Automation event replay attempt ceiling reached'
      using errcode='22023';
  end if;

  v_actor := 'user:' || p_actor_user_id::text;

  update tcg.automation_events
     set status='PENDING',
         next_attempt_at=clock_timestamp(),
         max_attempts=greatest(max_attempts,attempt_count+1),
         leased_by=null,
         lease_until=null,
         last_error_code='MANUAL_REPLAY_REQUESTED',
         dead_lettered_at=null,
         updated_at=clock_timestamp()
   where id=p_event_id
     and status='DEAD_LETTER';

  if not found then
    raise exception 'Automation event changed during replay'
      using errcode='40001';
  end if;

  insert into tcg.audit_events(
    actor,request_id,action,entity_type,entity_id,old_values,new_values
  )
  select
    v_actor,
    v_request_id,
    'AUTOMATION_EVENT_REPLAY_REQUESTED',
    'AUTOMATION_EVENT',
    ae.id,
    jsonb_build_object(
      'status',v_event.status,
      'attempt_count',v_event.attempt_count,
      'max_attempts',v_event.max_attempts,
      'last_error_code',v_event.last_error_code,
      'dead_lettered_at',v_event.dead_lettered_at,
      'next_attempt_at',v_event.next_attempt_at
    ),
    jsonb_build_object(
      'status',ae.status,
      'attempt_count',ae.attempt_count,
      'max_attempts',ae.max_attempts,
      'last_error_code',ae.last_error_code,
      'next_attempt_at',ae.next_attempt_at,
      'replay_reason',v_reason
    )
  from tcg.automation_events ae
  where ae.id=p_event_id;

  return (
    select jsonb_build_object(
      'event_id',ae.id,
      'event_type',ae.event_type,
      'previous_status','DEAD_LETTER',
      'status',ae.status,
      'attempt_count',ae.attempt_count,
      'max_attempts',ae.max_attempts,
      'next_attempt_at',ae.next_attempt_at,
      'reason',v_reason
    )
    from tcg.automation_events ae
    where ae.id=p_event_id
  );
end;
$function$;

revoke all on function tcg.replay_dead_letter_automation_event(uuid,uuid,text,text) from public;
revoke all on function tcg.replay_dead_letter_automation_event(uuid,uuid,text,text)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.replay_dead_letter_automation_event(uuid,uuid,text,text) to tcg_api;


-- Backwards-compatible wrapper during rollout. It keeps the same guarded,
-- history-preserving semantics but has no request trace. New API code uses
-- the four-argument function above.
create or replace function tcg.replay_dead_letter_automation_event(
  p_event_id uuid,
  p_actor_user_id uuid,
  p_reason text
)
returns jsonb
language sql
security definer
set search_path=pg_catalog
as $function$
  select tcg.replay_dead_letter_automation_event(
    p_event_id,
    p_actor_user_id,
    p_reason,
    null::text
  );
$function$;

revoke all on function tcg.replay_dead_letter_automation_event(uuid,uuid,text) from public;
revoke all on function tcg.replay_dead_letter_automation_event(uuid,uuid,text)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.replay_dead_letter_automation_event(uuid,uuid,text) to tcg_api;

commit;
