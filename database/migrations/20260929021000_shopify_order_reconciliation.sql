begin;

create or replace function tcg.record_shopify_order_reconciliation(
  p_remote_alerts jsonb,
  p_local_only uuid[],
  p_healthy_refs text[]
)
returns table(
  opened_alerts integer,
  resolved_alerts integer
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_opened integer := 0;
  v_remote_opened integer := 0;
  v_local_opened integer := 0;
  v_resolved integer := 0;
begin
  p_remote_alerts := coalesce(p_remote_alerts, '[]'::jsonb);
  p_local_only := coalesce(p_local_only, array[]::uuid[]);
  p_healthy_refs := coalesce(p_healthy_refs, array[]::text[]);

  if jsonb_typeof(p_remote_alerts) <> 'array' then
    raise exception 'p_remote_alerts must be a JSON array'
      using errcode='22023';
  end if;
  if jsonb_array_length(p_remote_alerts) > 10000
     or cardinality(p_local_only) > 10000
     or cardinality(p_healthy_refs) > 10000 then
    raise exception 'Shopify reconciliation batch exceeds safety limit'
      using errcode='22023';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_remote_alerts) item
    where jsonb_typeof(item) <> 'object'
       or coalesce(item->>'source_reference','') !~ '^[0-9]{1,32}$'
       or length(coalesce(item->>'order_number','')) > 100
       or length(coalesce(item->>'created_at','')) > 64
       or length(coalesce(item->>'cancelled_at','')) > 64
       or length(coalesce(item->>'financial_status','')) > 64
       or coalesce(item->>'alert_code','') not in (
         'SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE',
         'SHOPIFY_ORDER_WEBHOOK_GAP'
       )
       or (
         item->>'alert_code'='SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE'
         and coalesce(item->>'severity','') <> 'CRITICAL'
       )
       or (
         item->>'alert_code'='SHOPIFY_ORDER_WEBHOOK_GAP'
         and coalesce(item->>'severity','') <> 'HIGH'
       )
  ) then
    raise exception 'Shopify reconciliation remote alert payload is invalid'
      using errcode='22023';
  end if;

  if exists (
    select 1
    from unnest(p_healthy_refs) ref
    where ref !~ '^[0-9]{1,32}$'
  ) then
    raise exception 'Shopify reconciliation healthy reference is invalid'
      using errcode='22023';
  end if;

  if exists (
    select 1
    from unnest(p_local_only) local_id
    where not exists (
      select 1
      from tcg.orders o
      where o.id=local_id
        and o.source='SHOPIFY'
    )
  ) then
    raise exception 'Shopify reconciliation local order is invalid'
      using errcode='22023';
  end if;

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
    founder.id,
    'SHOPIFY',
    remote.item->>'alert_code',
    remote.item->>'severity',
    'OWNER',
    founder.id,
    'shopify-reconciliation:remote:' || (remote.item->>'source_reference'),
    case
      when remote.item->>'alert_code'='SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE'
        then 'Paid Shopify order is missing from Drop Rate'
      else 'Shopify order webhook coverage gap'
    end,
    case
      when remote.item->>'alert_code'='SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE'
        then 'Shopify order '
          || coalesce(nullif(remote.item->>'order_number',''), remote.item->>'source_reference')
          || ' has a paid-like financial state but is not present in tcg.orders.'
      else 'Shopify order '
          || coalesce(nullif(remote.item->>'order_number',''), remote.item->>'source_reference')
          || ' is not present in tcg.orders and has no successfully processed orders/create webhook.'
    end,
    case
      when remote.item->>'alert_code'='SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE'
        then 'Review Shopify payment/webhook history immediately. Do not create ledger entries manually.'
      else 'Review Shopify webhook history and pending-order reservation state before taking recovery action.'
    end,
    'OPEN',
    jsonb_strip_nulls(jsonb_build_object(
      'source','SHOPIFY',
      'direction','SHOPIFY_ONLY',
      'source_reference',remote.item->>'source_reference',
      'order_number',nullif(remote.item->>'order_number',''),
      'created_at',nullif(remote.item->>'created_at',''),
      'cancelled_at',nullif(remote.item->>'cancelled_at',''),
      'financial_status',nullif(remote.item->>'financial_status','')
    ))
  from jsonb_array_elements(p_remote_alerts) remote(item)
  cross join tcg.owners founder
  where founder.owner_type='FOUNDER'
    and founder.active
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

  get diagnostics v_remote_opened = row_count;

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
    founder.id,
    'SHOPIFY',
    'DROP_RATE_ORDER_MISSING_IN_SHOPIFY',
    'HIGH',
    'ORDER',
    o.id,
    'shopify-reconciliation:local:' || o.source_reference,
    'Drop Rate order is missing from Shopify scan',
    'Drop Rate order '
      || coalesce(o.order_number, o.source_reference)
      || ' was not returned by Shopify for the same reconciliation window.',
    'Review Shopify order state and API visibility before changing inventory, ownership or finance records.',
    'OPEN',
    jsonb_build_object(
      'source','SHOPIFY',
      'direction','DROP_RATE_ONLY',
      'source_reference',o.source_reference,
      'order_number',o.order_number,
      'drop_rate_status',o.status,
      'placed_at',o.placed_at
    )
  from unnest(p_local_only) local_id
  join tcg.orders o
    on o.id=local_id
   and o.source='SHOPIFY'
  cross join tcg.owners founder
  where founder.owner_type='FOUNDER'
    and founder.active
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

  get diagnostics v_local_opened = row_count;
  v_opened := v_remote_opened + v_local_opened;

  update tcg.action_required_items ari
     set status='RESOLVED',
         resolved_at=clock_timestamp(),
         resolved_by_user_id=null,
         updated_at=clock_timestamp(),
         version=ari.version+1
   where ari.status='OPEN'
     and ari.code in (
       'SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE',
       'SHOPIFY_ORDER_WEBHOOK_GAP',
       'DROP_RATE_ORDER_MISSING_IN_SHOPIFY'
     )
     and ari.metadata->>'source_reference' = any(p_healthy_refs)
     and exists (
       select 1
       from tcg.owners founder
       where founder.id=ari.owner_id
         and founder.owner_type='FOUNDER'
         and founder.active
     );

  get diagnostics v_resolved = row_count;

  return query select v_opened, v_resolved;
end;
$function$;

revoke all on function tcg.record_shopify_order_reconciliation(jsonb,uuid[],text[]) from public;
revoke all on function tcg.record_shopify_order_reconciliation(jsonb,uuid[],text[]) from anon;
revoke all on function tcg.record_shopify_order_reconciliation(jsonb,uuid[],text[]) from authenticated;
revoke all on function tcg.record_shopify_order_reconciliation(jsonb,uuid[],text[]) from service_role;
revoke all on function tcg.record_shopify_order_reconciliation(jsonb,uuid[],text[]) from tcg_auditor;
grant execute on function tcg.record_shopify_order_reconciliation(jsonb,uuid[],text[]) to tcg_api;

commit;
