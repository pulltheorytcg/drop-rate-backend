begin;

create table if not exists tcg.automation_heartbeats (
  heartbeat_key text primary key,
  workflow_version text not null,
  execution_id text not null,
  observed_at timestamptz not null,
  received_at timestamptz not null default clock_timestamp(),
  beat_count bigint not null default 1,
  constraint automation_heartbeats_key_check
    check (heartbeat_key ~ '^[a-z0-9][a-z0-9-]{1,79}$'),
  constraint automation_heartbeats_workflow_version_check
    check (char_length(workflow_version) between 1 and 80),
  constraint automation_heartbeats_execution_id_check
    check (char_length(execution_id) between 1 and 255),
  constraint automation_heartbeats_beat_count_check
    check (beat_count >= 1)
);

alter table tcg.automation_heartbeats enable row level security;

revoke all on table tcg.automation_heartbeats from public;
revoke all on table tcg.automation_heartbeats from anon;
revoke all on table tcg.automation_heartbeats from authenticated;
revoke all on table tcg.automation_heartbeats from service_role;
revoke all on table tcg.automation_heartbeats from tcg_auditor;
revoke all on table tcg.automation_heartbeats from tcg_api;

create or replace function tcg.record_automation_heartbeat(
  p_heartbeat_key text,
  p_workflow_version text,
  p_execution_id text,
  p_observed_at timestamptz
)
returns table(
  heartbeat_key text,
  received_at timestamptz,
  beat_count bigint,
  duplicate boolean
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_row tcg.automation_heartbeats%rowtype;
  v_duplicate boolean := false;
begin
  if p_heartbeat_key is null
     or p_heartbeat_key <> 'n8n-runtime' then
    raise exception 'Unsupported automation heartbeat key'
      using errcode='22023';
  end if;
  if p_workflow_version is null
     or char_length(p_workflow_version) < 1
     or char_length(p_workflow_version) > 80 then
    raise exception 'Invalid automation heartbeat workflow version'
      using errcode='22023';
  end if;
  if p_execution_id is null
     or char_length(p_execution_id) < 1
     or char_length(p_execution_id) > 255 then
    raise exception 'Invalid automation heartbeat execution ID'
      using errcode='22023';
  end if;
  if p_observed_at is null
     or p_observed_at < clock_timestamp() - interval '15 minutes'
     or p_observed_at > clock_timestamp() + interval '5 minutes' then
    raise exception 'Automation heartbeat timestamp outside accepted window'
      using errcode='22023';
  end if;

  insert into tcg.automation_heartbeats(
    heartbeat_key,
    workflow_version,
    execution_id,
    observed_at,
    received_at,
    beat_count
  ) values (
    p_heartbeat_key,
    p_workflow_version,
    p_execution_id,
    p_observed_at,
    clock_timestamp(),
    1
  )
  on conflict(heartbeat_key)
  do update set
    workflow_version=excluded.workflow_version,
    execution_id=excluded.execution_id,
    observed_at=excluded.observed_at,
    received_at=clock_timestamp(),
    beat_count=tcg.automation_heartbeats.beat_count+1
  where tcg.automation_heartbeats.execution_id is distinct from excluded.execution_id
    and excluded.observed_at > tcg.automation_heartbeats.observed_at
  returning * into v_row;

  if not found then
    select *
      into strict v_row
      from tcg.automation_heartbeats h
     where h.heartbeat_key=p_heartbeat_key;
    v_duplicate := true;
  end if;

  return query
  select
    v_row.heartbeat_key,
    v_row.received_at,
    v_row.beat_count,
    v_duplicate;
end;
$function$;

revoke all on function tcg.record_automation_heartbeat(text,text,text,timestamptz) from public;
revoke all on function tcg.record_automation_heartbeat(text,text,text,timestamptz) from anon;
revoke all on function tcg.record_automation_heartbeat(text,text,text,timestamptz) from authenticated;
revoke all on function tcg.record_automation_heartbeat(text,text,text,timestamptz) from service_role;
revoke all on function tcg.record_automation_heartbeat(text,text,text,timestamptz) from tcg_auditor;
grant execute on function tcg.record_automation_heartbeat(text,text,text,timestamptz) to tcg_api;

create or replace function tcg.check_n8n_runtime_heartbeat(
  p_alert_enabled boolean default false,
  p_stale_threshold interval default interval '20 minutes'
)
returns table(
  healthy boolean,
  alert_enabled boolean,
  last_received_at timestamptz,
  last_observed_at timestamptz,
  last_workflow_version text,
  last_execution_id text,
  beat_count bigint,
  age_seconds integer,
  alerted_founders integer,
  resolved_founders integer
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_last_received_at timestamptz;
  v_last_observed_at timestamptz;
  v_last_workflow_version text;
  v_last_execution_id text;
  v_beat_count bigint := 0;
  v_age_seconds integer;
  v_healthy boolean;
  v_alerted integer := 0;
  v_resolved integer := 0;
begin
  if p_stale_threshold is null
     or p_stale_threshold < interval '10 minutes'
     or p_stale_threshold > interval '24 hours' then
    raise exception 'n8n heartbeat threshold must be between 10 minutes and 24 hours'
      using errcode='22023';
  end if;

  select
    h.received_at,
    h.observed_at,
    h.workflow_version,
    h.execution_id,
    h.beat_count
  into
    v_last_received_at,
    v_last_observed_at,
    v_last_workflow_version,
    v_last_execution_id,
    v_beat_count
  from tcg.automation_heartbeats h
  where h.heartbeat_key='n8n-runtime';

  v_age_seconds :=
    case
      when v_last_received_at is null then null
      else greatest(
        0,
        extract(epoch from (clock_timestamp()-v_last_received_at))::integer
      )
    end;

  v_healthy :=
    v_last_received_at is not null
    and v_last_received_at >= clock_timestamp()-p_stale_threshold;

  if coalesce(p_alert_enabled,false) and not v_healthy then
    insert into tcg.action_required_items(
      owner_id,category,code,severity,entity_type,entity_id,dedupe_key,
      title,detail,recommended_action,status,metadata
    )
    select
      o.id,
      'AUTOMATION',
      'N8N_HEARTBEAT_STALE',
      'HIGH',
      'OWNER',
      o.id,
      'system:n8n-runtime-heartbeat',
      'n8n runtime heartbeat needs attention',
      'The n8n runtime heartbeat is stale. Last received: '
        || coalesce(v_last_received_at::text,'never')
        || '; age seconds=' || coalesce(v_age_seconds::text,'none') || '.',
      'Check the Drop Rate n8n Railway service, its schedule execution, and FastAPI control-plane connectivity. Do not replay business events merely to clear this heartbeat alert.',
      'OPEN',
      jsonb_build_object(
        'monitor','n8n_runtime_heartbeat',
        'threshold_seconds',extract(epoch from p_stale_threshold)::integer,
        'last_received_at',v_last_received_at,
        'last_observed_at',v_last_observed_at,
        'workflow_version',v_last_workflow_version,
        'execution_id',v_last_execution_id,
        'beat_count',v_beat_count
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
     where ari.code='N8N_HEARTBEAT_STALE'
       and ari.dedupe_key='system:n8n-runtime-heartbeat'
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
    v_last_received_at,
    v_last_observed_at,
    v_last_workflow_version,
    v_last_execution_id,
    coalesce(v_beat_count,0),
    v_age_seconds,
    v_alerted,
    v_resolved;
end;
$function$;

revoke all on function tcg.check_n8n_runtime_heartbeat(boolean,interval) from public;
revoke all on function tcg.check_n8n_runtime_heartbeat(boolean,interval) from anon;
revoke all on function tcg.check_n8n_runtime_heartbeat(boolean,interval) from authenticated;
revoke all on function tcg.check_n8n_runtime_heartbeat(boolean,interval) from service_role;
revoke all on function tcg.check_n8n_runtime_heartbeat(boolean,interval) from tcg_auditor;
grant execute on function tcg.check_n8n_runtime_heartbeat(boolean,interval) to tcg_api;

commit;
