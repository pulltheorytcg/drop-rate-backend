begin;

create or replace function tcg.shopify_order_automation_snapshot(
  p_order_id uuid
)
returns jsonb
language sql
stable
security definer
set search_path=pg_catalog
as $function$
  select jsonb_build_object(
    'order_id',o.id,
    'source_reference',o.source_reference,
    'status',o.status,
    'currency',o.currency,
    'item_count',(
      select count(*)::int
      from tcg.order_items oi
      where oi.order_id=o.id
    ),
    'owner_count',(
      select count(distinct oi.owner_id)::int
      from tcg.order_items oi
      where oi.order_id=o.id
    ),
    'sold_inventory_count',(
      select count(*)::int
      from tcg.order_items oi
      join tcg.inventory_items i on i.id=oi.inventory_id
      where oi.order_id=o.id
        and i.status='SOLD'
    ),
    'sold_shopify_link_count',(
      select count(*)::int
      from tcg.order_items oi
      join tcg.shopify_inventory_links sil on sil.inventory_id=oi.inventory_id
      where oi.order_id=o.id
        and sil.sync_state='SOLD'
        and sil.sold_at is not null
    ),
    'shopify_order_item_link_count',(
      select count(*)::int
      from tcg.order_items oi
      join tcg.shopify_order_item_links soil on soil.order_item_id=oi.id
      where oi.order_id=o.id
    ),
    'owner_mismatch_count',(
      select count(*)::int
      from tcg.order_items oi
      join tcg.inventory_items i on i.id=oi.inventory_id
      where oi.order_id=o.id
        and oi.owner_id<>i.owner_id
    ),
    'ledger_owner_mismatch_count',(
      select count(*)::int
      from tcg.financial_ledger_entries le
      join tcg.order_items oi on oi.id=le.order_item_id
      where le.order_id=o.id
        and le.owner_id<>oi.owner_id
    ),
    'ledger_entry_count',(
      select count(*)::int
      from tcg.financial_ledger_entries le
      where le.order_id=o.id
    )
  )
  from tcg.orders o
  where o.id=p_order_id
    and o.source='SHOPIFY'
  limit 1
$function$;

revoke all on function tcg.shopify_order_automation_snapshot(uuid) from public;
revoke all on function tcg.shopify_order_automation_snapshot(uuid)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.shopify_order_automation_snapshot(uuid) to tcg_api;

commit;
