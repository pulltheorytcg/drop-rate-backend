begin;

create or replace function tcg.check_n8n_workflow_heartbeat(
  p_alert_enabled boolean default false,
  p_threshold interval default interval '15 minutes'
)
returns table(
  healthy boolean,
  alert_enabled boolean,
  last_succeeded_at timestamptz,
  age_seconds integer,
  alerted_founders integer,
  resolved_founders integer
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_last_succeeded_at timestamptz;
  v_age_seconds integer;
  v_healthy boolean;
  v_alerted integer := 0;
  v_resolved integer := 0;
begin
  if p_threshold is null
     or p_threshold < interval '10 minutes'
     or p_threshold > interval '6 hours' then
    raise exception 'n8n workflow heartbeat threshold must be between 10 minutes and 6 hours'
      using errcode='22023';
  end if;

  select max(ar.created_at)
    into v_last_succeeded_at
    from tcg.automation_runs ar
   where ar.job_type='N8N:workflow-heartbeat'
     and ar.initiated_by='N8N'
     and ar.result->>'status'='SUCCEEDED'
     and ar.result->>'workflow_key'='workflow-heartbeat';

  if v_last_succeeded_at is not null then
    v_age_seconds := greatest(
      0,
      extract(epoch from (clock_timestamp() - v_last_succeeded_at))::integer
    );
  end if;

  v_healthy :=
    v_last_succeeded_at is not null
    and v_last_succeeded_at >= clock_timestamp() - p_threshold;

  if p_alert_enabled and not v_healthy then
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
      'AUTOMATION',
      'N8N_HEARTBEAT_STALE',
      'HIGH',
      'OWNER',
      o.id,
      'system:n8n-workflow-heartbeat',
      'n8n workflow heartbeat is stale',
      'The durable n8n workflow heartbeat has not succeeded within the configured threshold. Last success: '
        || coalesce(v_last_succeeded_at::text,'never'),
      'Check the drop-rate-n8n-e840 Railway service, DR-92 schedule registration, DR-91 receipt delivery, and FastAPI/Postgres health before replaying work.',
      'OPEN',
      jsonb_build_object(
        'monitor','n8n_workflow_heartbeat',
        'threshold_seconds',extract(epoch from p_threshold)::integer,
        'last_succeeded_at',v_last_succeeded_at,
        'age_seconds',v_age_seconds
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
  elsif p_alert_enabled and v_healthy then
    update tcg.action_required_items ari
       set status='RESOLVED',
           resolved_at=clock_timestamp(),
           resolved_by_user_id=null,
           updated_at=clock_timestamp(),
           version=ari.version+1
     where ari.code='N8N_HEARTBEAT_STALE'
       and ari.dedupe_key='system:n8n-workflow-heartbeat'
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
    p_alert_enabled,
    v_last_succeeded_at,
    v_age_seconds,
    v_alerted,
    v_resolved;
end;
$function$;

revoke all on function tcg.check_n8n_workflow_heartbeat(boolean,interval) from public;
revoke all on function tcg.check_n8n_workflow_heartbeat(boolean,interval)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.check_n8n_workflow_heartbeat(boolean,interval) to tcg_api;

commit;
