begin;

create or replace function tcg.shopify_orders_for_reconciliation(
  p_window_start timestamptz
)
returns table(
  id uuid,
  source_reference text,
  order_number text,
  status text,
  placed_at timestamptz
)
language plpgsql
stable
security definer
set search_path=pg_catalog
as $function$
begin
  if p_window_start is null then
    raise exception 'p_window_start is required'
      using errcode='22023';
  end if;

  return query
  select
    o.id,
    o.source_reference,
    o.order_number,
    o.status,
    o.placed_at
  from tcg.orders o
  where o.source='SHOPIFY'
    and o.placed_at >= p_window_start
  order by o.placed_at,o.id;
end;
$function$;

revoke all on function tcg.shopify_orders_for_reconciliation(timestamptz) from public;
revoke all on function tcg.shopify_orders_for_reconciliation(timestamptz) from anon;
revoke all on function tcg.shopify_orders_for_reconciliation(timestamptz) from authenticated;
revoke all on function tcg.shopify_orders_for_reconciliation(timestamptz) from service_role;
revoke all on function tcg.shopify_orders_for_reconciliation(timestamptz) from tcg_auditor;
grant execute on function tcg.shopify_orders_for_reconciliation(timestamptz) to tcg_api;

commit;
