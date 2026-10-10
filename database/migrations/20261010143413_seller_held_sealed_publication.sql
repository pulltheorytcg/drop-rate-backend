begin;

-- The API can append audited seller approval provenance; owner RLS is unchanged.
grant update(source_record) on tcg.inventory_items to tcg_api;

-- Unknown seller acquisition cost is genuinely unknown, not invented as zero.
-- Payouts and commission remain based on proceeds; profit stays incomplete.
alter table tcg.order_items alter column cost_basis_minor drop not null;

create or replace function tcg.validate_optional_consignment_cost()
returns trigger language plpgsql security invoker set search_path=pg_catalog as $$
begin
  if new.cost_basis_minor is null and not exists (
    select 1 from tcg.inventory_items i
    join tcg.owners o on o.id=i.owner_id
    join tcg.catalogue_products p on p.id=i.catalogue_id
    where i.id=new.inventory_id and i.owner_id=new.owner_id
      and o.owner_type='CONSIGNOR' and p.product_type='SEALED'
      and i.identity_confirmed and i.seal_status='SEALED'
      and i.language=p.language and i.status in ('APPROVED','RESERVED','SOLD') and i.sale_intent='FOR_SALE'
      and i.source_record->'seller_held_approval' @> jsonb_build_object(
        'owner_id',i.owner_id,'catalogue_id',i.catalogue_id,
        'language',i.language,'name',p.name,'set_name',p.set_name,'variant',p.variant)
      and nullif(i.source_record->'seller_held_approval'->>'actor_user_id','') is not null
  ) then
    raise exception 'Missing acquisition cost requires exact seller-held consignment approval'
      using errcode='23514';
  end if;
  return new;
end;
$$;
revoke all on function tcg.validate_optional_consignment_cost() from public;
drop trigger if exists order_item_optional_consignment_cost on tcg.order_items;
create trigger order_item_optional_consignment_cost before insert on tcg.order_items
for each row execute function tcg.validate_optional_consignment_cost();

-- Preserve the existing publication function and add the sealed canonical scope.
CREATE OR REPLACE FUNCTION tcg.shopify_publication_context(p_inventory_id uuid, p_owner_id uuid)
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog'
AS $function$
    select case
        when i.id is null then null
        else jsonb_build_object(
            'item',
            to_jsonb(i)
            || jsonb_build_object(
                'product_type', p.product_type,
                'game', p.game,
                'name', p.name,
                'set_name', p.set_name,
                'card_number', p.card_number,
                'variant', p.variant,
                'rarity', p.rarity,
                'catalogue_language', p.language,
                'registered_location_id', sl.id,
                'registered_location_active', sl.active,
                'owner_type', o.owner_type
            ),
            'existing_link', (
                select to_jsonb(l)
                from tcg.shopify_inventory_links l
                where l.inventory_id=i.id
                limit 1
            ),
            'pooled_membership', (
                select to_jsonb(lim)
                from tcg.listing_inventory_members lim
                where lim.inventory_id=i.id
                  and lim.state <> 'REMOVED'
                order by lim.created_at, lim.id
                limit 1
            ),
            'media_assets', coalesce((
                select jsonb_agg(to_jsonb(ma) order by ma.scope,ma.side,ma.created_at,ma.id)
                from tcg.media_assets ma
                where ma.approval_status='APPROVED'
                  and ma.rights_status='VERIFIED'
                  and ma.shopify_file_status='READY'
                  and (
                    (ma.scope='INVENTORY_ITEM' and ma.inventory_id=i.id)
                    or
                    (ma.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT') and ma.catalogue_id=i.catalogue_id)
                  )
            ), '[]'::jsonb),
            'shipping_profiles', coalesce((
                select jsonb_agg(to_jsonb(sp) order by sp.profile_key)
                from tcg.shopify_shipping_profiles sp
                where sp.owner_id=i.owner_id
                  and sp.active
            ), '[]'::jsonb)
        )
    end
    from tcg.inventory_items i
    join tcg.catalogue_products p on p.id=i.catalogue_id
    join tcg.owners o on o.id=i.owner_id and o.active
    left join tcg.storage_locations sl on sl.id=i.storage_location_id
    where i.id=p_inventory_id
      and i.owner_id=p_owner_id
    limit 1
$function$;

commit;
