-- Align Shopify link persistence with the existing authenticated founder authority.
-- No owner memberships, table privileges, RLS policies or historical links change.
begin;

CREATE OR REPLACE FUNCTION tcg.save_shopify_inventory_draft(p_inventory_id uuid, p_owner_id uuid, p_expected_version integer, p_created_by_user_id uuid, p_automation_event_id uuid, p_request_id text, p_listing_key text, p_shop_domain text, p_shopify_product_gid text, p_shopify_variant_gid text, p_shopify_inventory_item_gid text, p_shopify_location_gid text, p_shopify_publication_gid text, p_sku text, p_synced_price_minor bigint, p_test_mode boolean)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog'
AS $function$
declare
    v_item tcg.inventory_items%rowtype;
    v_existing tcg.shopify_inventory_links%rowtype;
    v_link tcg.shopify_inventory_links%rowtype;
    v_actor text;
begin
    if (p_created_by_user_id is null) = (p_automation_event_id is null) then
        raise exception 'Exactly one Shopify publication actor is required'
            using errcode='23514';
    end if;

    select * into v_item
    from tcg.inventory_items
    where id=p_inventory_id
      and owner_id=p_owner_id;

    if not found then
        raise exception 'Inventory item not found for publication owner'
            using errcode='23503';
    end if;
    if v_item.version <> p_expected_version
       or v_item.status <> 'APPROVED'
       or v_item.sale_intent <> 'FOR_SALE' then
        raise exception 'Inventory changed or is no longer publishable'
            using errcode='55000';
    end if;

    if p_automation_event_id is not null then
        if not exists (
            select 1
            from tcg.automation_events ae
            where ae.id=p_automation_event_id
              and ae.owner_id=p_owner_id
              and ae.event_type='inventory.approved'
              and ae.schema_version=1
              and ae.status='DISPATCHING'
              and ae.aggregate_type='INVENTORY_ITEM'
              and ae.aggregate_id=p_inventory_id::text
              and ae.idempotency_key=(
                  'inventory.approved:' || p_inventory_id::text
                  || ':v' || p_expected_version::text
              )
              and ae.payload->>'inventory_id'=p_inventory_id::text
              and ae.payload->>'status'='APPROVED'
              and ae.payload->>'version'=p_expected_version::text
        ) then
            raise exception 'Automation event does not authorize this inventory publication'
                using errcode='23514';
        end if;
        v_actor := 'automation:' || p_automation_event_id::text;
    else
        -- The platform publisher serves consignors without joining their owner
        -- memberships. Bind the claimed actor to the authenticated, active
        -- founder account; the item/owner/version checks above remain exact.
        if p_created_by_user_id is distinct from tcg.current_user_id()
           or not tcg.is_platform_admin() then
            raise exception 'Authenticated platform administrator required for publication'
                using errcode='42501';
        end if;
        v_actor := p_created_by_user_id::text;
    end if;

    select * into v_existing
    from tcg.shopify_inventory_links
    where inventory_id=p_inventory_id
    for update;

    if found then
        if v_existing.sync_state='SOLD' then
            raise exception 'Sold Shopify inventory cannot be relisted'
                using errcode='55000';
        end if;
        if v_existing.shopify_product_gid <> p_shopify_product_gid
           or v_existing.shopify_variant_gid <> p_shopify_variant_gid
           or v_existing.shopify_inventory_item_gid <> p_shopify_inventory_item_gid then
            raise exception 'Existing Shopify link remote identity changed'
                using errcode='55000';
        end if;
        if v_existing.sync_state='PUBLISHED' then
            return to_jsonb(v_existing);
        end if;
        if v_existing.sync_state not in ('DRAFT','ARCHIVED','ERROR') then
            raise exception 'Shopify inventory link is not relistable'
                using errcode='55000';
        end if;

        update tcg.shopify_inventory_links
        set sync_state='DRAFT',
            shop_domain=p_shop_domain,
            shopify_location_gid=p_shopify_location_gid,
            shopify_publication_gid=p_shopify_publication_gid,
            sku=p_sku,
            synced_price_minor=p_synced_price_minor,
            test_mode=p_test_mode,
            last_synced_at=clock_timestamp(),
            version=version+1
        where id=v_existing.id
        returning * into v_link;

        insert into tcg.audit_events(
            actor,request_id,action,entity_type,entity_id,old_values,new_values
        ) values (
            v_actor,nullif(btrim(coalesce(p_request_id,'')),''),
            'SHOPIFY_LINK_DRAFT_REFRESHED','SHOPIFY_INVENTORY_LINK',v_link.id,
            to_jsonb(v_existing),to_jsonb(v_link)
        );
        return to_jsonb(v_link);
    end if;

    insert into tcg.shopify_inventory_links(
        inventory_id,owner_id,created_by_user_id,created_by_automation_event_id,
        listing_key,allocation_priority,shop_domain,shopify_product_gid,
        shopify_variant_gid,shopify_inventory_item_gid,shopify_location_gid,
        shopify_publication_gid,sku,sync_state,test_mode,synced_price_minor
    ) values (
        p_inventory_id,p_owner_id,p_created_by_user_id,p_automation_event_id,
        p_listing_key,1,p_shop_domain,p_shopify_product_gid,
        p_shopify_variant_gid,p_shopify_inventory_item_gid,p_shopify_location_gid,
        p_shopify_publication_gid,p_sku,'DRAFT',p_test_mode,p_synced_price_minor
    )
    returning * into v_link;

    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values (
        v_actor,nullif(btrim(coalesce(p_request_id,'')),''),
        'SHOPIFY_LINK_DRAFTED','SHOPIFY_INVENTORY_LINK',v_link.id,
        null,to_jsonb(v_link)
    );
    return to_jsonb(v_link);
end;
$function$;

CREATE OR REPLACE FUNCTION tcg.mark_shopify_inventory_published(p_inventory_id uuid, p_owner_id uuid, p_expected_version integer, p_created_by_user_id uuid, p_automation_event_id uuid, p_request_id text, p_shopify_product_gid text, p_shopify_variant_gid text, p_shopify_inventory_item_gid text, p_synced_price_minor bigint, p_test_mode boolean)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog'
AS $function$
declare
    v_item tcg.inventory_items%rowtype;
    v_existing tcg.shopify_inventory_links%rowtype;
    v_link tcg.shopify_inventory_links%rowtype;
    v_actor text;
begin
    if (p_created_by_user_id is null) = (p_automation_event_id is null) then
        raise exception 'Exactly one Shopify publication actor is required'
            using errcode='23514';
    end if;

    select * into v_item
    from tcg.inventory_items
    where id=p_inventory_id
      and owner_id=p_owner_id;

    if not found then
        raise exception 'Inventory item not found for publication owner'
            using errcode='23503';
    end if;
    if v_item.version <> p_expected_version
       or v_item.status <> 'APPROVED'
       or v_item.sale_intent <> 'FOR_SALE' then
        raise exception 'Inventory changed while Shopify publication was in progress'
            using errcode='55000';
    end if;

    if p_automation_event_id is not null then
        if not exists (
            select 1
            from tcg.automation_events ae
            where ae.id=p_automation_event_id
              and ae.owner_id=p_owner_id
              and ae.event_type='inventory.approved'
              and ae.schema_version=1
              and ae.status='DISPATCHING'
              and ae.aggregate_type='INVENTORY_ITEM'
              and ae.aggregate_id=p_inventory_id::text
              and ae.idempotency_key=(
                  'inventory.approved:' || p_inventory_id::text
                  || ':v' || p_expected_version::text
              )
              and ae.payload->>'inventory_id'=p_inventory_id::text
              and ae.payload->>'status'='APPROVED'
              and ae.payload->>'version'=p_expected_version::text
        ) then
            raise exception 'Automation event does not authorize this inventory publication'
                using errcode='23514';
        end if;
        v_actor := 'automation:' || p_automation_event_id::text;
    else
        -- The platform publisher serves consignors without joining their owner
        -- memberships. Bind the claimed actor to the authenticated, active
        -- founder account; the item/owner/version checks above remain exact.
        if p_created_by_user_id is distinct from tcg.current_user_id()
           or not tcg.is_platform_admin() then
            raise exception 'Authenticated platform administrator required for publication'
                using errcode='42501';
        end if;
        v_actor := p_created_by_user_id::text;
    end if;

    select * into v_existing
    from tcg.shopify_inventory_links
    where inventory_id=p_inventory_id
      and owner_id=p_owner_id
    for update;

    if not found then
        raise exception 'Shopify draft link is missing'
            using errcode='55000';
    end if;
    if v_existing.shopify_product_gid <> p_shopify_product_gid
       or v_existing.shopify_variant_gid <> p_shopify_variant_gid
       or v_existing.shopify_inventory_item_gid <> p_shopify_inventory_item_gid then
        raise exception 'Shopify remote identity changed before publication finalization'
            using errcode='55000';
    end if;
    if v_existing.sync_state='PUBLISHED' then
        return to_jsonb(v_existing);
    end if;
    if v_existing.sync_state <> 'DRAFT' then
        raise exception 'Only a verified Shopify draft can be published'
            using errcode='55000';
    end if;

    update tcg.shopify_inventory_links
    set sync_state='PUBLISHED',
        synced_price_minor=p_synced_price_minor,
        test_mode=p_test_mode,
        last_synced_at=clock_timestamp(),
        version=version+1
    where id=v_existing.id
    returning * into v_link;

    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values (
        v_actor,nullif(btrim(coalesce(p_request_id,'')),''),
        'SHOPIFY_LINK_PUBLISHED','SHOPIFY_INVENTORY_LINK',v_link.id,
        to_jsonb(v_existing),to_jsonb(v_link)
    );
    return to_jsonb(v_link);
end;
$function$;

commit;

