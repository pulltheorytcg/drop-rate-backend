create table tcg.ebay_oauth_attempts (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references tcg.owners(id),
    user_id uuid not null references auth.users(id),
    state_sha256 text not null unique check (state_sha256 ~ '^[0-9a-f]{64}$'),
    expires_at timestamptz not null,
    consumed_at timestamptz,
    created_at timestamptz not null default clock_timestamp(),
    check (expires_at > created_at)
);

create index ebay_oauth_attempts_owner_created_idx
    on tcg.ebay_oauth_attempts(owner_id,created_at desc);

alter table tcg.ebay_oauth_attempts enable row level security;
alter table tcg.ebay_oauth_attempts force row level security;

create policy ebay_oauth_attempts_postgres
    on tcg.ebay_oauth_attempts for all to postgres
    using (true) with check (true);
create policy ebay_oauth_attempts_api
    on tcg.ebay_oauth_attempts for all to tcg_api
    using (true) with check (true);

revoke all on table tcg.ebay_oauth_attempts from anon, authenticated;
grant select,insert,update,delete on table tcg.ebay_oauth_attempts to tcg_api;

create table tcg.ebay_seller_connections (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null unique references tcg.owners(id),
    created_by_user_id uuid not null references auth.users(id),
    marketplace_id text not null default 'EBAY_GB' check (btrim(marketplace_id) <> ''),
    refresh_token_ciphertext text not null check (btrim(refresh_token_ciphertext) <> ''),
    granted_scopes text[] not null default '{}'::text[],
    status text not null default 'CONNECTED'
        check (status in ('CONNECTED','ACTION_REQUIRED','READY','DISCONNECTED','ERROR')),
    payment_policy_id text,
    fulfillment_policy_id text,
    return_policy_id text,
    merchant_location_key text,
    notification_destination_id text,
    notification_subscription_id text,
    connected_at timestamptz not null default clock_timestamp(),
    last_verified_at timestamptz,
    last_error_code text,
    version integer not null default 1 check (version >= 1),
    updated_at timestamptz not null default clock_timestamp()
);

create index ebay_seller_connections_status_idx
    on tcg.ebay_seller_connections(status,updated_at desc);
create index ebay_seller_connections_created_by_idx
    on tcg.ebay_seller_connections(created_by_user_id);

alter table tcg.ebay_seller_connections enable row level security;
alter table tcg.ebay_seller_connections force row level security;

create policy ebay_seller_connections_postgres
    on tcg.ebay_seller_connections for all to postgres
    using (true) with check (true);
create policy ebay_seller_connections_api_read
    on tcg.ebay_seller_connections for select to tcg_api
    using (owner_id in (select id from tcg.owners));
create policy ebay_seller_connections_api_insert
    on tcg.ebay_seller_connections for insert to tcg_api
    with check (owner_id in (select id from tcg.owners));
create policy ebay_seller_connections_api_update
    on tcg.ebay_seller_connections for update to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

revoke all on table tcg.ebay_seller_connections from anon, authenticated;
grant select,insert,update on table tcg.ebay_seller_connections to tcg_api;
revoke delete on table tcg.ebay_seller_connections from tcg_api;

create or replace function tcg.guard_ebay_seller_connection_owner()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if old.owner_id is distinct from new.owner_id
       or old.created_by_user_id is distinct from new.created_by_user_id then
        raise exception 'eBay seller connection ownership is immutable'
            using errcode='23514';
    end if;
    return new;
end;
$$;
revoke all on function tcg.guard_ebay_seller_connection_owner() from public;

create trigger ebay_seller_connection_owner_guard
    before update of owner_id,created_by_user_id
    on tcg.ebay_seller_connections
    for each row execute function tcg.guard_ebay_seller_connection_owner();

create or replace function tcg.audit_ebay_seller_connection_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values(
        coalesce(nullif(pg_catalog.current_setting('tcg.user_id',true),''),session_user::text),
        nullif(pg_catalog.current_setting('tcg.request_id',true),''),
        tg_op,
        tg_table_name,
        case when tg_op='DELETE' then old.id else new.id end,
        case when tg_op='INSERT' then null else pg_catalog.to_jsonb(old) - 'refresh_token_ciphertext' end,
        case when tg_op='DELETE' then null else pg_catalog.to_jsonb(new) - 'refresh_token_ciphertext' end
    );
    return null;
end;
$$;
revoke all on function tcg.audit_ebay_seller_connection_change() from public;

create trigger ebay_seller_connections_audit
    after insert or update or delete on tcg.ebay_seller_connections
    for each row execute function tcg.audit_ebay_seller_connection_change();
