begin;

create or replace function tcg.check_payout_scheduler_heartbeat(
  p_threshold interval default interval '90 minutes'
)
returns table(
  healthy boolean,
  last_completed_at timestamptz,
  last_status text,
  alerted_founders integer,
  resolved_founders integer
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_last_completed_at timestamptz;
  v_last_status text;
  v_healthy boolean;
  v_alerted integer := 0;
  v_resolved integer := 0;
begin
  if p_threshold is null or p_threshold < interval '30 minutes' then
    raise exception 'Payout scheduler heartbeat threshold must be at least 30 minutes'
      using errcode='22023';
  end if;

  select r.finished_at, r.status
    into v_last_completed_at, v_last_status
    from tcg.payout_scheduler_runs r
   where r.finished_at is not null
   order by r.finished_at desc
   limit 1;

  v_healthy :=
    v_last_completed_at is not null
    and v_last_status = 'SUCCESS'
    and v_last_completed_at >= clock_timestamp() - p_threshold;

  if not v_healthy then
    insert into tcg.action_required_items(
      owner_id,
      category,
      code,
      severity,
      entity_type,
      entity_id,
      dedupe_key,
      title,
      detail,
      recommended_action,
      status,
      metadata
    )
    select
      o.id,
      'SETTLEMENT',
      'PAYOUT_SCHEDULER_UNHEALTHY',
      'CRITICAL',
      'OWNER',
      o.id,
      'system:payout-scheduler-heartbeat',
      'Payout scheduler needs attention',
      'The payout scheduler heartbeat is unhealthy. Last completed run: '
        || coalesce(v_last_completed_at::text, 'never')
        || coalesce(' (' || v_last_status || ')', ''),
      'Check the drop-rate-payout-scheduler Railway service and restore successful hourly runs.',
      'OPEN',
      jsonb_build_object(
        'monitor','payout_scheduler_heartbeat',
        'threshold_seconds',extract(epoch from p_threshold)::integer,
        'last_completed_at',v_last_completed_at,
        'last_status',v_last_status
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
  else
    update tcg.action_required_items ari
       set status='RESOLVED',
           resolved_at=clock_timestamp(),
           resolved_by_user_id=null,
           updated_at=clock_timestamp(),
           version=ari.version+1
     where ari.code='PAYOUT_SCHEDULER_UNHEALTHY'
       and ari.dedupe_key='system:payout-scheduler-heartbeat'
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
    v_last_completed_at,
    v_last_status,
    v_alerted,
    v_resolved;
end;
$function$;

revoke all on function tcg.check_payout_scheduler_heartbeat(interval) from public;
revoke all on function tcg.check_payout_scheduler_heartbeat(interval) from anon;
revoke all on function tcg.check_payout_scheduler_heartbeat(interval) from authenticated;
revoke all on function tcg.check_payout_scheduler_heartbeat(interval) from service_role;
revoke all on function tcg.check_payout_scheduler_heartbeat(interval) from tcg_auditor;
grant execute on function tcg.check_payout_scheduler_heartbeat(interval) to tcg_api;

commit;
