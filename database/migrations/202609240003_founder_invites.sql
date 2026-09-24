-- Invite-only founder onboarding and membership-safe multi-owner access.

create table if not exists tcg.founder_invites (
    id uuid primary key default gen_random_uuid(),
    token_hash text not null unique,
    invited_name text not null check (length(btrim(invited_name)) between 1 and 120),
    invited_email text,
    founder_slot smallint not null check (founder_slot between 1 and 3),
    created_by_owner_id uuid not null references tcg.owners(id),
    expires_at timestamptz not null,
    redeemed_by_user_id uuid,
    redeemed_owner_id uuid references tcg.owners(id),
    redeemed_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz not null default now(),
    check (
        (redeemed_at is null and redeemed_by_user_id is null and redeemed_owner_id is null)
        or
        (redeemed_at is not null and redeemed_by_user_id is not null and redeemed_owner_id is not null)
    )
);

alter table tcg.founder_invites enable row level security;

revoke all on tcg.founder_invites from public;
revoke all on tcg.founder_invites from tcg_api;

create unique index if not exists founder_invites_open_slot_key
on tcg.founder_invites(founder_slot)
where redeemed_at is null and revoked_at is null;

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
as $$
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
       and m.role = 'FOUNDER'
       and o.active
       and o.owner_type = 'FOUNDER'
     order by m.created_at
     limit 1;

    if v_owner_id is null then
        raise exception 'Founder membership required' using errcode = '42501';
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
$$;

create or replace function tcg.preview_founder_invite(p_token_hash text)
returns table(
    invited_name text,
    invited_email text,
    founder_slot smallint,
    expires_at timestamptz,
    available boolean
)
language sql
security definer
set search_path = pg_catalog, tcg
as $$
    select
        i.invited_name,
        i.invited_email,
        i.founder_slot,
        i.expires_at,
        (
            i.redeemed_at is null
            and i.revoked_at is null
            and i.expires_at > now()
        ) as available
    from tcg.founder_invites i
    where i.token_hash = btrim(p_token_hash)
    limit 1;
$$;

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
as $$
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
    values (v_user_id, v_owner.id, 'FOUNDER', true);

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
            'invite_id', v_invite.id
        )
    );

    return query
    select
        v_owner.id,
        v_owner.display_name,
        v_owner.owner_type,
        v_owner.founder_slot,
        'FOUNDER'::text;
end;
$$;

revoke all on function tcg.create_founder_invite(text,text,smallint,text,timestamptz) from public;
revoke all on function tcg.preview_founder_invite(text) from public;
revoke all on function tcg.redeem_founder_invite(text,text,text) from public;

grant execute on function tcg.create_founder_invite(text,text,smallint,text,timestamptz) to tcg_api;
grant execute on function tcg.preview_founder_invite(text) to tcg_api;
grant execute on function tcg.redeem_founder_invite(text,text,text) to tcg_api;
