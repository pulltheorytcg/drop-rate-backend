begin;

-- Add explicit category identities. No inventory, prices, provider references,
-- verified identities or publication state are manufactured by this migration.
alter table tcg.catalogue_products drop constraint catalogue_products_product_type_check;
alter table tcg.catalogue_products add constraint catalogue_products_product_type_check
    check (product_type in ('CARD','SEALED','COLLECTION','COMIC','ACCESSORY','FIGURE'));
alter table tcg.collectible_systems drop constraint collectible_systems_system_kind_check;
alter table tcg.collectible_systems add constraint collectible_systems_system_kind_check
    -- Preserve every kind already supported by the production predecessor.
    check (system_kind in ('TCG','COMICS','SPORTS_CARD','FIGURE','CONSTRUCTION_SET'));
alter table tcg.catalogue_product_profiles drop constraint catalogue_product_profiles_collectible_type_check;
alter table tcg.catalogue_product_profiles add constraint catalogue_product_profiles_collectible_type_check
    check (collectible_type in ('CARD','SEALED','COMIC','ACCESSORY','FIGURE'));
alter table tcg.taxonomy_schemas drop constraint taxonomy_schemas_scope_kind_check;
alter table tcg.taxonomy_schemas add constraint taxonomy_schemas_scope_kind_check
    check (scope_kind in ('CARD','SEALED','COMIC','ACCESSORY','FIGURE'));
alter table tcg.provider_catalogue_mappings drop constraint provider_catalogue_mappings_provider_entity_type_check;
alter table tcg.provider_catalogue_mappings add constraint provider_catalogue_mappings_provider_entity_type_check
    check (provider_entity_type in ('CARD_PRINTING','SEALED_PRODUCT','COMIC_PRINTING','ACCESSORY','FIGURE_PRODUCT'));

insert into tcg.collectible_systems(code,display_name,franchise,system_kind,metadata)
values ('SPORTS_CARDS','Sports Cards','Sports','SPORTS_CARD','{"intake":"SELLER_ENTERED","reference_catalogue_available":false}'),
       ('FIGURES','Figures','Figures','FIGURE','{"intake":"SELLER_ENTERED","reference_catalogue_available":false}')
on conflict(code) do nothing;

-- Only append an unreviewed structured identity with the server's actor.
-- The existing admin-only update policies remain unchanged. These rows are
-- excluded from reference-catalogue discovery until reviewed; owner inventory
-- continues to use its existing row-level ownership policies.
create policy seller_collectible_insert on tcg.catalogue_product_profiles
for insert to tcg_api with check (
    tcg.current_access_role() is not null
    and identity_status='NEEDS_REVIEW'
    and attributes->>'identity_source'='SELLER_ENTERED'
    and attributes->>'submitted_by_user_id'=tcg.current_user_id()::text
    and ((system_code='SPORTS_CARDS' and collectible_type='CARD'
          and jsonb_typeof(attributes->'sports_card')='object'
          and attributes->'sports_card'->>'system_code'='SPORTS_CARDS')
      or (system_code='FIGURES' and collectible_type='FIGURE'
          and jsonb_typeof(attributes->'figure_details')='object'
          and attributes->'figure_details'->>'system_code'='FIGURES'))
    and exists(select 1 from tcg.catalogue_products p
        where p.id=catalogue_id and p.product_type=collectible_type
          and p.identity_key like 'manual:v1:%')
);

create or replace function tcg.validate_catalogue_product_profile()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
declare
    v_product_type text;
    v_expected_type text;
    v_system_kind text;
begin
    select p.product_type into v_product_type
    from tcg.catalogue_products p
    where p.id=new.catalogue_id;

    if v_product_type is null then
        raise exception 'Catalogue product not found' using errcode='23503';
    end if;

    select s.system_kind into v_system_kind
    from tcg.collectible_systems s
    where s.code=new.system_code;

    if v_system_kind is null then
        raise exception 'Collectible system not found' using errcode='23503';
    end if;

    v_expected_type := case
        when v_product_type='CARD' then 'CARD'
        when v_product_type in ('SEALED','COLLECTION') then 'SEALED'
        when v_product_type='COMIC' then 'COMIC'
        when v_product_type='ACCESSORY' then 'ACCESSORY'
        when v_product_type='FIGURE' then 'FIGURE'
    end;

    if new.collectible_type <> v_expected_type then
        raise exception 'Structured collectible type does not match catalogue product type'
            using errcode='23514';
    end if;

    if (new.collectible_type='CARD' and v_system_kind not in ('TCG','SPORTS_CARD'))
       or (new.collectible_type='SEALED' and v_system_kind <> 'TCG') then
        raise exception 'Card/sealed products require a matching collectible system'
            using errcode='23514';
    end if;

    if new.collectible_type='COMIC' and v_system_kind <> 'COMICS' then
        raise exception 'Comic products require a comics collectible system'
            using errcode='23514';
    end if;

    if new.collectible_type='FIGURE' and v_system_kind <> 'FIGURE' then
        raise exception 'Figures require a figures collectible system' using errcode='23514';
    end if;

    return new;
end;
$$;
revoke all on function tcg.validate_catalogue_product_profile() from public;
grant execute on function tcg.validate_catalogue_product_profile() to tcg_api;

create or replace function tcg.validate_provider_catalogue_mapping()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
declare
    v_profile tcg.catalogue_product_profiles%rowtype;
    v_expected_entity text;
begin
    select * into v_profile
    from tcg.catalogue_product_profiles
    where catalogue_id=new.catalogue_id;

    if v_profile.catalogue_id is null then
        raise exception 'Catalogue product profile is required before provider mapping'
            using errcode='23503';
    end if;

    v_expected_entity := case v_profile.collectible_type
        when 'CARD' then 'CARD_PRINTING'
        when 'SEALED' then 'SEALED_PRODUCT'
        when 'COMIC' then 'COMIC_PRINTING'
        when 'ACCESSORY' then 'ACCESSORY'
        when 'FIGURE' then 'FIGURE_PRODUCT'
    end;

    if v_profile.system_code <> new.system_code
       or new.provider_entity_type <> v_expected_entity then
        raise exception 'Provider mapping does not match catalogue product identity'
            using errcode='23514';
    end if;

    return new;
end;
$$;
revoke all on function tcg.validate_provider_catalogue_mapping() from public;
grant execute on function tcg.validate_provider_catalogue_mapping() to tcg_api;

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
    elsif product_kind = 'FIGURE' then
        if nullif(btrim(new.condition), '') is not null and new.condition not in
            ('New','Like New','Very Good','Good','Fair','Damaged') then
            raise exception 'Invalid figure condition' using errcode='23514';
        end if;
        if new.grading_company is not null or new.grade is not null or new.certificate_number is not null then
            raise exception 'Figures cannot use card or comic grading fields' using errcode='23514';
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
