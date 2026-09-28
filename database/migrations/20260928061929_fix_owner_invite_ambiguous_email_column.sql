-- Fix PL/pgSQL output-column ambiguity in owner invite creation.
-- The RETURNS TABLE column invited_email becomes a PL/pgSQL variable, so all
-- owner_invites references in the expiry cleanup must be table-qualified.

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
as $$
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

    update tcg.owner_invites i
       set revoked_at=now()
     where lower(i.invited_email)=v_email
       and i.redeemed_at is null
       and i.revoked_at is null
       and i.expires_at <= now();

    insert into tcg.owner_invites(
        token_hash,invited_name,invited_email,commission_bps,
        created_by_owner_id,expires_at
    )
    values(
        btrim(p_token_hash),btrim(p_invited_name),v_email,p_commission_bps,
        v_admin_owner_id,p_expires_at
    )
    returning * into v_invite;

    insert into tcg.audit_events(actor,request_id,action,entity_type,entity_id,new_values)
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
    select v_invite.id,v_invite.invited_name,v_invite.invited_email,
           v_invite.commission_bps,v_invite.expires_at,v_invite.created_at;
end;
$$;

revoke all on function tcg.create_owner_invite(text,text,text,integer,timestamptz)
from public,anon,authenticated,service_role;
grant execute on function tcg.create_owner_invite(text,text,text,integer,timestamptz)
to tcg_api;
