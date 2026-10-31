begin;

-- A marketing opt-in is deliberately separate from an authenticated seller account.
-- Public browser roles cannot read or write this table through the Data API.
create table if not exists tcg.seller_hub_launch_waitlist (
    id uuid primary key default gen_random_uuid(),
    email text not null,
    display_name text not null default '',
    interest text not null default 'CARDS',
    status text not null default 'AWAITING_LAUNCH',
    consent_version text not null default 'seller-hub-launch-2026-10-31',
    consented_at timestamptz not null default now(),
    source text not null default 'app.droprate.co.uk',
    created_at timestamptz not null default now(),
    constraint seller_hub_launch_email_format check (
        email = lower(btrim(email))
        and length(email) between 5 and 254
        and email ~ '^[^[:space:]@]+@[^[:space:]@.]+(\.[^[:space:]@.]+)+$'
    ),
    constraint seller_hub_launch_name_length check (length(display_name) <= 120),
    constraint seller_hub_launch_interest_allowed check (interest in ('CARDS','SEALED','COMICS_MANGA','OTHER')),
    constraint seller_hub_launch_status_allowed check (status in ('AWAITING_LAUNCH','NOTIFIED','UNSUBSCRIBED'))
);

create unique index if not exists seller_hub_launch_waitlist_email_unique
    on tcg.seller_hub_launch_waitlist (email);

alter table tcg.seller_hub_launch_waitlist enable row level security;
alter table tcg.seller_hub_launch_waitlist force row level security;

revoke all on tcg.seller_hub_launch_waitlist from public, anon, authenticated, service_role, tcg_api;

-- The existing FastAPI tcg_api database role may only perform this narrow,
-- idempotent opt-in through a private, fixed-purpose function.
create or replace function tcg_private.register_seller_hub_interest(
    p_email text,
    p_display_name text,
    p_interest text,
    p_consent boolean
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_email text := lower(btrim(coalesce(p_email, '')));
    v_display_name text := btrim(coalesce(p_display_name, ''));
    v_created_id uuid;
begin
    if p_consent is distinct from true
       or length(v_email) < 5 or length(v_email) > 254
       or v_email !~ '^[^[:space:]@]+@[^[:space:]@.]+(\.[^[:space:]@.]+)+$'
       or length(v_display_name) > 120
       or p_interest is null
       or p_interest not in ('CARDS','SEALED','COMICS_MANGA','OTHER') then
        raise exception 'Invalid Seller Hub launch registration' using errcode = '22023';
    end if;

    insert into tcg.seller_hub_launch_waitlist (email, display_name, interest)
    values (v_email, v_display_name, p_interest)
    on conflict (email) do update
       set display_name = excluded.display_name,
           interest = excluded.interest,
           status = 'AWAITING_LAUNCH',
           consented_at = now(),
           consent_version = 'seller-hub-launch-2026-10-31'
     where seller_hub_launch_waitlist.status = 'UNSUBSCRIBED'
    returning id into v_created_id;

    return v_created_id is not null;
end;
$function$;

revoke all on function tcg_private.register_seller_hub_interest(text,text,text,boolean)
    from public, anon, authenticated, service_role, tcg_api;
grant execute on function tcg_private.register_seller_hub_interest(text,text,text,boolean) to tcg_api;

commit;
