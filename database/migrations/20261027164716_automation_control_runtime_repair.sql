begin;

-- Live ledger: n8n_runtime_heartbeat version 20260930044501.
-- Reviewed source: 20260930054500_n8n_runtime_heartbeat.sql.
-- Keep the existing heartbeat signature and monotonic/idempotent behavior.
-- This migration installs capabilities only; it does not call either function.
do $guard$
begin
  if exists (select 1 from pg_roles where rolname='tcg_api' and (rolsuper or rolbypassrls)) then
    raise exception 'Automation runtime must remain a restricted role';
  end if;
  if exists (
    select 1 from pg_class
    where oid = any(array['tcg.owners'::regclass, 'tcg.automation_runs'::regclass,
      'tcg.action_required_items'::regclass, 'tcg.automation_heartbeats'::regclass])
      and not relrowsecurity
  ) then
    raise exception 'Automation owner and control tables must retain RLS';
  end if;
  if has_table_privilege('tcg_api','tcg.automation_heartbeats','SELECT,INSERT,UPDATE,DELETE')
     or has_table_privilege('tcg_api','tcg.automation_runs','UPDATE,DELETE') then
    raise exception 'Automation runtime table permissions must remain restricted';
  end if;
  if not exists (
    select 1 from pg_constraint c join pg_index i on i.indexrelid=c.conindid
    where c.conrelid='tcg.automation_heartbeats'::regclass
      and c.contype='p' and c.conname='automation_heartbeats_pkey'
      and not c.condeferrable and i.indisprimary and i.indisunique
      and i.indisvalid and i.indisready and i.indislive and i.indimmediate
      and i.indpred is null and i.indexprs is null
      and c.conkey=array[(select a.attnum from pg_attribute a
        where a.attrelid=c.conrelid and a.attname='heartbeat_key')]
  ) then
    raise exception 'Existing automation heartbeat primary key is not the reviewed key';
  end if;
  if exists (
    with expected(relation_id,key_columns) as (values
        ('tcg.automation_runs'::regclass, array['job_type','owner_id','run_key']::text[]),
        ('tcg.action_required_items'::regclass, array['dedupe_key','owner_id']::text[])
      ),
    arbiters as (
      select expected.relation_id,i.indimmediate
      from expected join pg_index i on i.indrelid=expected.relation_id
      where i.indisunique and i.indisvalid and i.indisready and i.indislive
        and not i.indisexclusion
        and i.indpred is null and i.indexprs is null
        and i.indnkeyatts=cardinality(expected.key_columns)
        and (
          select array_agg(a.attname::text order by a.attname::text)
          from unnest(i.indkey) with ordinality k(attnum,key_position)
          join pg_attribute a on a.attrelid=i.indrelid and a.attnum=k.attnum
          where k.key_position <= i.indnkeyatts
        )=expected.key_columns
    )
    select 1 from expected
    where not exists (select 1 from arbiters a
                      where a.relation_id=expected.relation_id and a.indimmediate)
       or exists (select 1 from arbiters a
                  where a.relation_id=expected.relation_id and not a.indimmediate)
  ) then
    raise exception 'Automation receipt and alert conflict keys must be immediate valid unique indexes';
  end if;
end;
$guard$;

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
  on conflict on constraint automation_heartbeats_pkey
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

create schema if not exists tcg_private authorization postgres;
revoke all on schema tcg_private from public,anon,authenticated;
grant usage on schema tcg_private to tcg_api;

-- The backend verifies the exact request HMAC before invoking this capability.
-- No caller-selected actor, SQL, alert severity, category, entity or recipient
-- list is accepted. A global receipt resolves current active founders here;
-- an explicitly scoped receipt must name an existing active owner.
create function tcg_private.record_automation_execution_receipt(
  p_workflow_key text,
  p_workflow_version text,
  p_execution_id text,
  p_status text,
  p_idempotency_key text,
  p_occurred_at timestamptz,
  p_owner_id uuid,
  p_event_id uuid,
  p_error_code text,
  p_error_message text
)
returns table(
  owner_receipts_inserted integer,
  duplicate_owner_receipts integer,
  action_required_ids uuid[]
)
language plpgsql
security definer
set search_path=pg_catalog
set lock_timeout='2s'
as $function$
declare
  v_owner record;
  v_run_id uuid;
  v_action_id uuid;
  v_inserted integer := 0;
  v_duplicates integer := 0;
  v_recipients integer := 0;
  v_actions uuid[] := array[]::uuid[];
  v_payload jsonb;
begin
  if p_workflow_key is null or p_workflow_key !~ '^[a-z0-9][a-z0-9-]{1,119}$'
     or p_workflow_version is null or char_length(p_workflow_version) not between 1 and 80
     or p_execution_id is null or char_length(p_execution_id) not between 1 and 255
     or p_status is null or p_status not in ('SUCCEEDED','FAILED')
     or p_idempotency_key is null or char_length(p_idempotency_key) not between 1 and 255
     or p_occurred_at is null or not isfinite(p_occurred_at)
     or char_length(p_error_code) > 120 or char_length(p_error_message) > 1200
     or (p_status='FAILED' and nullif(btrim(coalesce(p_error_code,'')),'') is null
         and nullif(btrim(coalesce(p_error_message,'')),'') is null) then
    raise exception 'Invalid automation execution receipt' using errcode='22023';
  end if;

  v_payload := jsonb_build_object(
    'workflow_key',p_workflow_key,'workflow_version',p_workflow_version,
    'execution_id',p_execution_id,'status',p_status,
    'idempotency_key',p_idempotency_key,'event_id',p_event_id,
    'error_code',p_error_code,'error_message',p_error_message,
    'occurred_at',p_occurred_at
  );

  -- Hold the selected owner rows against deactivation through this atomic write.
  -- Ordering keeps global fanout and action upserts consistent across callers.
  for v_owner in
    select o.id
    from tcg.owners o
    where o.active and (
      (p_owner_id is null and o.owner_type='FOUNDER') or o.id=p_owner_id
    )
    order by o.created_at,o.id
    for share
  loop
    v_recipients := v_recipients + 1;
    insert into tcg.automation_runs as ar(owner_id,job_type,run_key,initiated_by,result)
    values(v_owner.id,'N8N:' || p_workflow_key,p_idempotency_key,'N8N',v_payload)
    on conflict(owner_id,job_type,run_key) do nothing
    returning ar.id into v_run_id;

    if not found then
      v_duplicates := v_duplicates + 1;
      continue;
    end if;
    v_inserted := v_inserted + 1;

    if p_status='FAILED' then
      -- OWNER is the existing allowed entity used by the other system monitors.
      -- Workflow identity remains in the dedupe key and immutable receipt data.
      insert into tcg.action_required_items as ari(
        owner_id,category,code,severity,entity_type,entity_id,dedupe_key,
        title,detail,recommended_action,status,metadata
      ) values (
        v_owner.id,'AUTOMATION','N8N_WORKFLOW_FAILED','HIGH','OWNER',v_owner.id,
        'n8n-workflow-failed:' || p_workflow_key,
        'Automation workflow failed: ' || p_workflow_key,
        left(coalesce(nullif(btrim(p_error_code),''),'N8N_WORKFLOW_FAILED') || ': '
          || coalesce(nullif(btrim(p_error_message),''),'Workflow execution failed'),2000),
        'Review the n8n execution and backend/provider health. Replay only after the underlying cause is understood.',
        'OPEN',v_payload || jsonb_build_object('source','n8n-control-plane')
      )
      on conflict(owner_id,dedupe_key) do update set
        category=excluded.category,code=excluded.code,severity=excluded.severity,
        entity_type=excluded.entity_type,entity_id=excluded.entity_id,
        title=excluded.title,detail=excluded.detail,recommended_action=excluded.recommended_action,
        status='OPEN',metadata=excluded.metadata,last_seen_at=clock_timestamp(),
        resolved_at=null,resolved_by_user_id=null,updated_at=clock_timestamp(),version=ari.version+1
      returning ari.id into v_action_id;
      v_actions := array_append(v_actions,v_action_id);
    end if;
  end loop;

  if v_recipients=0 then
    if p_owner_id is not null then
      raise exception 'Automation receipt owner is not active' using errcode='22023';
    end if;
    raise exception 'No active founder owners available' using errcode='55000';
  end if;

  return query select v_inserted,v_duplicates,v_actions;
end;
$function$;

alter function tcg_private.record_automation_execution_receipt(text,text,text,text,text,timestamptz,uuid,uuid,text,text)
  owner to postgres;
revoke all on function tcg_private.record_automation_execution_receipt(text,text,text,text,text,timestamptz,uuid,uuid,text,text)
  from public,anon,authenticated,service_role,tcg_auditor,tcg_api;
grant execute on function tcg_private.record_automation_execution_receipt(text,text,text,text,text,timestamptz,uuid,uuid,text,text)
  to tcg_api;

comment on function tcg_private.record_automation_execution_receipt(text,text,text,text,text,timestamptz,uuid,uuid,text,text)
  is 'Backend-only HMAC-authenticated automation receipts. Resolves active recipients and atomically records append-only receipts and fixed owner-scoped failure alerts without an impersonated user or table-grant changes.';

commit;
