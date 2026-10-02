-- Backend-only processing of a signature-verified order fetched from eBay.
-- Ownership is resolved from immutable links, never supplied by a seller.
create function tcg.record_shared_ebay_order(
  p_order_reference text, p_placed_at timestamptz, p_lines jsonb
) returns jsonb language plpgsql security definer set search_path=pg_catalog
as $function$
declare
  v_order_id uuid;
  v_item_id uuid;
  v_link record;
  v_line record;
  v_count integer;
  v_ids jsonb;
begin
  if nullif(btrim(p_order_reference),'') is null or length(p_order_reference)>200
     or p_placed_at is null or jsonb_typeof(p_lines) is distinct from 'array'
     or jsonb_array_length(p_lines) not between 1 and 1000 then
    raise exception 'Invalid eBay order envelope' using errcode='23514';
  end if;
  select count(*) into v_count from jsonb_to_recordset(p_lines)
    as x(listing_id text,line_item_id text,sale_price_minor bigint,shipping_minor bigint)
    where nullif(btrim(listing_id),'') is null or nullif(btrim(line_item_id),'') is null
      or sale_price_minor is null or sale_price_minor<0
      or shipping_minor is null or shipping_minor<0;
  if v_count>0 or
     (select count(distinct x->>'listing_id') from jsonb_array_elements(p_lines) x) <> jsonb_array_length(p_lines) or
     (select count(distinct x->>'line_item_id') from jsonb_array_elements(p_lines) x) <> jsonb_array_length(p_lines) then
    raise exception 'Invalid or duplicate eBay lines' using errcode='23514';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('ebay-order:'||p_order_reference,0));
  select id into v_order_id from tcg.orders where source='EBAY' and source_reference=p_order_reference;
  if found then
    select coalesce(jsonb_agg(inventory_id order by id),'[]'::jsonb) into v_ids
      from tcg.order_items where order_id=v_order_id;
    return jsonb_build_object('action','ORDER_ALREADY_RECORDED','order_id',v_order_id,'inventory_ids',v_ids);
  end if;
  -- Lock every physical unit in a consistent order before touching money or stock.
  v_count := 0;
  for v_link in
    select l.id,l.inventory_id,i.status,i.sale_intent,l.state
    from tcg.ebay_inventory_links l
    join tcg.inventory_items i on i.id=l.inventory_id and i.owner_id=l.owner_id
    join tcg.owners o on o.id=l.owner_id and o.active
    where l.listing_id in (select x->>'listing_id' from jsonb_array_elements(p_lines) x)
    order by i.id for update of l,i
  loop
    v_count := v_count+1;
    if v_link.status<>'APPROVED' or v_link.sale_intent<>'FOR_SALE' or v_link.state not in ('LIVE','PUBLISHING') then
      return jsonb_build_object('action','CHANNEL_CONFLICT','link_id',v_link.id,
        'state',case when v_link.sale_intent<>'FOR_SALE' then 'PERSONAL_COLLECTION' else v_link.status end);
    end if;
  end loop;
  if v_count<>jsonb_array_length(p_lines) then
    raise exception 'eBay order contains an unmanaged listing' using errcode='23514';
  end if;

  perform set_config('tcg.request_id','ebay:'||p_order_reference,true);
  insert into tcg.orders(source,source_reference,order_number,currency,status,placed_at)
    values('EBAY',p_order_reference,p_order_reference,'GBP','PAID',p_placed_at) returning id into v_order_id;
  v_ids := '[]'::jsonb;
  for v_line in select * from jsonb_to_recordset(p_lines)
      as x(listing_id text,line_item_id text,sale_price_minor bigint,shipping_minor bigint)
  loop
    select l.*,i.acquisition_cost_minor into strict v_link
      from tcg.ebay_inventory_links l join tcg.inventory_items i on i.id=l.inventory_id
      where l.listing_id=v_line.listing_id;
    update tcg.inventory_items set status='SOLD',version=version+1,updated_at=clock_timestamp()
      where id=v_link.inventory_id;
    insert into tcg.order_items(order_id,inventory_id,owner_id,sale_price_minor,discount_minor,cost_basis_minor,sold_at)
      values(v_order_id,v_link.inventory_id,v_link.owner_id,v_line.sale_price_minor,0,v_link.acquisition_cost_minor,p_placed_at)
      returning id into v_item_id;
    insert into tcg.ebay_order_item_links(order_id,order_item_id,inventory_id,owner_id,created_by_user_id,ebay_order_id,ebay_line_item_id,ebay_listing_id)
      values(v_order_id,v_item_id,v_link.inventory_id,v_link.owner_id,v_link.created_by_user_id,p_order_reference,v_line.line_item_id,v_line.listing_id);
    -- Existing database triggers snapshot each owner's commission and append it.
    insert into tcg.financial_ledger_entries(owner_id,order_id,order_item_id,entry_type,amount_minor,currency,funds_status,source_key)
      values(v_link.owner_id,v_order_id,v_item_id,'SALE_REVENUE',v_line.sale_price_minor,'GBP','PENDING',
        'ebay:'||p_order_reference||':'||v_line.line_item_id||':sale');
    if v_line.shipping_minor>0 then
      insert into tcg.financial_ledger_entries(owner_id,order_id,order_item_id,entry_type,amount_minor,currency,funds_status,source_key)
        values(v_link.owner_id,v_order_id,v_item_id,'SHIPPING_REVENUE',v_line.shipping_minor,'GBP','PENDING',
          'ebay:'||p_order_reference||':'||v_line.line_item_id||':shipping');
    end if;
    update tcg.ebay_inventory_links set state='SOLD',sold_at=clock_timestamp(),last_verified_at=clock_timestamp(),
      last_error_code=null,version=version+1,updated_at=clock_timestamp() where id=v_link.id;
    update tcg.shopify_inventory_links set sync_state='SOLD',sold_at=coalesce(sold_at,clock_timestamp()),
      version=version+1,last_synced_at=clock_timestamp()
      where inventory_id=v_link.inventory_id and sync_state in ('DRAFT','PUBLISHED','ERROR');
    v_ids := v_ids || jsonb_build_array(v_link.inventory_id);
  end loop;
  insert into tcg.audit_events(actor,request_id,action,entity_type,entity_id,new_values)
    values('system:ebay','ebay:'||p_order_reference,'SHARED_EBAY_ORDER_RECORDED','ORDER',v_order_id,
      jsonb_build_object('inventory_ids',v_ids,'source_reference',p_order_reference));
  return jsonb_build_object('action','EBAY_ORDER_RECORDED','order_id',v_order_id,'inventory_ids',v_ids);
end
$function$;
revoke all on function tcg.record_shared_ebay_order(text,timestamptz,jsonb) from public,anon,authenticated;
grant execute on function tcg.record_shared_ebay_order(text,timestamptz,jsonb) to tcg_api;
