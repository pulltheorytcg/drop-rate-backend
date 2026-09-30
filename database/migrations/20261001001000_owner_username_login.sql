begin;

create table if not exists tcg.owner_login_failures (
    id bigint generated always as identity primary key,
    occurred_at timestamptz not null default clock_timestamp(),
    network_hash text not null,
    identifier_hash text not null,
    constraint owner_login_failures_network_hash_check
        check (network_hash ~ '^[0-9a-f]{64}$'),
    constraint owner_login_failures_identifier_hash_check
        check (identifier_hash ~ '^[0-9a-f]{64}$')
);

create index if not exists owner_login_failures_network_recent_idx
    on tcg.owner_login_failures (network_hash, occurred_at desc);

create index if not exists owner_login_failures_identifier_recent_idx
    on tcg.owner_login_failures (identifier_hash, occurred_at desc);

alter table tcg.owner_login_failures enable row level security;

revoke all on table tcg.owner_login_failures from public, anon, authenticated;
revoke all on sequence tcg.owner_login_failures_id_seq from public, anon, authenticated;

create or replace function tcg.resolve_owner_login_email(p_username text)
returns text
language sql
security definer
set search_path = pg_catalog, tcg, auth
stable
as $function$
    select u.email::text
    from tcg.owners o
    join tcg.owner_memberships m
      on m.owner_id=o.id
     and m.active
    join auth.users u
      on u.id=m.user_id
    where o.active
      and o.username is not null
      and lower(o.username)=lower(btrim(p_username))
      and m.role in ('OWNER','PLATFORM_ADMIN')
      and u.email is not null
    order by m.created_at,m.id
    limit 1
$function$;

revoke all on function tcg.resolve_owner_login_email(text) from public, anon, authenticated;
grant execute on function tcg.resolve_owner_login_email(text) to tcg_api;

create or replace function tcg.owner_login_rate_limit_status(
    p_network_hash text,
    p_identifier_hash text
)
returns table(
    allowed boolean,
    retry_after_seconds integer,
    identifier_failures integer,
    network_failures integer
)
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
declare
    v_now timestamptz := clock_timestamp();
    v_window interval := interval '15 minutes';
    v_identifier_failures integer;
    v_network_failures integer;
    v_identifier_oldest timestamptz;
    v_network_oldest timestamptz;
    v_retry integer := 0;
begin
    if p_network_hash !~ '^[0-9a-f]{64}$'
       or p_identifier_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'Invalid login throttle key' using errcode='22023';
    end if;

    select count(*)::int, min(occurred_at)
      into v_identifier_failures, v_identifier_oldest
      from tcg.owner_login_failures
     where identifier_hash=p_identifier_hash
       and occurred_at > v_now-v_window;

    select count(*)::int, min(occurred_at)
      into v_network_failures, v_network_oldest
      from tcg.owner_login_failures
     where network_hash=p_network_hash
       and occurred_at > v_now-v_window;

    if v_identifier_failures >= 8 and v_identifier_oldest is not null then
        v_retry := greatest(
            v_retry,
            ceil(extract(epoch from ((v_identifier_oldest+v_window)-v_now)))::int
        );
    end if;

    if v_network_failures >= 30 and v_network_oldest is not null then
        v_retry := greatest(
            v_retry,
            ceil(extract(epoch from ((v_network_oldest+v_window)-v_now)))::int
        );
    end if;

    return query
    select
        (v_identifier_failures < 8 and v_network_failures < 30),
        greatest(v_retry,0),
        v_identifier_failures,
        v_network_failures;
end;
$function$;

revoke all on function tcg.owner_login_rate_limit_status(text,text)
    from public, anon, authenticated;
grant execute on function tcg.owner_login_rate_limit_status(text,text) to tcg_api;

create or replace function tcg.record_owner_login_failure(
    p_network_hash text,
    p_identifier_hash text
)
returns void
language plpgsql
security definer
set search_path = pg_catalog, tcg
as $function$
begin
    if p_network_hash !~ '^[0-9a-f]{64}$'
       or p_identifier_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'Invalid login throttle key' using errcode='22023';
    end if;

    insert into tcg.owner_login_failures(network_hash,identifier_hash)
    values (p_network_hash,p_identifier_hash);

    delete from tcg.owner_login_failures
     where occurred_at < clock_timestamp()-interval '48 hours';
end;
$function$;

revoke all on function tcg.record_owner_login_failure(text,text)
    from public, anon, authenticated;
grant execute on function tcg.record_owner_login_failure(text,text) to tcg_api;

commit;
