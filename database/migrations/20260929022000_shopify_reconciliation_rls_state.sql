begin;

create or replace function tcg.get_shopify_order_reconciliation_state(
  p_window_start timestamptz,
  p_remote_refs text[]
)
returns table(
  record_type text,
  order_id uuid,
  source_reference text,
  order_number text,
  order_status text,
  placed_at timestamptz,
  webhook_topic text,
  webhook_status text
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_remote_refs text[] := coalesce(p_remote_refs, array[]::text[]);
begin
  if p_window_start is null then
    raise exception 'Shopify reconciliation window start is required'
      using errcode='22023';
  end if;

  if p_window_start < clock_timestamp() - interval '61 days'
     or p_window_start > clock_timestamp() + interval '5 minutes' then
    raise exception 'Shopify reconciliation window start is outside safety bounds'
      using errcode='22023';
  end if;

  if cardinality(v_remote_refs) > 10000 then
    raise exception 'Shopify reconciliation remote reference batch exceeds safety limit'
      using errcode='22023';
  end if;

  if exists (
    select 1
    from unnest(v_remote_refs) ref
    where ref !~ '^[0-9]{1,32}$'
  ) then
    raise exception 'Shopify reconciliation remote reference is invalid'
      using errcode='22023';
  end if;

  return query
  select
    'ORDER'::text,
    o.id,
    o.source_reference,
    o.order_number,
    o.status::text,
    o.placed_at,
    null::text,
    null::text
  from tcg.orders o
  where o.source='SHOPIFY'
    and o.placed_at >= p_window_start

  union all

  select
    'WEBHOOK'::text,
    null::uuid,
    e.resource_id,
    null::text,
    null::text,
    null::timestamptz,
    e.topic,
    e.status
  from tcg.shopify_webhook_events e
  where e.resource_id=any(v_remote_refs)
    and e.topic in ('orders/create','orders/paid','orders/cancelled')
    and e.status in ('RECEIVED','PROCESSED','FAILED')

  order by 1,6 nulls last,3;
end;
$function$;

revoke all on function tcg.get_shopify_order_reconciliation_state(timestamptz,text[]) from public;
revoke all on function tcg.get_shopify_order_reconciliation_state(timestamptz,text[]) from anon;
revoke all on function tcg.get_shopify_order_reconciliation_state(timestamptz,text[]) from authenticated;
revoke all on function tcg.get_shopify_order_reconciliation_state(timestamptz,text[]) from service_role;
revoke all on function tcg.get_shopify_order_reconciliation_state(timestamptz,text[]) from tcg_auditor;
grant execute on function tcg.get_shopify_order_reconciliation_state(timestamptz,text[]) to tcg_api;

commit;
