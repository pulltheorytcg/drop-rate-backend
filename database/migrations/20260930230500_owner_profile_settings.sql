begin;

alter table tcg.owners
    add column if not exists username text;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'owners_username_format_check'
          and conrelid = 'tcg.owners'::regclass
    ) then
        alter table tcg.owners
            add constraint owners_username_format_check
            check (
                username is null
                or username ~ '^[a-z0-9][a-z0-9_]{2,29}$'
            );
    end if;
end
$$;

create unique index if not exists owners_username_lower_uidx
    on tcg.owners (lower(username))
    where username is not null;

create or replace function tcg.update_owner_profile(
    p_display_name text,
    p_username text
)
returns table(
    owner_id uuid,
    display_name text,
    username text,
    owner_type text,
    commission_bps integer,
    created_at timestamptz
)
language plpgsql
security definer
set search_path = pg_catalog, tcg, auth
as $function$
declare
    v_user_id uuid := tcg.current_user_id();
    v_owner tcg.owners%rowtype;
    v_name text := btrim(coalesce(p_display_name, ''));
    v_username text := nullif(lower(btrim(coalesce(p_username, ''))), '');
    v_old_name text;
    v_old_username text;
begin
    if v_user_id is null then
        raise exception 'Authenticated user required' using errcode = '42501';
    end if;

    if length(v_name) < 1 or length(v_name) > 120 then
        raise exception 'Display name must be between 1 and 120 characters'
            using errcode = '22023';
    end if;

    if v_username is not null
       and v_username !~ '^[a-z0-9][a-z0-9_]{2,29}$' then
        raise exception 'Username must be 3-30 characters using lowercase letters, numbers and underscores'
            using errcode = '22023';
    end if;

    select o.*
      into v_owner
      from tcg.owner_memberships m
      join tcg.owners o on o.id = m.owner_id
     where m.user_id = v_user_id
       and m.active
       and o.active
       and m.role = 'OWNER'
     for update of o;

    if not found then
        raise exception 'Active Seller Hub owner membership required'
            using errcode = '42501';
    end if;

    if v_username is not null and exists (
        select 1
        from tcg.owners o
        where lower(o.username) = v_username
          and o.id <> v_owner.id
    ) then
        raise exception 'Username is already in use' using errcode = '23505';
    end if;

    v_old_name := v_owner.display_name;
    v_old_username := v_owner.username;

    update tcg.owners
       set display_name = v_name,
           username = v_username
     where id = v_owner.id
     returning * into v_owner;

    if v_old_name is distinct from v_owner.display_name
       or v_old_username is distinct from v_owner.username then
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
            'OWNER_PROFILE_UPDATED',
            'OWNER',
            v_owner.id,
            jsonb_build_object(
                'display_name', v_old_name,
                'username', v_old_username
            ),
            jsonb_build_object(
                'display_name', v_owner.display_name,
                'username', v_owner.username
            )
        );
    end if;

    return query
    select
        v_owner.id,
        v_owner.display_name,
        v_owner.username,
        v_owner.owner_type,
        v_owner.commission_bps,
        v_owner.created_at;
end;
$function$;

revoke all on function tcg.update_owner_profile(text, text) from public;
grant execute on function tcg.update_owner_profile(text, text) to tcg_api;

commit;
