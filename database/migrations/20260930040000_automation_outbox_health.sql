begin;

create or replace function tcg.check_automation_outbox_health(
  p_alert_enabled boolean default false,
  p_pending_age_threshold interval default interval '30 minutes'
)
returns table(
  healthy boolean,
  alert_enabled boolean,
  pending_count integer,
  due_count integer,
  dispatching_count integer,
  dead_letter_count integer,
  oldest_pending_at timestamptz,
  oldest_pending_age_seconds integer,
  stale_dispatching_count integer,
  alerted_founders integer,
  resolved_founders integer
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_pending_count integer := 0;
  v_due_count integer := 0;
  v_dispatching_count integer := 0;
  v_dead_letter_count integer := 0;
  v_oldest_pending_at timestamptz;
  v_oldest_pending_age_seconds integer;
  v_stale_dispatching_count integer := 0;
  v_healthy boolean;
  v_alerted integer := 0;
  v_resolved integer := 0;
begin
  if p_pending_age_threshold is null
     or p_pending_age_threshold < interval '5 minutes'
     or p_pending_age_threshold > interval '24 hours' then
    raise exception 'Automation pending-age threshold must be between 5 minutes and 24 hours'
      using errcode='22023';
  end if;

  select
    count(*) filter (where ae.status='PENDING')::integer,
    count(*) filter (
      where ae.status='PENDING'
        and ae.available_at <= clock_timestamp()
        and ae.next_attempt_at <= clock_timestamp()
    )::integer,
    count(*) filter (where ae.status='DISPATCHING')::integer,
    count(*) filter (where ae.status='DEAD_LETTER')::integer,
    min(ae.created_at) filter (where ae.status='PENDING'),
    count(*) filter (
      where ae.status='DISPATCHING'
        and ae.lease_until <= clock_timestamp()
    )::integer
  into
    v_pending_count,
    v_due_count,
    v_dispatching_count,
    v_dead_letter_count,
    v_oldest_pending_at,
    v_stale_dispatching_count
  from tcg.automation_events ae;

  v_oldest_pending_age_seconds :=
    case
      when v_oldest_pending_at is null then null
      else greatest(
        0,
        extract(epoch from (clock_timestamp()-v_oldest_pending_at))::integer
      )
    end;

  v_healthy :=
    v_dead_letter_count = 0
    and v_stale_dispatching_count = 0
    and (
      v_oldest_pending_at is null
      or v_oldest_pending_at >= clock_timestamp()-p_pending_age_threshold
    );

  if coalesce(p_alert_enabled,false) and not v_healthy then
    insert into tcg.action_required_items(
      owner_id,category,code,severity,entity_type,entity_id,dedupe_key,
      title,detail,recommended_action,status,metadata
    )
    select
      o.id,
      'AUTOMATION',
      'AUTOMATION_OUTBOX_UNHEALTHY',
      'HIGH',
      'OWNER',
      o.id,
      'system:automation-outbox-health',
      'Automation outbox needs attention',
      'Automation outbox is unhealthy. Pending=' || v_pending_count::text
        || ', due=' || v_due_count::text
        || ', dispatching=' || v_dispatching_count::text
        || ', dead-letter=' || v_dead_letter_count::text
        || ', stale leases=' || v_stale_dispatching_count::text
        || ', oldest pending age seconds='
        || coalesce(v_oldest_pending_age_seconds::text,'none') || '.',
      'Review dispatcher/n8n health and backlog disposition. Replay or supersede events only through the audited automation recovery path.',
      'OPEN',
      jsonb_build_object(
        'monitor','automation_outbox_health',
        'pending_count',v_pending_count,
        'due_count',v_due_count,
        'dispatching_count',v_dispatching_count,
        'dead_letter_count',v_dead_letter_count,
        'oldest_pending_at',v_oldest_pending_at,
        'oldest_pending_age_seconds',v_oldest_pending_age_seconds,
        'stale_dispatching_count',v_stale_dispatching_count,
        'threshold_seconds',extract(epoch from p_pending_age_threshold)::integer
      )
    from tcg.owners o
    where o.owner_type='FOUNDER'
      and o.active
    on conflict(owner_id,dedupe_key)
    do update set
      category=excluded.category,
      code=excluded.code,
      severity=excluded.severity,
      entity_type=excluded.entity_type,
      entity_id=excluded.entity_id,
      title=excluded.title,
      detail=excluded.detail,
      recommended_action=excluded.recommended_action,
      status='OPEN',
      metadata=excluded.metadata,
      last_seen_at=clock_timestamp(),
      resolved_at=null,
      resolved_by_user_id=null,
      updated_at=clock_timestamp(),
      version=tcg.action_required_items.version+1;

    get diagnostics v_alerted = row_count;
  elsif coalesce(p_alert_enabled,false) and v_healthy then
    update tcg.action_required_items ari
       set status='RESOLVED',
           resolved_at=clock_timestamp(),
           resolved_by_user_id=null,
           updated_at=clock_timestamp(),
           version=ari.version+1
     where ari.code='AUTOMATION_OUTBOX_UNHEALTHY'
       and ari.dedupe_key='system:automation-outbox-health'
       and ari.status='OPEN'
       and exists (
         select 1
         from tcg.owners o
         where o.id=ari.owner_id
           and o.owner_type='FOUNDER'
           and o.active
       );
    get diagnostics v_resolved = row_count;
  end if;

  return query
  select
    v_healthy,
    coalesce(p_alert_enabled,false),
    v_pending_count,
    v_due_count,
    v_dispatching_count,
    v_dead_letter_count,
    v_oldest_pending_at,
    v_oldest_pending_age_seconds,
    v_stale_dispatching_count,
    v_alerted,
    v_resolved;
end;
$function$;

revoke all on function tcg.check_automation_outbox_health(boolean,interval) from public;
revoke all on function tcg.check_automation_outbox_health(boolean,interval) from anon;
revoke all on function tcg.check_automation_outbox_health(boolean,interval) from authenticated;
revoke all on function tcg.check_automation_outbox_health(boolean,interval) from service_role;
revoke all on function tcg.check_automation_outbox_health(boolean,interval) from tcg_auditor;
grant execute on function tcg.check_automation_outbox_health(boolean,interval) to tcg_api;

commit;
