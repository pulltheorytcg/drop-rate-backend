begin;

-- These routines are available only to the backend database role, like the
-- shared eBay order recorder. Browser anon/authenticated roles receive no grant.
-- They preserve RLS on all underlying tables and never change ownership/money.
create or replace function tcg.ebay_restore_ready(p_link uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,tcg as $function$
 select exists(
   select 1 from tcg.ebay_inventory_links l
   join tcg.inventory_items i on i.id=l.inventory_id and i.owner_id=l.owner_id
   join tcg.owners o on o.id=i.owner_id and o.active
   where l.id=p_link and l.state='WITHDRAWN' and l.withdrawal_reason='SHOPIFY_RESERVED'
     and i.status='APPROVED' and i.sale_intent='FOR_SALE' and i.identity_confirmed
     and i.language is not null and i.storage_location_id is not null
     and i.acquisition_cost_minor is not null and i.store_price_minor>=100
     and l.listed_price_minor=greatest(100,(i.store_price_minor*(10000+l.markup_bps)+5000)/10000)
     and ((i.grading_company is null and i.grade is null and i.condition='Near Mint'
           and i.condition_review_status='VERIFIED_NEAR_MINT')
       or (nullif(i.grading_company,'') is not null and nullif(i.grade,'') is not null
           and i.condition_review_status='VERIFIED_GRADED'))
     and exists(select 1 from tcg.shopify_shipping_profiles sp where sp.owner_id=i.owner_id
       and sp.active and sp.profile_key=case when nullif(i.grade,'') is not null then 'GRADED_CARD' else 'RAW_CARD' end)
     and (select count(distinct m.side) from tcg.media_assets m where m.owner_id=i.owner_id
       and m.inventory_id=i.id and m.scope='INVENTORY_ITEM' and m.media_kind='IMAGE'
       and m.side in ('FRONT','BACK') and m.rights_status='VERIFIED'
       and m.approval_status='APPROVED' and m.source_status='ACTIVE' and m.revoked_at is null
       and m.shopify_file_status='READY' and m.shopify_cdn_url is not null)=2
 );
$function$;

create or replace function tcg.record_ebay_channel_result(
 p_link uuid,p_version integer,p_state text,p_offer text,p_listing text,p_reason text,p_error text
) returns boolean language plpgsql security definer set search_path=pg_catalog,tcg as $function$
declare
 link tcg.ebay_inventory_links%rowtype;
 item tcg.inventory_items%rowtype;
begin
 select * into link from tcg.ebay_inventory_links where id=p_link for update;
 if not found or link.version<>p_version or link.state='SOLD' then return false; end if;
 select * into strict item from tcg.inventory_items where id=link.inventory_id and owner_id=link.owner_id;
 if p_state='WITHDRAWN' then
   if (link.state in ('LIVE','ERROR') and
     ((p_reason='PERSONAL_COLLECTION' and item.sale_intent='PERSONAL_COLLECTION')
      or (p_reason='SHOPIFY_RESERVED' and item.status='RESERVED')
      or (p_reason='SHOPIFY_SOLD' and item.status='SOLD'))) is not true then return false; end if;
 elsif p_state='LIVE' then
   if nullif(btrim(p_listing),'') is null or not tcg.ebay_restore_ready(p_link) then return false; end if;
 elsif p_state='ERROR' then
   if link.state not in ('PUBLISHING','LIVE','WITHDRAWN','ERROR') or nullif(btrim(p_error),'') is null
     then return false; end if;
 else
   raise exception 'Unsupported eBay channel transition' using errcode='23514';
 end if;
 update tcg.ebay_inventory_links set state=p_state,
   offer_id=coalesce(nullif(btrim(p_offer),''),offer_id),
   listing_id=case when p_state='LIVE' then p_listing else listing_id end,
   withdrawal_reason=case when p_state='WITHDRAWN' then p_reason when p_state='LIVE' then null else withdrawal_reason end,
   withdrawn_at=case when p_state='WITHDRAWN' then clock_timestamp() when p_state='LIVE' then null else withdrawn_at end,
   last_verified_at=case when p_state in ('WITHDRAWN','LIVE') then clock_timestamp() else last_verified_at end,
   last_error_code=case when p_state='ERROR' then left(p_error,120) else null end,
   version=version+1,updated_at=clock_timestamp()
 where id=p_link and version=p_version;
 return found;
end;
$function$;

create or replace function tcg.shopify_stock_after_ebay_sale(p_link uuid) returns jsonb
language plpgsql security definer set search_path=pg_catalog,tcg as $function$
declare
 target tcg.shopify_inventory_links%rowtype;
 quantity integer;
 stocked boolean;
begin
 select l.* into target from tcg.shopify_inventory_links l
 join tcg.inventory_items i on i.id=l.inventory_id and i.owner_id=l.owner_id
 join tcg.ebay_inventory_links e on e.inventory_id=i.id and e.owner_id=i.owner_id
 where l.id=p_link and not l.test_mode and i.status='SOLD' and e.state='SOLD';
 if not found then raise exception 'Recorded eBay sale required' using errcode='23514'; end if;
 select count(*) filter(where l.shopify_variant_gid=target.shopify_variant_gid
   and l.shopify_location_gid=target.shopify_location_gid)::integer,count(*)>0 into quantity,stocked
 from tcg.shopify_inventory_links l
 join tcg.inventory_items i on i.id=l.inventory_id and i.owner_id=l.owner_id
 where l.shop_domain=target.shop_domain and l.shopify_product_gid=target.shopify_product_gid
   and l.id<>target.id and not l.test_mode and l.sync_state='PUBLISHED'
   and l.reserved_order_reference is null and l.reserved_line_reference is null
   and i.status='APPROVED' and i.sale_intent='FOR_SALE';
 return jsonb_build_object('quantity',quantity,'status',case when stocked then 'ACTIVE' else 'DRAFT' end);
end;
$function$;

revoke all on function tcg.ebay_restore_ready(uuid) from public,anon,authenticated;
revoke all on function tcg.record_ebay_channel_result(uuid,integer,text,text,text,text,text) from public,anon,authenticated;
revoke all on function tcg.shopify_stock_after_ebay_sale(uuid) from public,anon,authenticated;
grant execute on function tcg.ebay_restore_ready(uuid) to tcg_api;
grant execute on function tcg.record_ebay_channel_result(uuid,integer,text,text,text,text,text) to tcg_api;
grant execute on function tcg.shopify_stock_after_ebay_sale(uuid) to tcg_api;

commit;
