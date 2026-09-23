begin;

alter table tcg.inventory_items
    add column seal_status text
    check (seal_status in ('SEALED', 'UNSEALED'));

create or replace function tcg.validate_inventory_condition_state()
returns trigger
language plpgsql
set search_path = pg_catalog, tcg
as $$
declare
    product_kind text;
begin
    select product_type into product_kind
    from tcg.catalogue_products
    where id = new.catalogue_id;

    if product_kind = 'CARD' then
        if new.condition is not null and new.condition not in (
            'Near Mint',
            'Lightly Played',
            'Moderately Played',
            'Heavily Played',
            'Damaged'
        ) then
            raise exception 'Invalid raw card condition: %', new.condition
                using errcode = '23514';
        end if;
    else
        if new.seal_status = 'SEALED' then
            new.condition := 'Sealed';
        elsif new.seal_status = 'UNSEALED' then
            new.condition := 'Unsealed';
        end if;
    end if;

    return new;
end;
$$;

create trigger inventory_condition_state_guard
    before insert or update of catalogue_id, condition, seal_status
    on tcg.inventory_items
    for each row execute function tcg.validate_inventory_condition_state();

commit;
