begin;

-- Existing launch opt-ins were collected before Shopify contact storage was
-- disclosed. They must NOT be exported merely because this migration landed.
alter table tcg.seller_hub_launch_waitlist
    add column shopify_sync_state text not null default 'NOT_REQUESTED',
    add column shopify_sync_attempts integer not null default 0,
    add column shopify_next_attempt_at timestamptz not null default now(),
    add column shopify_lease_token uuid,
    add column shopify_claimed_at timestamptz,
    add column shopify_customer_gid text,
    add column shopify_synced_at timestamptz,
    add constraint seller_hub_shopify_sync_state_allowed
        check (shopify_sync_state in ('NOT_REQUESTED', 'PENDING', 'IN_PROGRESS', 'RETRY', 'SYNCED')),
    add constraint seller_hub_shopify_sync_attempts_valid check (shopify_sync_attempts >= 0),
    add constraint seller_hub_shopify_customer_gid_valid check (
        shopify_customer_gid is null or shopify_customer_gid ~ '^gid://shopify/Customer/[0-9]+$'
    );

create index seller_hub_shopify_sync_due_idx
    on tcg.seller_hub_launch_waitlist (shopify_next_attempt_at, created_at)
    where shopify_sync_state in ('PENDING', 'RETRY', 'IN_PROGRESS');

-- Only the updated, explicitly-disclosed UI/API can request Shopify contact
-- storage. The original four-argument signup function stays available for
-- in-flight old browser assets and still saves opt-ins without exporting them.
create function tcg_private.register_seller_hub_interest_for_shopify(
    p_email text,
    p_display_name text,
    p_interest text,
    p_consent boolean,
    p_shopify_contact_consent boolean
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_email text := lower(btrim(coalesce(p_email, '')));
    v_created_or_reactivated boolean;
begin
    if p_shopify_contact_consent is distinct from true then
        raise exception 'Shopify contact storage requires explicit consent' using errcode = '22023';
    end if;

    v_created_or_reactivated := tcg_private.register_seller_hub_interest(
        p_email, p_display_name, p_interest, p_consent
    );

    -- Re-opt-in after UNSUBSCRIBED must refresh the remote tag. Repeated
    -- registered requests must not restart an already-queued/synced operation.
    update tcg.seller_hub_launch_waitlist
       set shopify_sync_state = 'PENDING',
           shopify_sync_attempts = 0,
           shopify_next_attempt_at = now(),
           shopify_lease_token = null,
           shopify_claimed_at = null,
           shopify_synced_at = null,
           consent_version = 'seller-hub-shopify-2026-10-31',
           consented_at = now()
     where email = v_email
       and status <> 'UNSUBSCRIBED'
       and (shopify_sync_state = 'NOT_REQUESTED' or
            (v_created_or_reactivated and shopify_sync_state <> 'PENDING'));

    return v_created_or_reactivated;
end;
$function$;

revoke all on function tcg_private.register_seller_hub_interest_for_shopify(text,text,text,boolean,boolean)
    from public, anon, authenticated, service_role, tcg_api;
grant execute on function tcg_private.register_seller_hub_interest_for_shopify(text,text,text,boolean,boolean)
    to tcg_api;

-- Atomic, bounded claims with SKIP LOCKED prevent concurrent Railway replicas
-- from processing the same signup. An abandoned lease becomes claimable again.
create function tcg_private.claim_seller_hub_shopify_sync(p_limit integer)
returns table (waitlist_id uuid, contact_email text, lease_token uuid)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
begin
    if p_limit is null or p_limit < 1 or p_limit > 10 then
        raise exception 'Invalid Seller Hub Shopify batch size' using errcode = '22023';
    end if;

    return query
    with due as (
        select w.id
          from tcg.seller_hub_launch_waitlist w
         where w.status <> 'UNSUBSCRIBED'
           and ((w.shopify_sync_state in ('PENDING', 'RETRY')
                 and w.shopify_next_attempt_at <= now())
              or (w.shopify_sync_state = 'IN_PROGRESS'
                  and w.shopify_claimed_at < now() - interval '10 minutes'))
         order by w.shopify_next_attempt_at, w.created_at, w.id
         for update skip locked
         limit p_limit
    )
    update tcg.seller_hub_launch_waitlist w
       set shopify_sync_state = 'IN_PROGRESS',
           shopify_sync_attempts = w.shopify_sync_attempts + 1,
           shopify_claimed_at = now(),
           shopify_lease_token = gen_random_uuid()
      from due
     where w.id = due.id
     returning w.id, w.email, w.shopify_lease_token;
end;
$function$;

revoke all on function tcg_private.claim_seller_hub_shopify_sync(integer)
    from public, anon, authenticated, service_role, tcg_api;
grant execute on function tcg_private.claim_seller_hub_shopify_sync(integer) to tcg_api;

-- Acknowledgements are protected by the claim token. Partial Shopify writes
-- are retried with exponential backoff; email upsert and tagsAdd are idempotent.
create function tcg_private.finish_seller_hub_shopify_sync(
    p_waitlist_id uuid,
    p_lease_token uuid,
    p_customer_gid text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_updated uuid;
begin
    if p_customer_gid is not null
       and p_customer_gid !~ '^gid://shopify/Customer/[0-9]+$' then
        raise exception 'Invalid Shopify customer identifier' using errcode = '22023';
    end if;

    update tcg.seller_hub_launch_waitlist w
       set shopify_sync_state = case when p_customer_gid is not null then 'SYNCED' else 'RETRY' end,
           shopify_customer_gid = coalesce(p_customer_gid, w.shopify_customer_gid),
           shopify_synced_at = case when p_customer_gid is not null then now() else w.shopify_synced_at end,
           shopify_next_attempt_at = case when p_customer_gid is not null then now()
                else now() + make_interval(secs => least(86400, (power(2, least(w.shopify_sync_attempts, 10)) * 60)::integer)) end,
           shopify_lease_token = null,
           shopify_claimed_at = null
     where w.id = p_waitlist_id
       and w.shopify_sync_state = 'IN_PROGRESS'
       and w.shopify_lease_token = p_lease_token
       and w.status <> 'UNSUBSCRIBED'
     returning w.id into v_updated;

    return v_updated is not null;
end;
$function$;

revoke all on function tcg_private.finish_seller_hub_shopify_sync(uuid,uuid,text)
    from public, anon, authenticated, service_role, tcg_api;
grant execute on function tcg_private.finish_seller_hub_shopify_sync(uuid,uuid,text) to tcg_api;

commit;
