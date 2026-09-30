begin;

alter table tcg.automation_events
    add column if not exists superseded_at timestamptz,
    add column if not exists superseded_reason text;

alter table tcg.automation_events
    drop constraint if exists automation_events_status_check;

alter table tcg.automation_events
    add constraint automation_events_status_check
    check (
      status = any(array[
        'PENDING'::text,
        'DISPATCHING'::text,
        'DELIVERED'::text,
        'DEAD_LETTER'::text,
        'SUPERSEDED'::text
      ])
    );

alter table tcg.automation_events
    drop constraint if exists automation_events_terminal_check;

alter table tcg.automation_events
    add constraint automation_events_terminal_check
    check (
      (
        status='DELIVERED'
        and delivered_at is not null
        and dead_lettered_at is null
        and superseded_at is null
      )
      or
      (
        status='DEAD_LETTER'
        and dead_lettered_at is not null
        and delivered_at is null
        and superseded_at is null
      )
      or
      (
        status='SUPERSEDED'
        and superseded_at is not null
        and delivered_at is null
        and dead_lettered_at is null
      )
      or
      (
        status in ('PENDING','DISPATCHING')
        and delivered_at is null
        and dead_lettered_at is null
        and superseded_at is null
      )
    );

alter table tcg.automation_events
    drop constraint if exists automation_events_superseded_reason_check;

alter table tcg.automation_events
    add constraint automation_events_superseded_reason_check
    check (
      (status='SUPERSEDED' and char_length(btrim(coalesce(superseded_reason,''))) between 8 and 500)
      or
      (status<>'SUPERSEDED' and superseded_reason is null)
    );


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

    with candidates as (
        select ae.id
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
    ),
    before_rows as (
        select ae.*
        from tcg.automation_events ae
        join candidates c on c.id=ae.id
    ),
    updated as (
        update tcg.automation_events ae
        set status='SUPERSEDED',
            superseded_at=clock_timestamp(),
            superseded_reason=v_reason,
            next_attempt_at='infinity'::timestamptz,
            leased_by=null,
            lease_until=null,
            last_error_code=null,
            updated_at=clock_timestamp()
        from candidates c
        where ae.id=c.id
        returning ae.*
    ),
    audited as (
        insert into tcg.audit_events(
          actor,request_id,action,entity_type,entity_id,old_values,new_values
        )
        select
          v_actor,
          null,
          'AUTOMATION_EVENT_SUPERSEDED',
          'AUTOMATION_EVENT',
          u.id,
          jsonb_build_object(
            'status',b.status,
            'event_type',b.event_type,
            'idempotency_key',b.idempotency_key,
            'next_attempt_at',b.next_attempt_at
          ),
          jsonb_build_object(
            'status',u.status,
            'event_type',u.event_type,
            'idempotency_key',u.idempotency_key,
            'superseded_at',u.superseded_at,
            'superseded_reason',u.superseded_reason
          )
        from updated u
        join before_rows b on b.id=u.id
        returning entity_id
    )
    select count(*)::integer into v_count from audited;

    return jsonb_build_object(
      'superseded_count',v_count,
      'reason',v_reason
    );
end
$function$;

revoke all on function tcg.supersede_published_inventory_approved_events(text,text,integer) from public;
revoke all on function tcg.supersede_published_inventory_approved_events(text,text,integer) from anon, authenticated, service_role, tcg_auditor;
grant execute on function tcg.supersede_published_inventory_approved_events(text,text,integer) to tcg_api;

commit;
