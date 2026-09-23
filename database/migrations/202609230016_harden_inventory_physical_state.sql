begin;

create or replace function tcg.validate_inventory_condition_state()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
    product_kind text;
begin
    select p.product_type into product_kind
    from tcg.catalogue_products p
    where p.id = new.catalogue_id;

    if product_kind is null then
        raise exception 'Catalogue product is missing'
            using errcode = '23514';
    end if;

    if product_kind = 'CARD' then
        if new.seal_status is not null then
            raise exception 'Card inventory cannot use seal_status'
                using errcode = '23514';
        end if;

        if new.condition is not null and new.condition not in (
            'Near Mint',
            'Lightly Played',
            'Moderately Played',
            'Heavily Played',
            'Damaged'
        ) then
            raise exception 'Invalid raw card condition'
                using errcode = '23514';
        end if;
    else
        if new.grading_company is not null
           or new.grade is not null
           or new.certificate_number is not null then
            raise exception 'Non-card inventory cannot use grading fields'
                using errcode = '23514';
        end if;

        if new.seal_status = 'SEALED' then
            new.condition := 'Sealed';
        elsif new.seal_status = 'UNSEALED' then
            new.condition := 'Unsealed';
        else
            new.condition := null;
        end if;
    end if;

    return new;
end;
$$;

revoke all on function tcg.validate_inventory_condition_state() from public;

drop trigger if exists inventory_condition_state_guard on tcg.inventory_items;
create trigger inventory_condition_state_guard
    before insert or update of
        catalogue_id,
        condition,
        seal_status,
        grading_company,
        grade,
        certificate_number
    on tcg.inventory_items
    for each row execute function tcg.validate_inventory_condition_state();

commit;
