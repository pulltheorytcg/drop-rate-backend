-- Branded seller/consignor invitation delivery and auditable onboarding acknowledgement.
-- The raw invite token is never stored: only SHA-256 hashes remain in PostgreSQL.
-- Resends rotate the token hash before a new email is sent so an old invite link
-- becomes invalid if delivery is uncertain.

begin;

alter table tcg.owner_invites
    add column if not exists email_status text not null default 'NOT_SENT',
    add column if not exists email_provider text,
    add column if not exists email_provider_message_id text,
    add column if not exists email_attempt_count integer not null default 0,
    add column if not exists email_last_attempt_at timestamptz,
    add column if not exists email_sent_at timestamptz,
    add column if not exists email_delivered_at timestamptz,
    add column if not exists email_last_event_at timestamptz,
    add column if not exists email_last_error_code text,
    add column if not exists onboarding_ack_version integer,
    add column if not exists onboarding_acknowledged_at timestamptz;

alter table tcg.owner_invites
    drop constraint if exists owner_invites_email_status_check;
alter table tcg.owner_invites
    add constraint owner_invites_email_status_check
    check (email_status in ('NOT_SENT','SENT','DELIVERED','FAILED','BOUNCED'));

alter table tcg.owner_invites
    drop constraint if exists owner_invites_email_attempt_count_check;
alter table tcg.owner_invites
    add constraint owner_invites_email_attempt_count_check
    check (email_attempt_count >= 0);

alter table tcg.owner_invites
    drop constraint if exists owner_invites_onboarding_ack_check;
alter table tcg.owner_invites
    add constraint owner_invites_onboarding_ack_check
    check (
        (onboarding_acknowledged_at is null and onboarding_ack_version is null)
        or
        (onboarding_acknowledged_at is not null and onboarding_ack_version is not null)
    );

create unique index if not exists owner_invites_provider_message_uidx
    on tcg.owner_invites(email_provider,email_provider_message_id)
    where email_provider is not null and email_provider_message_id is not null;

create or replace function tcg.list_owner_invites(p_limit integer default 25)
returns table(
    id uuid,
    invited_name text,
    invited_email text,
    commission_bps integer,
    expires_at timestamptz,
    redeemed_at timestamptz,
    revoked_at timestamptz,
    email_status text,
    email_provider text,
    email_attempt_count integer,
    email_last_attempt_at timestamptz,
    email_sent_at timestamptz,
    email_delivered_at timestamptz,
    email_last_event_at timestamptz,
    email_last_error_code text,
    onboarding_ack_version integer,
    onboarding_acknowledged_at timestamptz,
    onboarding_status text,
    created_at timestamptz
)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $$
declare
    v_user_id uuid := tcg.current_user_id();
begin
    if p_limit < 1 or p_limit > 100 then
        raise exception 'Invite list limit must be between 1 and 100' using errcode='22023';
    end if;

    if not exists(
      select 1
      from tcg.owner_memberships m
      join tcg.owners o on o.id=m.owner_id
      where m.user_id=v_user_id
        and m.active
        and m.role='PLATFORM_ADMIN'
        and o.active
    ) then
        raise exception 'Platform administrator membership required' using errcode='42501';
    end if;

    return query
    select
      i.id,
      i.invited_name,
      i.invited_email,
      i.commission_bps,
      i.expires_at,
      i.redeemed_at,
      i.revoked_at,
      i.email_status,
      i.email_provider,
      i.email_attempt_count,
      i.email_last_attempt_at,
      i.email_sent_at,
      i.email_delivered_at,
      i.email_last_event_at,
      i.email_last_error_code,
      i.onboarding_ack_version,
      i.onboarding_acknowledged_at,
      case
        when i.redeemed_at is not null then 'ACCEPTED'
        when i.revoked_at is not null then 'REVOKED'
        when i.expires_at <= now() then 'EXPIRED'
        else 'INVITED'
      end::text as onboarding_status,
      i.created_at
    from tcg.owner_invites i
    order by i.created_at desc,i.id desc
    limit p_limit;
end;
$$;

create or replace function tcg.prepare_owner_invite_resend(
    p_invite_id uuid,
    p_token_hash text
)
returns table(
    id uuid,
    invited_name text,
    invited_email text,
    commission_bps integer,
    expires_at timestamptz,
    email_attempt_count integer
)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $$
declare
    v_user_id uuid := tcg.current_user_id();
    v_invite tcg.owner_invites%rowtype;
begin
    if p_token_hash is null or length(btrim(p_token_hash)) < 32 then
        raise exception 'Invalid invite token hash' using errcode='22023';
    end if;

    if not exists(
      select 1
      from tcg.owner_memberships m
      join tcg.owners o on o.id=m.owner_id
      where m.user_id=v_user_id
        and m.active
        and m.role='PLATFORM_ADMIN'
        and o.active
    ) then
        raise exception 'Platform administrator membership required' using errcode='42501';
    end if;

    select * into v_invite
    from tcg.owner_invites i
    where i.id=p_invite_id
    for update;

    if v_invite.id is null then
        raise exception 'Owner invite not found' using errcode='22023';
    end if;
    if v_invite.redeemed_at is not null then
        raise exception 'Owner invite has already been accepted' using errcode='55000';
    end if;
    if v_invite.revoked_at is not null then
        raise exception 'Owner invite has been revoked' using errcode='55000';
    end if;
    if v_invite.expires_at <= now() then
        raise exception 'Owner invite has expired' using errcode='55000';
    end if;

    update tcg.owner_invites i
    set token_hash=btrim(p_token_hash),
        email_status='NOT_SENT',
        email_provider_message_id=null,
        email_last_error_code=null
    where i.id=p_invite_id
    returning * into v_invite;

    insert into tcg.audit_events(
      actor,request_id,action,entity_type,entity_id,new_values
    ) values(
      v_user_id::text,
      nullif(current_setting('tcg.request_id',true),''),
      'OWNER_INVITE_RESEND_PREPARED',
      'OWNER_INVITE',
      v_invite.id,
      jsonb_build_object(
        'invited_email',v_invite.invited_email,
        'email_attempt_count',v_invite.email_attempt_count,
        'expires_at',v_invite.expires_at
      )
    );

    return query select
      v_invite.id,
      v_invite.invited_name,
      v_invite.invited_email,
      v_invite.commission_bps,
      v_invite.expires_at,
      v_invite.email_attempt_count;
end;
$$;

create or replace function tcg.record_owner_invite_email_result(
    p_invite_id uuid,
    p_status text,
    p_provider text,
    p_provider_message_id text default null,
    p_error_code text default null
)
returns table(
    id uuid,
    email_status text,
    email_provider text,
    email_provider_message_id text,
    email_attempt_count integer,
    email_last_attempt_at timestamptz,
    email_sent_at timestamptz,
    email_last_error_code text
)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $$
declare
    v_user_id uuid := tcg.current_user_id();
    v_status text := upper(btrim(coalesce(p_status,'')));
    v_provider text := upper(btrim(coalesce(p_provider,'')));
    v_error text := nullif(upper(left(
      regexp_replace(btrim(coalesce(p_error_code,'')),'[^A-Za-z0-9_.:-]+','_','g'),
      120
    )),'');
    v_invite tcg.owner_invites%rowtype;
begin
    if v_status not in ('SENT','FAILED') then
        raise exception 'Email result must be SENT or FAILED' using errcode='22023';
    end if;
    if char_length(v_provider) < 2 or char_length(v_provider) > 40 then
        raise exception 'Invalid email provider' using errcode='22023';
    end if;

    if not exists(
      select 1
      from tcg.owner_memberships m
      join tcg.owners o on o.id=m.owner_id
      where m.user_id=v_user_id
        and m.active
        and m.role='PLATFORM_ADMIN'
        and o.active
    ) then
        raise exception 'Platform administrator membership required' using errcode='42501';
    end if;

    update tcg.owner_invites i
    set email_status=v_status,
        email_provider=v_provider,
        email_provider_message_id=case
          when v_status='SENT' then nullif(btrim(p_provider_message_id),'')
          else null
        end,
        email_attempt_count=i.email_attempt_count+1,
        email_last_attempt_at=clock_timestamp(),
        email_sent_at=case
          when v_status='SENT' then clock_timestamp()
          else i.email_sent_at
        end,
        email_last_error_code=case
          when v_status='FAILED' then coalesce(v_error,'EMAIL_SEND_FAILED')
          else null
        end
    where i.id=p_invite_id
    returning * into v_invite;

    if v_invite.id is null then
        raise exception 'Owner invite not found' using errcode='22023';
    end if;

    insert into tcg.audit_events(
      actor,request_id,action,entity_type,entity_id,new_values
    ) values(
      v_user_id::text,
      nullif(current_setting('tcg.request_id',true),''),
      case when v_status='SENT'
        then 'OWNER_INVITE_EMAIL_SENT'
        else 'OWNER_INVITE_EMAIL_FAILED'
      end,
      'OWNER_INVITE',
      v_invite.id,
      jsonb_build_object(
        'email_status',v_invite.email_status,
        'email_provider',v_invite.email_provider,
        'email_attempt_count',v_invite.email_attempt_count,
        'email_last_error_code',v_invite.email_last_error_code
      )
    );

    return query select
      v_invite.id,
      v_invite.email_status,
      v_invite.email_provider,
      v_invite.email_provider_message_id,
      v_invite.email_attempt_count,
      v_invite.email_last_attempt_at,
      v_invite.email_sent_at,
      v_invite.email_last_error_code;
end;
$$;

create or replace function tcg.redeem_owner_invite(
    p_token_hash text,
    p_display_name text,
    p_authenticated_email text,
    p_ack_version integer
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
as $$
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
    if p_ack_version <> 1 then
        raise exception 'Current onboarding acknowledgement is required' using errcode='22023';
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
           redeemed_at=now(),
           onboarding_ack_version=p_ack_version,
           onboarding_acknowledged_at=now()
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
          'invite_id',v_invite.id,
          'onboarding_ack_version',p_ack_version
        )
    );

    return query
    select
      v_owner.id,v_owner.display_name,v_owner.owner_type,
      v_owner.commission_bps,'OWNER'::text;
end;
$$;

revoke all on function tcg.list_owner_invites(integer)
from public,anon,authenticated,service_role;
revoke all on function tcg.prepare_owner_invite_resend(uuid,text)
from public,anon,authenticated,service_role;
revoke all on function tcg.record_owner_invite_email_result(uuid,text,text,text,text)
from public,anon,authenticated,service_role;
revoke all on function tcg.redeem_owner_invite(text,text,text,integer)
from public,anon,authenticated,service_role;

-- The previous three-argument redeem function did not require onboarding
-- acknowledgement. Remove application-role execution so the new acknowledgement
-- contract cannot be bypassed by old backend code.
revoke all on function tcg.redeem_owner_invite(text,text,text) from tcg_api;

grant execute on function tcg.list_owner_invites(integer) to tcg_api;
grant execute on function tcg.prepare_owner_invite_resend(uuid,text) to tcg_api;
grant execute on function tcg.record_owner_invite_email_result(uuid,text,text,text,text) to tcg_api;
grant execute on function tcg.redeem_owner_invite(text,text,text,integer) to tcg_api;


create table if not exists tcg.owner_invite_email_events (
    id uuid primary key default gen_random_uuid(),
    provider text not null check (provider in ('RESEND')),
    webhook_event_id text not null,
    provider_message_id text not null,
    event_type text not null,
    payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
    occurred_at timestamptz not null,
    created_at timestamptz not null default clock_timestamp(),
    constraint owner_invite_email_events_provider_event_uidx
      unique(provider,webhook_event_id)
);

create index if not exists owner_invite_email_events_message_idx
    on tcg.owner_invite_email_events(provider,provider_message_id,occurred_at desc);

alter table tcg.owner_invite_email_events enable row level security;
alter table tcg.owner_invite_email_events force row level security;

revoke all on tcg.owner_invite_email_events
from public,anon,authenticated,service_role,tcg_api;

create or replace function tcg.record_owner_invite_email_webhook(
    p_provider text,
    p_webhook_event_id text,
    p_provider_message_id text,
    p_event_type text,
    p_payload_sha256 text,
    p_occurred_at timestamptz
)
returns table(
    processed boolean,
    matched boolean,
    invite_id uuid,
    email_status text
)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $$
declare
    v_provider text := upper(btrim(coalesce(p_provider,'')));
    v_event_id text := btrim(coalesce(p_webhook_event_id,''));
    v_message_id text := btrim(coalesce(p_provider_message_id,''));
    v_event_type text := lower(btrim(coalesce(p_event_type,'')));
    v_inserted uuid;
    v_invite tcg.owner_invites%rowtype;
    v_status text;
begin
    if v_provider <> 'RESEND' then
        raise exception 'Unsupported email webhook provider' using errcode='22023';
    end if;
    if char_length(v_event_id) < 3 or char_length(v_event_id) > 255 then
        raise exception 'Invalid webhook event ID' using errcode='22023';
    end if;
    if char_length(v_message_id) < 3 or char_length(v_message_id) > 255 then
        raise exception 'Invalid provider message ID' using errcode='22023';
    end if;
    if v_event_type not in (
      'email.sent','email.delivered','email.delivery_delayed',
      'email.bounced','email.failed','email.suppressed','email.complained'
    ) then
        raise exception 'Unsupported email webhook event type' using errcode='22023';
    end if;
    if p_payload_sha256 is null
       or p_payload_sha256 !~ '^[0-9a-f]{64}$' then
        raise exception 'Invalid webhook payload fingerprint' using errcode='22023';
    end if;
    if p_occurred_at is null then
        raise exception 'Webhook occurred_at is required' using errcode='22023';
    end if;

    insert into tcg.owner_invite_email_events(
      provider,webhook_event_id,provider_message_id,event_type,
      payload_sha256,occurred_at
    ) values(
      v_provider,v_event_id,v_message_id,v_event_type,
      p_payload_sha256,p_occurred_at
    )
    on conflict(provider,webhook_event_id) do nothing
    returning id into v_inserted;

    if v_inserted is null then
        select i.* into v_invite
        from tcg.owner_invites i
        where i.email_provider=v_provider
          and i.email_provider_message_id=v_message_id
        limit 1;
        return query select
          false,
          v_invite.id is not null,
          v_invite.id,
          v_invite.email_status;
        return;
    end if;

    v_status := case
      when v_event_type='email.delivered' then 'DELIVERED'
      when v_event_type='email.bounced' then 'BOUNCED'
      when v_event_type in ('email.failed','email.suppressed','email.complained')
        then 'FAILED'
      when v_event_type='email.sent' then 'SENT'
      else null
    end;

    select i.* into v_invite
    from tcg.owner_invites i
    where i.email_provider=v_provider
      and i.email_provider_message_id=v_message_id
    for update;

    if v_invite.id is null then
        return query select true,false,null::uuid,null::text;
        return;
    end if;

    if v_status is not null then
        update tcg.owner_invites i
        set email_status=v_status,
            email_delivered_at=case
              when v_status='DELIVERED'
                then coalesce(i.email_delivered_at,p_occurred_at)
              else i.email_delivered_at
            end,
            email_last_event_at=p_occurred_at,
            email_last_error_code=case
              when v_status in ('FAILED','BOUNCED')
                then upper(replace(v_event_type,'.','_'))
              when v_status in ('SENT','DELIVERED')
                then null
              else i.email_last_error_code
            end
        where i.id=v_invite.id
          and (
            i.email_last_event_at is null
            or p_occurred_at >= i.email_last_event_at
          )
        returning * into v_invite;

        if v_invite.id is null then
            select i.* into v_invite
            from tcg.owner_invites i
            where i.email_provider=v_provider
              and i.email_provider_message_id=v_message_id
            limit 1;
        end if;
    end if;

    insert into tcg.audit_events(
      actor,request_id,action,entity_type,entity_id,new_values
    ) values(
      'resend-webhook',
      v_event_id,
      'OWNER_INVITE_EMAIL_EVENT',
      'OWNER_INVITE',
      v_invite.id,
      jsonb_build_object(
        'provider',v_provider,
        'event_type',v_event_type,
        'email_status',v_invite.email_status,
        'occurred_at',p_occurred_at
      )
    );

    return query select true,true,v_invite.id,v_invite.email_status;
end;
$$;

revoke all on function tcg.record_owner_invite_email_webhook(
  text,text,text,text,text,timestamptz
) from public,anon,authenticated,service_role;
grant execute on function tcg.record_owner_invite_email_webhook(
  text,text,text,text,text,timestamptz
) to tcg_api;

commit;
