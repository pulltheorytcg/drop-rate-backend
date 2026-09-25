create or replace function tcg.audit_order_item_reconciliation_change()
returns trigger
language plpgsql
security definer
set search_path to 'pg_catalog'
as $function$
begin
    insert into tcg.audit_events(
        actor, request_id, action, entity_type, entity_id, old_values, new_values
    ) values (
        coalesce(nullif(current_setting('tcg.user_id', true), ''), session_user::text),
        nullif(current_setting('tcg.request_id', true), ''),
        tg_op,
        tg_table_name,
        case
            when tg_op = 'DELETE' then old.order_item_id
            else new.order_item_id
        end,
        case when tg_op = 'INSERT' then null else to_jsonb(old) end,
        case when tg_op = 'DELETE' then null else to_jsonb(new) end
    );
    return null;
end;
$function$;

revoke all on function tcg.audit_order_item_reconciliation_change() from public;

drop trigger if exists order_item_reconciliations_audit
on tcg.order_item_reconciliations;

create trigger order_item_reconciliations_audit
    after insert or update or delete on tcg.order_item_reconciliations
    for each row execute function tcg.audit_order_item_reconciliation_change();
