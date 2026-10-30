begin;

-- Return only public stock aggregates, including other sellers in the same pool.
-- The caller must own the exact personal copy being withdrawn. No foreign
-- inventory identifiers, prices or ownership details leave this function.
create or replace function tcg.shopify_personal_withdrawal_target(p_link_id uuid, p_owner_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
  target tcg.shopify_inventory_links%rowtype;
  remaining_quantity integer;
  product_has_stock boolean;
begin
  if not exists (
    select 1 from tcg.owner_memberships m join tcg.owners o on o.id=m.owner_id
    where m.user_id=tcg.current_user_id() and m.owner_id=p_owner_id
      and m.active and o.active
  ) then
    raise exception 'Active inventory owner required' using errcode='42501';
  end if;
  select l.* into target from tcg.shopify_inventory_links l
  join tcg.inventory_items i on i.id=l.inventory_id and i.owner_id=l.owner_id
  where l.id=p_link_id and l.owner_id=p_owner_id and not l.test_mode
    and l.sync_state in ('DRAFT','PUBLISHED','ERROR')
    and i.sale_intent='PERSONAL_COLLECTION' and i.status not in ('SOLD','RESERVED');
  if not found then
    raise exception 'Personal inventory link changed; refresh and retry' using errcode='40001';
  end if;
  select count(*) filter(where l.shopify_variant_gid=target.shopify_variant_gid
                          and l.shopify_location_gid=target.shopify_location_gid)::integer,
         count(*)>0
  into remaining_quantity,product_has_stock
  from tcg.shopify_inventory_links l
  join tcg.inventory_items i on i.id=l.inventory_id and i.owner_id=l.owner_id
  where l.shop_domain=target.shop_domain and l.shopify_product_gid=target.shopify_product_gid
    and l.id<>target.id and not l.test_mode and l.sync_state='PUBLISHED'
    and l.reserved_order_reference is null and l.reserved_line_reference is null
    and i.status='APPROVED' and i.sale_intent='FOR_SALE';
  return jsonb_build_object('quantity',remaining_quantity,
    'status',case when product_has_stock then 'ACTIVE' else 'DRAFT' end);
end;
$function$;
revoke all on function tcg.shopify_personal_withdrawal_target(uuid,uuid) from public;
grant execute on function tcg.shopify_personal_withdrawal_target(uuid,uuid) to tcg_api;

commit;
