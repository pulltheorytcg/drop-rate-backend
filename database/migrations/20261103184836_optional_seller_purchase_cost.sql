begin;

-- Purchase cost is optional for every seller and physical product type.
-- Keep unknown cost NULL in reservations and sales; never rewrite an existing
-- cost, commission snapshot, financial entry or physical-copy history.
alter table tcg.order_items alter column cost_basis_minor drop not null;
alter table tcg.inventory_reservations alter column acquisition_cost_minor_snapshot drop not null;

-- The existing trigger now permits unknown cost for approved managed stock
-- too. Identity, owner, active sale and dispatch checks remain fail-closed.
-- The audited seller-held sealed exception still governs stock without a
-- registered storage location; optional cost does not widen that exception.
create or replace function tcg.validate_optional_consignment_cost()
returns trigger language plpgsql security invoker set search_path=pg_catalog as $$
begin
  if new.cost_basis_minor is null and not exists (
    select 1 from tcg.inventory_items i
    join tcg.owners o on o.id=i.owner_id
    join tcg.catalogue_products p on p.id=i.catalogue_id
    where i.id=new.inventory_id and i.owner_id=new.owner_id
      and o.owner_type in ('FOUNDER','CONSIGNOR') and o.active
      and i.identity_confirmed and i.status in ('APPROVED','RESERVED','SOLD')
      and i.sale_intent='FOR_SALE'
      and (i.storage_location_id is not null or (
        o.owner_type='CONSIGNOR' and p.product_type='SEALED' and i.seal_status='SEALED'
        and i.language=p.language
        and i.source_record->'seller_held_approval' @> jsonb_build_object(
          'owner_id',i.owner_id,'catalogue_id',i.catalogue_id,
          'language',i.language,'name',p.name,'set_name',p.set_name,'variant',p.variant)
        and nullif(i.source_record->'seller_held_approval'->>'actor_user_id','') is not null
      ))
  ) then
    raise exception 'Sale requires the approved physical copy, its owner and a confirmed dispatch location'
      using errcode='23514';
  end if;
  return new;
end;
$$;
revoke all on function tcg.validate_optional_consignment_cost() from public;

-- Restoring an eBay listing after another channel's reservation is released
-- uses the same required publication checks, without a purchase-cost gate.
create or replace function tcg.ebay_restore_ready(p_link uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,tcg as $function$
 select exists(
   select 1 from tcg.ebay_inventory_links l
   join tcg.inventory_items i on i.id=l.inventory_id and i.owner_id=l.owner_id
   join tcg.owners o on o.id=i.owner_id and o.active
   where l.id=p_link and l.state='WITHDRAWN' and l.withdrawal_reason='SHOPIFY_RESERVED'
     and i.status='APPROVED' and i.sale_intent='FOR_SALE' and i.identity_confirmed
     and i.language is not null and i.storage_location_id is not null
     and i.store_price_minor>=100
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
revoke all on function tcg.ebay_restore_ready(uuid) from public,anon,authenticated;
grant execute on function tcg.ebay_restore_ready(uuid) to tcg_api;

commit;
