-- Access-control foundation: separate platform permission from physical ownership.
-- Founder HQ is PLATFORM_ADMIN-only. External sellers/consignors use OWNER membership.

alter table tcg.owner_memberships
  drop constraint if exists owner_memberships_role_check;

alter table tcg.owner_memberships
  alter column role set default 'OWNER';

insert into tcg.audit_events(
  actor,request_id,action,entity_type,entity_id,old_values,new_values
)
select
  'system:rbac-migration',
  null,
  'MEMBERSHIP_ROLE_MIGRATED',
  'OWNER',
  m.owner_id,
  jsonb_build_object('role',m.role),
  jsonb_build_object('role','PLATFORM_ADMIN')
from tcg.owner_memberships m
where m.role='FOUNDER';

update tcg.owner_memberships
set role='PLATFORM_ADMIN'
where role='FOUNDER';

alter table tcg.owner_memberships
  add constraint owner_memberships_role_check
  check (role in ('PLATFORM_ADMIN','OWNER'));

create or replace function tcg.current_access_role()
returns text
language sql
stable
security definer
set search_path to 'pg_catalog'
as $function$
  select m.role
  from tcg.owner_memberships m
  where m.user_id=tcg.current_user_id()
    and m.active
  order by m.created_at,m.id
  limit 1
$function$;

create or replace function tcg.is_platform_admin()
returns boolean
language sql
stable
security definer
set search_path to 'pg_catalog'
as $function$
  select coalesce(tcg.current_access_role()='PLATFORM_ADMIN',false)
$function$;

revoke all on function tcg.current_access_role() from public;
revoke all on function tcg.is_platform_admin() from public;
grant execute on function tcg.current_access_role() to tcg_api;
grant execute on function tcg.is_platform_admin() to tcg_api;

drop policy if exists owner_read on tcg.owners;
create policy owner_read
on tcg.owners
for select
to tcg_api
using (
  active
  and (
    tcg.is_platform_admin()
    or exists (
      select 1
      from tcg.owner_memberships m
      where m.owner_id=owners.id
        and m.user_id=tcg.current_user_id()
        and m.active
    )
  )
);

create or replace function tcg.create_founder_invite(
    p_token_hash text,
    p_invited_name text,
    p_founder_slot smallint,
    p_invited_email text default null,
    p_expires_at timestamptz default (now() + interval '7 days')
)
returns table(
    id uuid,
    invited_name text,
    invited_email text,
    founder_slot smallint,
    expires_at timestamptz,
    created_at timestamptz
)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_user_id uuid := tcg.current_user_id();
    v_owner_id uuid;
    v_invite tcg.founder_invites%rowtype;
begin
    if v_user_id is null then
        raise exception 'Authenticated user required' using errcode = '42501';
    end if;

    select m.owner_id
      into v_owner_id
      from tcg.owner_memberships m
      join tcg.owners o on o.id = m.owner_id
     where m.user_id = v_user_id
       and m.active
       and m.role = 'PLATFORM_ADMIN'
       and o.active
     order by m.created_at
     limit 1;

    if v_owner_id is null then
        raise exception 'Platform administrator membership required' using errcode = '42501';
    end if;

    if p_token_hash is null or length(btrim(p_token_hash)) < 32 then
        raise exception 'Invalid invite token hash' using errcode = '22023';
    end if;

    if p_founder_slot not between 1 and 3 then
        raise exception 'Invalid founder slot' using errcode = '22023';
    end if;

    if exists (
        select 1 from tcg.owners o
        where o.owner_type = 'FOUNDER'
          and o.founder_slot = p_founder_slot
          and o.active
    ) then
        raise exception 'Founder slot is already occupied' using errcode = '23505';
    end if;

    insert into tcg.founder_invites(
        token_hash, invited_name, invited_email, founder_slot,
        created_by_owner_id, expires_at
    )
    values (
        btrim(p_token_hash),
        btrim(p_invited_name),
        nullif(btrim(p_invited_email), ''),
        p_founder_slot,
        v_owner_id,
        p_expires_at
    )
    returning * into v_invite;

    insert into tcg.audit_events(
        actor, request_id, action, entity_type, entity_id, new_values
    )
    values (
        v_user_id::text,
        current_setting('tcg.request_id', true),
        'FOUNDER_INVITE_CREATED',
        'FOUNDER_INVITE',
        v_invite.id,
        jsonb_build_object(
            'invited_name', v_invite.invited_name,
            'invited_email', v_invite.invited_email,
            'founder_slot', v_invite.founder_slot,
            'expires_at', v_invite.expires_at
        )
    );

    return query
    select
        v_invite.id,
        v_invite.invited_name,
        v_invite.invited_email,
        v_invite.founder_slot,
        v_invite.expires_at,
        v_invite.created_at;
end;
$function$;

create or replace function tcg.redeem_founder_invite(
    p_token_hash text,
    p_display_name text,
    p_email text
)
returns table(
    owner_id uuid,
    display_name text,
    owner_type text,
    founder_slot smallint,
    role text
)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_user_id uuid := tcg.current_user_id();
    v_invite tcg.founder_invites%rowtype;
    v_owner tcg.owners%rowtype;
begin
    if v_user_id is null then
        raise exception 'Authenticated user required' using errcode = '42501';
    end if;

    if exists (
        select 1
        from tcg.owner_memberships m
        where m.user_id = v_user_id and m.active
    ) then
        raise exception 'Account is already linked to an owner' using errcode = '23505';
    end if;

    select *
      into v_invite
      from tcg.founder_invites i
     where i.token_hash = btrim(p_token_hash)
     for update;

    if v_invite.id is null then
        raise exception 'Invite not found' using errcode = '22023';
    end if;
    if v_invite.revoked_at is not null then
        raise exception 'Invite has been revoked' using errcode = '22023';
    end if;
    if v_invite.redeemed_at is not null then
        raise exception 'Invite has already been redeemed' using errcode = '23505';
    end if;
    if v_invite.expires_at <= now() then
        raise exception 'Invite has expired' using errcode = '22023';
    end if;
    if v_invite.invited_email is not null
       and lower(btrim(v_invite.invited_email)) <> lower(btrim(p_email)) then
        raise exception 'Invite email does not match this account' using errcode = '42501';
    end if;
    if exists (
        select 1 from tcg.owners o
        where o.owner_type = 'FOUNDER'
          and o.founder_slot = v_invite.founder_slot
          and o.active
    ) then
        raise exception 'Founder slot is already occupied' using errcode = '23505';
    end if;

    insert into tcg.owners(display_name, owner_type, founder_slot)
    values (
        coalesce(nullif(btrim(p_display_name), ''), v_invite.invited_name),
        'FOUNDER',
        v_invite.founder_slot
    )
    returning * into v_owner;

    insert into tcg.owner_memberships(user_id, owner_id, role, active)
    values (v_user_id, v_owner.id, 'PLATFORM_ADMIN', true);

    update tcg.founder_invites
       set redeemed_by_user_id = v_user_id,
           redeemed_owner_id = v_owner.id,
           redeemed_at = now()
     where id = v_invite.id;

    insert into tcg.audit_events(
        actor, request_id, action, entity_type, entity_id, new_values
    )
    values (
        v_user_id::text,
        current_setting('tcg.request_id', true),
        'FOUNDER_INVITE_REDEEMED',
        'OWNER',
        v_owner.id,
        jsonb_build_object(
            'display_name', v_owner.display_name,
            'owner_type', v_owner.owner_type,
            'founder_slot', v_owner.founder_slot,
            'access_role', 'PLATFORM_ADMIN',
            'invite_id', v_invite.id
        )
    );

    return query
    select
        v_owner.id,
        v_owner.display_name,
        v_owner.owner_type,
        v_owner.founder_slot,
        'PLATFORM_ADMIN'::text;
end;
$function$;
