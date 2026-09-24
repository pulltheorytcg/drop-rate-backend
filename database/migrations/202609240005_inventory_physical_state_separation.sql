begin;

-- Historical guard logic mirrored SEALED/UNSEALED into condition. Condition is
-- now reserved exclusively for raw card condition, so remove any legacy mirror.
update tcg.inventory_items i
set condition = null
from tcg.catalogue_products p
where p.id = i.catalogue_id
  and p.product_type <> 'CARD'
  and i.condition is not null;

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

        if nullif(btrim(new.condition), '') is not null
           and new.condition not in (
               'Near Mint',
               'Lightly Played',
               'Moderately Played',
               'Heavily Played',
               'Damaged'
           ) then
            raise exception 'Invalid raw card condition'
                using errcode = '23514';
        end if;

        if nullif(btrim(new.condition), '') is not null
           and (new.grading_company is not null or new.grade is not null) then
            raise exception 'Graded card inventory cannot also use raw card condition'
                using errcode = '23514';
        end if;
    else
        if nullif(btrim(new.condition), '') is not null then
            raise exception 'Non-card inventory cannot use raw card condition'
                using errcode = '23514';
        end if;

        if new.grading_company is not null
           or new.grade is not null
           or new.certificate_number is not null then
            raise exception 'Non-card inventory cannot use grading fields'
                using errcode = '23514';
        end if;

        -- Never mirror seal state into condition.
        new.condition := null;
    end if;

    return new;
end;
$$;

revoke all on function tcg.validate_inventory_condition_state() from public;

alter table tcg.inventory_items
add constraint inventory_items_physical_state_separation_check
check (
    (
        nullif(btrim(condition), '') is null
        or (
            grading_company is null
            and grade is null
            and certificate_number is null
            and seal_status is null
        )
    )
    and (
        seal_status is null
        or (
            nullif(btrim(condition), '') is null
            and grading_company is null
            and grade is null
            and certificate_number is null
        )
    )
);

commit;
