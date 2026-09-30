begin;

create or replace function tcg.shopify_price_sync_candidates(
  p_limit integer default 50
)
returns jsonb
language plpgsql
stable
security definer
set search_path=pg_catalog
as $function$
declare
  v_rows jsonb;
begin
  if p_limit < 1 or p_limit > 100 then
    raise exception 'Shopify price sync limit must be between 1 and 100'
      using errcode='22023';
  end if;

  select coalesce(jsonb_agg(to_jsonb(q) order by q.last_synced_at,q.link_id),'[]'::jsonb)
    into v_rows
    from (
      select
        sil.id as link_id,
        sil.version as link_version,
        sil.owner_id,
        sil.shopify_product_gid,
        sil.shopify_variant_gid,
        sil.synced_price_minor,
        sil.last_synced_at,
        i.id as inventory_id,
        i.version as inventory_version,
        i.catalogue_id,
        i.inventory_code,
        i.store_price_minor
      from tcg.shopify_inventory_links sil
      join tcg.inventory_items i on i.id=sil.inventory_id
      where sil.sync_state='PUBLISHED'
        and coalesce(sil.test_mode,false)=false
        and sil.listing_key not like 'shopify-pool:%'
        and sil.reserved_order_reference is null
        and sil.reserved_line_reference is null
        and i.status='APPROVED'
        and i.sale_intent='FOR_SALE'
        and i.store_price_minor is not null
        and i.store_price_minor <> sil.synced_price_minor
      order by sil.last_synced_at,sil.id
      limit p_limit
    ) q;

  return v_rows;
end;
$function$;

revoke all on function tcg.shopify_price_sync_candidates(integer) from public;
revoke all on function tcg.shopify_price_sync_candidates(integer)
  from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.shopify_price_sync_candidates(integer) to tcg_api;


create or replace function tcg.finalize_shopify_price_sync(
  p_link_id uuid,
  p_owner_id uuid,
  p_expected_link_version integer,
  p_inventory_id uuid,
  p_expected_inventory_version integer,
  p_target_price_minor bigint,
  p_request_id text default null
)
returns jsonb
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
  v_current record;
  v_updated tcg.shopify_inventory_links%rowtype;
begin
  if p_target_price_minor is null or p_target_price_minor < 100 then
    raise exception 'Shopify price sync target must be at least 100 minor units'
      using errcode='22023';
  end if;

  select
    sil.id as link_id,
    sil.version as link_version,
    sil.sync_state,
    sil.test_mode,
    sil.listing_key,
    sil.reserved_order_reference,
    sil.reserved_line_reference,
    sil.synced_price_minor,
    i.id as inventory_id,
    i.version as inventory_version,
    i.status as inventory_status,
    i.sale_intent,
    i.store_price_minor,
    i.inventory_code
  into v_current
  from tcg.shopify_inventory_links sil
  join tcg.inventory_items i on i.id=sil.inventory_id
  where sil.id=p_link_id
    and sil.owner_id=p_owner_id
    and i.id=p_inventory_id
  for update of sil,i;

  if not found then
    return jsonb_build_object(
      'status','RETRY_REQUIRED',
      'reason','MISSING_OR_REASSIGNED'
    );
  end if;

  if v_current.link_version <> p_expected_link_version
     or v_current.inventory_version <> p_expected_inventory_version
     or v_current.sync_state <> 'PUBLISHED'
     or coalesce(v_current.test_mode,false)
     or v_current.listing_key like 'shopify-pool:%'
     or v_current.reserved_order_reference is not null
     or v_current.reserved_line_reference is not null
     or v_current.inventory_status <> 'APPROVED'
     or v_current.sale_intent <> 'FOR_SALE'
     or v_current.store_price_minor is null
     or v_current.store_price_minor <> p_target_price_minor then
    return jsonb_build_object(
      'status','RETRY_REQUIRED',
      'reason','STATE_CHANGED',
      'inventory_id',v_current.inventory_id,
      'inventory_code',v_current.inventory_code
    );
  end if;

  update tcg.shopify_inventory_links
     set synced_price_minor=p_target_price_minor,
         last_synced_at=clock_timestamp(),
         version=version+1
   where id=p_link_id
     and owner_id=p_owner_id
     and version=p_expected_link_version
  returning * into v_updated;

  if not found then
    return jsonb_build_object(
      'status','RETRY_REQUIRED',
      'reason','LINK_VERSION_CHANGED',
      'inventory_id',v_current.inventory_id,
      'inventory_code',v_current.inventory_code
    );
  end if;

  insert into tcg.audit_events(
    actor,request_id,action,entity_type,entity_id,old_values,new_values
  ) values(
    'automation:shopify-product-updates',
    nullif(btrim(coalesce(p_request_id,'')),''),
    'SHOPIFY_PRICE_SYNCED',
    'SHOPIFY_INVENTORY_LINK',
    v_updated.id,
    jsonb_build_object(
      'synced_price_minor',v_current.synced_price_minor,
      'version',v_current.link_version
    ),
    jsonb_build_object(
      'synced_price_minor',v_updated.synced_price_minor,
      'version',v_updated.version
    )
  );

  return jsonb_build_object(
    'status','SYNCED',
    'inventory_id',v_current.inventory_id,
    'inventory_code',v_current.inventory_code,
    'previous_price_minor',v_current.synced_price_minor,
    'synced_price_minor',v_updated.synced_price_minor,
    'link_version',v_updated.version
  );
end;
$function$;

revoke all on function tcg.finalize_shopify_price_sync(
  uuid,uuid,integer,uuid,integer,bigint,text
) from public;
revoke all on function tcg.finalize_shopify_price_sync(
  uuid,uuid,integer,uuid,integer,bigint,text
) from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.finalize_shopify_price_sync(
  uuid,uuid,integer,uuid,integer,bigint,text
) to tcg_api;

commit;
