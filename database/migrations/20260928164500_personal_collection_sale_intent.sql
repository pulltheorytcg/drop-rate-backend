begin;

alter table tcg.inventory_items
    add column if not exists sale_intent text not null default 'FOR_SALE';

alter table tcg.inventory_items
    drop constraint if exists inventory_items_sale_intent_check;

alter table tcg.inventory_items
    add constraint inventory_items_sale_intent_check
    check (sale_intent in ('FOR_SALE', 'PERSONAL_COLLECTION'));

alter table tcg.inventory_items
    drop constraint if exists inventory_items_personal_collection_not_sellable_check;

alter table tcg.inventory_items
    add constraint inventory_items_personal_collection_not_sellable_check
    check (
        sale_intent = 'FOR_SALE'
        or status not in ('RESERVED', 'SOLD')
    );

create index if not exists inventory_items_owner_sale_intent_status_idx
    on tcg.inventory_items(owner_id, sale_intent, status, updated_at desc);

grant update(sale_intent) on tcg.inventory_items to tcg_api;

create or replace function tcg.audit_inventory_sale_intent_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if old.sale_intent is not distinct from new.sale_intent then
        return null;
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
        coalesce(
            nullif(pg_catalog.current_setting('tcg.user_id', true), ''),
            session_user::text
        ),
        nullif(pg_catalog.current_setting('tcg.request_id', true), ''),
        'SALE_INTENT_CHANGED',
        'inventory_items',
        new.id,
        pg_catalog.jsonb_build_object(
            'sale_intent', old.sale_intent,
            'status', old.status,
            'version', old.version
        ),
        pg_catalog.jsonb_build_object(
            'sale_intent', new.sale_intent,
            'status', new.status,
            'version', new.version
        )
    );

    return null;
end;
$$;

revoke all on function tcg.audit_inventory_sale_intent_change() from public;

drop trigger if exists inventory_sale_intent_audit on tcg.inventory_items;
create trigger inventory_sale_intent_audit
after update of sale_intent on tcg.inventory_items
for each row
execute function tcg.audit_inventory_sale_intent_change();

commit;
