begin;

create table if not exists tcg.automation_component_heartbeats (
  component_key text primary key
    check (
      char_length(component_key) between 3 and 80
      and component_key ~ '^[A-Z][A-Z0-9_]+$'
    ),
  instance_id text not null
    check (char_length(instance_id) between 3 and 120),
  component_version text
    check (component_version is null or char_length(component_version) between 1 and 80),
  last_seen_at timestamptz not null default clock_timestamp(),
  started_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp()
);

alter table tcg.automation_component_heartbeats enable row level security;
alter table tcg.automation_component_heartbeats force row level security;

revoke all on tcg.automation_component_heartbeats from public;
revoke all on tcg.automation_component_heartbeats from anon;
revoke all on tcg.automation_component_heartbeats from authenticated;
revoke all on tcg.automation_component_heartbeats from service_role;
revoke all on tcg.automation_component_heartbeats from tcg_api;
revoke all on tcg.automation_component_heartbeats from tcg_auditor;


create or replace function tcg.record_automation_component_heartbeat(
  p_component_key text,
  p_instance_id text,
  p_component_version text default null
)
returns timestamptz
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_component_key text := upper(btrim(coalesce(p_component_key,'')));
  v_instance_id text := btrim(coalesce(p_instance_id,''));
  v_component_version text := nullif(btrim(coalesce(p_component_version,'')),'');
  v_seen timestamptz := clock_timestamp();
begin
  if char_length(v_component_key) < 3
     or char_length(v_component_key) > 80
     or v_component_key !~ '^[A-Z][A-Z0-9_]+$' then
    raise exception 'Invalid automation component key' using errcode='22023';
  end if;
  if char_length(v_instance_id) < 3 or char_length(v_instance_id) > 120 then
    raise exception 'Invalid automation component instance ID' using errcode='22023';
  end if;
  if v_component_version is not null
     and char_length(v_component_version) > 80 then
    raise exception 'Invalid automation component version' using errcode='22023';
  end if;

  insert into tcg.automation_component_heartbeats(
    component_key,instance_id,component_version,last_seen_at,started_at,updated_at
  ) values(
    v_component_key,v_instance_id,v_component_version,v_seen,v_seen,v_seen
  )
  on conflict(component_key)
  do update set
    instance_id=excluded.instance_id,
    component_version=excluded.component_version,
    last_seen_at=excluded.last_seen_at,
    started_at=case
      when tcg.automation_component_heartbeats.instance_id is distinct from excluded.instance_id
      then excluded.started_at
      else tcg.automation_component_heartbeats.started_at
    end,
    updated_at=excluded.updated_at;

  return v_seen;
end;
$function$;

revoke all on function tcg.record_automation_component_heartbeat(text,text,text) from public;
revoke all on function tcg.record_automation_component_heartbeat(text,text,text)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.record_automation_component_heartbeat(text,text,text) to tcg_api;


create or replace function tcg.check_automation_dispatcher_heartbeat(
  p_alert_enabled boolean default false,
  p_threshold interval default interval '90 seconds'
)
returns table(
  healthy boolean,
  alert_enabled boolean,
  last_seen_at timestamptz,
  instance_id text,
  component_version text,
  age_seconds integer,
  alerted_founders integer,
  resolved_founders integer
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_last_seen_at timestamptz;
  v_instance_id text;
  v_component_version text;
  v_age_seconds integer;
  v_healthy boolean;
  v_alerted integer := 0;
  v_resolved integer := 0;
begin
  if p_threshold is null
     or p_threshold < interval '30 seconds'
     or p_threshold > interval '15 minutes' then
    raise exception 'Automation dispatcher heartbeat threshold must be 30 seconds to 15 minutes'
      using errcode='22023';
  end if;

  select h.last_seen_at,h.instance_id,h.component_version
    into v_last_seen_at,v_instance_id,v_component_version
    from tcg.automation_component_heartbeats h
   where h.component_key='DISPATCHER';

  v_age_seconds := case
    when v_last_seen_at is null then null
    else greatest(0,extract(epoch from (clock_timestamp()-v_last_seen_at))::integer)
  end;

  v_healthy :=
    v_last_seen_at is not null
    and v_last_seen_at >= clock_timestamp()-p_threshold;

  if coalesce(p_alert_enabled,false) and not v_healthy then
    insert into tcg.action_required_items(
      owner_id,category,code,severity,entity_type,entity_id,dedupe_key,
      title,detail,recommended_action,status,metadata
    )
    select
      o.id,
      'AUTOMATION',
      'AUTOMATION_DISPATCHER_UNHEALTHY',
      'CRITICAL',
      'OWNER',
      o.id,
      'system:automation-dispatcher-heartbeat',
      'Automation dispatcher needs attention',
      'The automation dispatcher heartbeat is missing or stale. Last seen: '
        || coalesce(v_last_seen_at::text,'never')
        || ', age seconds: ' || coalesce(v_age_seconds::text,'unknown') || '.',
      'Check the Drop Rate automation dispatcher Railway service before replaying or manually processing automation events.',
      'OPEN',
      jsonb_build_object(
        'monitor','automation_dispatcher_heartbeat',
        'threshold_seconds',extract(epoch from p_threshold)::integer,
        'last_seen_at',v_last_seen_at,
        'age_seconds',v_age_seconds,
        'instance_id',v_instance_id,
        'component_version',v_component_version
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
     where ari.code='AUTOMATION_DISPATCHER_UNHEALTHY'
       and ari.dedupe_key='system:automation-dispatcher-heartbeat'
       and ari.status='OPEN'
       and exists(
         select 1 from tcg.owners o
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
    v_last_seen_at,
    v_instance_id,
    v_component_version,
    v_age_seconds,
    v_alerted,
    v_resolved;
end;
$function$;

revoke all on function tcg.check_automation_dispatcher_heartbeat(boolean,interval) from public;
revoke all on function tcg.check_automation_dispatcher_heartbeat(boolean,interval)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.check_automation_dispatcher_heartbeat(boolean,interval) to tcg_api;

commit;
