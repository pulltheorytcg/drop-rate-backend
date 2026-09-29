begin;

create or replace function tcg.record_shopify_raw_pool_audit(
    p_request_id text,
    p_entity_id uuid,
    p_old_values jsonb,
    p_new_values jsonb
)
returns void
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_user_id uuid := tcg.current_user_id();
begin
    if v_user_id is null then
        raise exception 'Authenticated user required' using errcode = '42501';
    end if;

    if not tcg.is_platform_admin() then
        raise exception 'Platform administrator access required' using errcode = '42501';
    end if;

    insert into tcg.audit_events(
        actor,
        request_id,
        action,
        entity_type,
        entity_id,
        old_values,
        new_values
    ) values (
        v_user_id::text,
        nullif(p_request_id, ''),
        'SHOPIFY_RAW_POOL_LINK_CONSOLIDATED',
        'SHOPIFY_INVENTORY_LINK',
        p_entity_id,
        p_old_values,
        p_new_values
    );
end;
$function$;

revoke all on function tcg.record_shopify_raw_pool_audit(
    text, uuid, jsonb, jsonb
) from public;

grant execute on function tcg.record_shopify_raw_pool_audit(
    text, uuid, jsonb, jsonb
) to tcg_api;

commit;
