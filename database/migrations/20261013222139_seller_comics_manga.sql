begin;

-- Books share the existing COMIC identity model. No stock or prices are changed.
insert into tcg.collectible_systems(code,display_name,franchise,system_kind,metadata)
values ('MANGA','Manga','Manga','COMICS','{"intake":"SELLER_ENTERED"}'),
       ('OTHER_COMICS','Other Comics','Comics','COMICS','{"intake":"SELLER_ENTERED"}')
on conflict(code) do nothing;

-- Sellers may append only unverified book identities attributed to themselves.
-- Existing admin update rules and inventory owner RLS remain in force.
create policy seller_book_insert on tcg.catalogue_product_profiles
for insert to tcg_api with check (
    tcg.current_access_role() is not null
    and collectible_type='COMIC' and identity_status='NEEDS_REVIEW'
    and system_code in ('MARVEL_COMICS','DC_COMICS','OTHER_COMICS','MANGA')
    and attributes->>'identity_source'='SELLER_ENTERED'
    and attributes->>'submitted_by_user_id'=tcg.current_user_id()::text
    and exists(select 1 from tcg.catalogue_products p where p.id=catalogue_id
               and p.product_type='COMIC' and p.identity_key like 'manual:v1:%')
);
create policy seller_book_insert on tcg.comic_printing_details
for insert to tcg_api with check (
    tcg.current_access_role() is not null and identity_status='NEEDS_REVIEW'
    and attributes->>'identity_source'='SELLER_ENTERED'
    and attributes->>'submitted_by_user_id'=tcg.current_user_id()::text
    and exists(select 1 from tcg.catalogue_product_profiles p
               where p.catalogue_id=comic_printing_details.catalogue_id
                 and p.system_code=comic_printing_details.system_code
                 and p.collectible_type='COMIC' and p.identity_status='NEEDS_REVIEW'
                 and p.attributes->>'submitted_by_user_id'=tcg.current_user_id()::text)
);

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
    elsif product_kind = 'COMIC' then
        if new.seal_status is not null then
            raise exception 'Comics and manga cannot use seal_status' using errcode='23514';
        end if;
        if nullif(btrim(new.condition), '') is not null and new.condition not in
            ('Mint','Near Mint','Very Fine','Fine','Very Good','Good','Fair','Poor') then
            raise exception 'Invalid comic or manga condition' using errcode='23514';
        end if;
        if new.grading_company is not null then
            if nullif(btrim(new.condition), '') is not null then
                raise exception 'Graded books cannot also use raw book condition' using errcode='23514';
            end if;
            if new.grade is null or btrim(new.grade) !~ '^[0-9]+([.][0-9]+)?$' then
                raise exception 'Comic grade must be a number between 0.5 and 10' using errcode='23514';
            end if;
            if btrim(new.grade)::numeric < 0.5 or btrim(new.grade)::numeric > 10 then
                raise exception 'Comic grade must be a number between 0.5 and 10' using errcode='23514';
            end if;
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

commit;
