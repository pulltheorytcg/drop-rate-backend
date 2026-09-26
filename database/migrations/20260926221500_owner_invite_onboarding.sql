-- Restricted OWNER invitation/onboarding flow for third-party consignors.
-- Founder/admin invitations remain separate. OWNER invites can never grant PLATFORM_ADMIN.

create table if not exists tcg.owner_invites (
    id uuid primary key default gen_random_uuid(),
    token_hash text not null unique,
    invited_name text not null check (length(btrim(invited_name)) between 1 and 120),
    invited_email text not null check (
      length(btrim(invited_email)) between 3 and 320
      and position('@' in invited_email) > 1
    ),
    commission_bps integer not null default 1000
      check (commission_bps between 0 and 10000),
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

alter table tcg.owner_invites enable row level security;
alter table tcg.owner_invites force row level security;

revoke all on tcg.owner_invites from public;
revoke all on tcg.owner_invites from anon;
revoke all on tcg.owner_invites from authenticated;
revoke all on tcg.owner_invites from service_role;
revoke all on tcg.owner_invites from tcg_api;

create unique index if not exists owner_invites_open_email_key
on tcg.owner_invites(lower(invited_email))
where redeemed_at is null and revoked_at is null;

create or replace function tcg.create_owner_invite(
    p_token_hash text,
    p_invited_name text,
    p_invited_email text,
    p_commission_bps integer default 1000,
    p_expires_at timestamptz default (now() + interval '7 days')
)
returns table(
    id uuid,
    invited_name text,
    invited_email text,
    commission_bps integer,
    expires_at timestamptz,
    created_at timestamptz
)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_user_id uuid := tcg.current_user_id();
    v_admin_owner_id uuid;
    v_invite tcg.owner_invites%rowtype;
    v_email text := lower(btrim(p_invited_email));
begin
    if v_user_id is null then
        raise exception 'Authenticated user required' using errcode = '42501';
    end if;

    select m.owner_id
      into v_admin_owner_id
      from tcg.owner_memberships m
      join tcg.owners o on o.id=m.owner_id
     where m.user_id=v_user_id
       and m.active
       and m.role='PLATFORM_ADMIN'
       and o.active
     order by m.created_at,m.id
     limit 1;

    if v_admin_owner_id is null then
        raise exception 'Platform administrator membership required' using errcode='42501';
    end if;

    if p_token_hash is null or length(btrim(p_token_hash)) < 32 then
        raise exception 'Invalid invite token hash' using errcode='22023';
    end if;
    if length(btrim(p_invited_name)) < 1 or length(btrim(p_invited_name)) > 120 then
        raise exception 'Invalid invited name' using errcode='22023';
    end if;
    if length(v_email) < 3 or length(v_email) > 320 or position('@' in v_email) <= 1 then
        raise exception 'Invalid invited email' using errcode='22023';
    end if;
    if p_commission_bps < 0 or p_commission_bps > 10000 then
        raise exception 'Commission basis points must be between 0 and 10000' using errcode='22023';
    end if;
    if p_expires_at <= now() then
        raise exception 'Invite expiry must be in the future' using errcode='22023';
    end if;

    update tcg.owner_invites
       set revoked_at=now()
     where lower(invited_email)=v_email
       and redeemed_at is null
       and revoked_at is null
       and expires_at <= now();

    insert into tcg.owner_invites(
        token_hash,invited_name,invited_email,commission_bps,
        created_by_owner_id,expires_at
    )
    values(
        btrim(p_token_hash),btrim(p_invited_name),v_email,p_commission_bps,
        v_admin_owner_id,p_expires_at
    )
    returning * into v_invite;

    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,new_values
    )
    values(
        v_user_id::text,
        nullif(current_setting('tcg.request_id',true),''),
        'OWNER_INVITE_CREATED',
        'OWNER_INVITE',
        v_invite.id,
        jsonb_build_object(
          'invited_name',v_invite.invited_name,
          'invited_email',v_invite.invited_email,
          'commission_bps',v_invite.commission_bps,
          'expires_at',v_invite.expires_at
        )
    );

    return query
    select
      v_invite.id,v_invite.invited_name,v_invite.invited_email,
      v_invite.commission_bps,v_invite.expires_at,v_invite.created_at;
end;
$function$;

create or replace function tcg.preview_owner_invite(p_token_hash text)
returns table(
    invited_name text,
    commission_bps integer,
    expires_at timestamptz,
    available boolean
)
language sql
security definer
set search_path = pg_catalog, tcg
as $function$
    select
      i.invited_name,
      i.commission_bps,
      i.expires_at,
      (
        i.redeemed_at is null
        and i.revoked_at is null
        and i.expires_at > now()
      ) as available
    from tcg.owner_invites i
    where i.token_hash=btrim(p_token_hash)
    limit 1
$function$;

create or replace function tcg.redeem_owner_invite(
    p_token_hash text,
    p_display_name text,
    p_authenticated_email text
)
returns table(
    owner_id uuid,
    display_name text,
    owner_type text,
    commission_bps integer,
    role text
)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_user_id uuid := tcg.current_user_id();
    v_invite tcg.owner_invites%rowtype;
    v_owner tcg.owners%rowtype;
    v_email text := lower(btrim(p_authenticated_email));
begin
    if v_user_id is null then
        raise exception 'Authenticated user required' using errcode='42501';
    end if;
    if v_email is null or length(v_email) < 3 then
        raise exception 'Verified account email is required' using errcode='42501';
    end if;

    if exists (
      select 1 from tcg.owner_memberships m
      where m.user_id=v_user_id and m.active
    ) then
        raise exception 'Account is already linked to an owner' using errcode='23505';
    end if;

    select *
      into v_invite
      from tcg.owner_invites i
     where i.token_hash=btrim(p_token_hash)
     for update;

    if v_invite.id is null then
        raise exception 'Invite not found' using errcode='22023';
    end if;
    if v_invite.revoked_at is not null then
        raise exception 'Invite has been revoked' using errcode='22023';
    end if;
    if v_invite.redeemed_at is not null then
        raise exception 'Invite has already been redeemed' using errcode='23505';
    end if;
    if v_invite.expires_at <= now() then
        raise exception 'Invite has expired' using errcode='22023';
    end if;
    if lower(v_invite.invited_email) <> v_email then
        raise exception 'Invite email does not match this authenticated account'
          using errcode='42501';
    end if;

    insert into tcg.owners(display_name,owner_type,commission_bps)
    values(
      coalesce(nullif(btrim(p_display_name),''),v_invite.invited_name),
      'CONSIGNOR',
      v_invite.commission_bps
    )
    returning * into v_owner;

    insert into tcg.owner_memberships(user_id,owner_id,role,active)
    values(v_user_id,v_owner.id,'OWNER',true);

    update tcg.owner_invites
       set redeemed_by_user_id=v_user_id,
           redeemed_owner_id=v_owner.id,
           redeemed_at=now()
     where id=v_invite.id;

    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,new_values
    )
    values(
        v_user_id::text,
        nullif(current_setting('tcg.request_id',true),''),
        'OWNER_INVITE_REDEEMED',
        'OWNER',
        v_owner.id,
        jsonb_build_object(
          'display_name',v_owner.display_name,
          'owner_type',v_owner.owner_type,
          'commission_bps',v_owner.commission_bps,
          'access_role','OWNER',
          'invite_id',v_invite.id
        )
    );

    return query
    select
      v_owner.id,v_owner.display_name,v_owner.owner_type,
      v_owner.commission_bps,'OWNER'::text;
end;
$function$;

create or replace function tcg.revoke_owner_invite(p_invite_id uuid)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_user_id uuid := tcg.current_user_id();
    v_is_admin boolean;
begin
    select exists(
      select 1
      from tcg.owner_memberships m
      join tcg.owners o on o.id=m.owner_id
      where m.user_id=v_user_id
        and m.active
        and m.role='PLATFORM_ADMIN'
        and o.active
    ) into v_is_admin;

    if not coalesce(v_is_admin,false) then
      raise exception 'Platform administrator membership required' using errcode='42501';
    end if;

    update tcg.owner_invites
       set revoked_at=now()
     where id=p_invite_id
       and redeemed_at is null
       and revoked_at is null;

    if not found then
      return false;
    end if;

    insert into tcg.audit_events(
      actor,request_id,action,entity_type,entity_id,new_values
    ) values(
      v_user_id::text,
      nullif(current_setting('tcg.request_id',true),''),
      'OWNER_INVITE_REVOKED',
      'OWNER_INVITE',
      p_invite_id,
      jsonb_build_object('revoked_at',now())
    );

    return true;
end;
$function$;

revoke all on function tcg.create_owner_invite(text,text,text,integer,timestamptz) from public;
revoke all on function tcg.preview_owner_invite(text) from public;
revoke all on function tcg.redeem_owner_invite(text,text,text) from public;
revoke all on function tcg.revoke_owner_invite(uuid) from public;

grant execute on function tcg.create_owner_invite(text,text,text,integer,timestamptz) to tcg_api;
grant execute on function tcg.preview_owner_invite(text) to tcg_api;
grant execute on function tcg.redeem_owner_invite(text,text,text) to tcg_api;
grant execute on function tcg.revoke_owner_invite(uuid) to tcg_api;
