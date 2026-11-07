-- Integration acceptance against the real schema. Always roll back all fixtures,
-- ledger rows, audit rows and outbox events; no provider calls are made.
begin;
do $test$
declare
  a uuid; b uuid; user_id uuid; catalogue uuid; ia uuid; ib uuid;
  suffix text := gen_random_uuid()::text;
  result jsonb; replay jsonb; lines jsonb; recorded uuid;
begin
  select f.user_id into strict user_id from tcg.founder_app_accounts f where founder_slot=1 and active;
  select id into catalogue from tcg.catalogue_products where product_type='CARD' limit 1;
  if catalogue is null then raise exception 'Card catalogue fixture unavailable'; end if;
  insert into tcg.owners(display_name,owner_type) values('Rollback seller A '||suffix,'CONSIGNOR') returning id into a;
  insert into tcg.owners(display_name,owner_type) values('Rollback seller B '||suffix,'CONSIGNOR') returning id into b;
  insert into tcg.inventory_items(inventory_code,catalogue_id,owner_id,acquisition_cost_minor,acquisition_date,
    currency,condition,language,store_price_minor,identity_confirmed,status,sale_intent)
    values('TEST-A-'||suffix,catalogue,a,100,current_date,'GBP','Near Mint','English',1000,true,'APPROVED','FOR_SALE') returning id into ia;
  insert into tcg.inventory_items(inventory_code,catalogue_id,owner_id,acquisition_cost_minor,acquisition_date,
    currency,condition,language,store_price_minor,identity_confirmed,status,sale_intent)
    values('TEST-B-'||suffix,catalogue,b,200,current_date,'GBP','Near Mint','English',2000,true,'APPROVED','FOR_SALE') returning id into ib;
  insert into tcg.ebay_inventory_links(inventory_id,owner_id,created_by_user_id,sku,marketplace_id,category_id,state,
    listed_price_minor,inventory_version_snapshot,listing_id)
    values(ia,a,user_id,'TEST-A-'||suffix,'EBAY_GB','183454','LIVE',1000,1,'listing-a-'||suffix),
          (ib,b,user_id,'TEST-B-'||suffix,'EBAY_GB','183454','LIVE',2000,1,'listing-b-'||suffix);
  lines := jsonb_build_array(
    jsonb_build_object('listing_id','listing-a-'||suffix,'line_item_id','a','sale_price_minor',1000,'shipping_minor',167),
    jsonb_build_object('listing_id','listing-b-'||suffix,'line_item_id','b','sale_price_minor',2000,'shipping_minor',332));
  result := tcg.record_shared_ebay_order('rollback-'||suffix,now(),lines);
  if result->>'action'<>'EBAY_ORDER_RECORDED' then raise exception 'Order was not recorded: %',result; end if;
  recorded := (result->>'order_id')::uuid;
  if (select count(*) from tcg.order_items where order_id=recorded)<>2 then raise exception 'Missing order lines'; end if;
  if (select sum(amount_minor) from tcg.financial_ledger_entries where order_id=recorded and owner_id=a)<>1067 then raise exception 'Seller A allocation incorrect'; end if;
  if (select sum(amount_minor) from tcg.financial_ledger_entries where order_id=recorded and owner_id=b)<>2132 then raise exception 'Seller B allocation incorrect'; end if;
  if (select count(*) from tcg.inventory_items where id in (ia,ib) and status='SOLD')<>2 then raise exception 'Stock not sold atomically'; end if;
  replay := tcg.record_shared_ebay_order('rollback-'||suffix,now(),lines);
  if replay->>'action'<>'ORDER_ALREADY_RECORDED' or replay->>'order_id'<>result->>'order_id' then raise exception 'Replay failed'; end if;
  if (select count(*) from tcg.financial_ledger_entries where order_id=recorded)<>6 then raise exception 'Replay duplicated money'; end if;
  result := tcg.record_shared_ebay_order('conflict-'||suffix,now(),lines);
  if result->>'action'<>'CHANNEL_CONFLICT' then raise exception 'Sold stock accepted twice'; end if;
  if exists(select 1 from tcg.orders where source_reference='conflict-'||suffix) then raise exception 'Conflict left a partial order'; end if;
end
$test$;
select 'PASS: mixed owners, exact shipping, commissions, stock, replay and conflict rollback' as result;
rollback;
