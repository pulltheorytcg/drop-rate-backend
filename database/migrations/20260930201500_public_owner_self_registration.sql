begin;

create or replace function tcg.self_register_owner(
    p_display_name text,
    p_ack_version integer default 1
)
returns table(
    owner_id uuid,
    display_name text,
    owner_type text,
    commission_bps integer,
    membership_role text,
    created boolean
)
language plpgsql
security definer
set search_path = pg_catalog, tcg, auth
as $function$
declare
    v_user_id uuid := tcg.current_user_id();
    v_name text := btrim(coalesce(p_display_name, ''));
    v_auth_user auth.users%rowtype;
    v_membership tcg.owner_memberships%rowtype;
    v_owner tcg.owners%rowtype;
begin
    if v_user_id is null then
        raise exception 'Authenticated user required' using errcode = '42501';
    end if;

    if p_ack_version <> 1 then
        raise exception 'Unsupported seller onboarding acknowledgement version'
            using errcode = '22023';
    end if;

    if length(v_name) < 1 or length(v_name) > 120 then
        raise exception 'Seller display name must be between 1 and 120 characters'
            using errcode = '22023';
    end if;

    select *
      into v_auth_user
      from auth.users
     where id = v_user_id
     for update;

    if not found
       or coalesce(v_auth_user.is_anonymous, false)
       or nullif(btrim(coalesce(v_auth_user.email, '')), '') is null
       or coalesce(v_auth_user.email_confirmed_at, v_auth_user.confirmed_at) is null then
        raise exception 'A verified non-anonymous account is required'
            using errcode = '42501';
    end if;

    perform pg_advisory_xact_lock(hashtextextended('seller-self-register:' || v_user_id::text, 0));

    select *
      into v_membership
      from tcg.owner_memberships
     where user_id = v_user_id
     for update;

    if found then
        if v_membership.active and v_membership.role = 'OWNER' then
            select *
              into v_owner
              from tcg.owners
             where id = v_membership.owner_id;

            if v_owner.id is null or not v_owner.active or v_owner.owner_type <> 'CONSIGNOR' then
                raise exception 'Existing seller membership is not active'
                    using errcode = '42501';
            end if;

            return query
            select
                v_owner.id,
                v_owner.display_name,
                v_owner.owner_type,
                v_owner.commission_bps,
                v_membership.role,
                false;
            return;
        end if;

        raise exception 'This account already has a different Drop Rate access role'
            using errcode = '42501';
    end if;

    insert into tcg.owners(
        display_name,
        owner_type,
        founder_slot,
        active,
        commission_bps
    ) values (
        v_name,
        'CONSIGNOR',
        null,
        true,
        1000
    )
    returning * into v_owner;

    insert into tcg.owner_memberships(
        user_id,
        owner_id,
        role,
        active
    ) values (
        v_user_id,
        v_owner.id,
        'OWNER',
        true
    )
    returning * into v_membership;

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
        nullif(current_setting('tcg.request_id', true), ''),
        'OWNER_SELF_REGISTERED',
        'OWNER',
        v_owner.id,
        null,
        jsonb_build_object(
            'owner_type', v_owner.owner_type,
            'commission_bps', v_owner.commission_bps,
            'membership_role', v_membership.role,
            'acknowledgement_version', p_ack_version,
            'verified_email', lower(v_auth_user.email)
        )
    );

    return query
    select
        v_owner.id,
        v_owner.display_name,
        v_owner.owner_type,
        v_owner.commission_bps,
        v_membership.role,
        true;
end;
$function$;

revoke all on function tcg.self_register_owner(text, integer) from public;
grant execute on function tcg.self_register_owner(text, integer) to tcg_api;

commit;
