begin;

-- Repair the backlog supersede helper so each state transition produces an audit
-- row and the returned count reflects the actual updated events.
create or replace function tcg.supersede_published_inventory_approved_events(
    p_reason text,
    p_actor text default 'automation-backlog-reconciliation',
    p_limit integer default 5000
)
returns jsonb
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
declare
    v_reason text := btrim(coalesce(p_reason,''));
    v_actor text := btrim(coalesce(p_actor,''));
    v_event record;
    v_count integer := 0;
begin
    if char_length(v_reason) < 8 or char_length(v_reason) > 500 then
        raise exception 'Supersede reason must be between 8 and 500 characters'
            using errcode='22023';
    end if;
    if char_length(v_actor) < 3 or char_length(v_actor) > 120 then
        raise exception 'Supersede actor must be between 3 and 120 characters'
            using errcode='22023';
    end if;
    if p_limit < 1 or p_limit > 10000 then
        raise exception 'Supersede limit must be between 1 and 10000'
            using errcode='22023';
    end if;

    for v_event in
        select
          ae.id,
          ae.event_type,
          ae.idempotency_key,
          ae.next_attempt_at
        from tcg.automation_events ae
        join tcg.inventory_items i
          on ae.aggregate_type='INVENTORY_ITEM'
         and ae.aggregate_id=i.id::text
        join tcg.shopify_inventory_links sil
          on sil.inventory_id=i.id
         and sil.sync_state='PUBLISHED'
        where ae.status='PENDING'
          and ae.event_type='inventory.approved'
        order by ae.created_at,ae.id
        limit p_limit
        for update of ae skip locked
    loop
        update tcg.automation_events
        set status='SUPERSEDED',
            superseded_at=clock_timestamp(),
            superseded_reason=v_reason,
            next_attempt_at='infinity'::timestamptz,
            leased_by=null,
            lease_until=null,
            last_error_code=null,
            updated_at=clock_timestamp()
        where id=v_event.id
          and status='PENDING';

        if found then
            insert into tcg.audit_events(
              actor,request_id,action,entity_type,entity_id,old_values,new_values
            )
            select
              v_actor,
              null,
              'AUTOMATION_EVENT_SUPERSEDED',
              'AUTOMATION_EVENT',
              ae.id,
              jsonb_build_object(
                'status','PENDING',
                'event_type',v_event.event_type,
                'idempotency_key',v_event.idempotency_key,
                'next_attempt_at',v_event.next_attempt_at
              ),
              jsonb_build_object(
                'status',ae.status,
                'event_type',ae.event_type,
                'idempotency_key',ae.idempotency_key,
                'superseded_at',ae.superseded_at,
                'superseded_reason',ae.superseded_reason
              )
            from tcg.automation_events ae
            where ae.id=v_event.id;

            v_count := v_count + 1;
        end if;
    end loop;

    return jsonb_build_object(
      'superseded_count',v_count,
      'reason',v_reason
    );
end
$function$;

revoke all on function tcg.supersede_published_inventory_approved_events(text,text,integer) from public;
revoke all on function tcg.supersede_published_inventory_approved_events(text,text,integer)
  from anon, authenticated, service_role, tcg_auditor;
grant execute on function tcg.supersede_published_inventory_approved_events(text,text,integer)
  to tcg_api;

-- One-time repair for events already superseded by the initial production
-- reconciliation where the CTE audit insert did not materialize.
insert into tcg.audit_events(
  actor,request_id,action,entity_type,entity_id,old_values,new_values
)
select
  'phase2-n8n-backlog-reconciliation-audit-repair',
  null,
  'AUTOMATION_EVENT_SUPERSEDED',
  'AUTOMATION_EVENT',
  ae.id,
  jsonb_build_object(
    'status','PENDING',
    'event_type',ae.event_type,
    'idempotency_key',ae.idempotency_key
  ),
  jsonb_build_object(
    'status',ae.status,
    'event_type',ae.event_type,
    'idempotency_key',ae.idempotency_key,
    'superseded_at',ae.superseded_at,
    'superseded_reason',ae.superseded_reason,
    'audit_repair',true
  )
from tcg.automation_events ae
where ae.status='SUPERSEDED'
  and ae.event_type='inventory.approved'
  and ae.superseded_at is not null
  and not exists (
    select 1
    from tcg.audit_events au
    where au.action='AUTOMATION_EVENT_SUPERSEDED'
      and au.entity_type='AUTOMATION_EVENT'
      and au.entity_id=ae.id
  );

commit;
