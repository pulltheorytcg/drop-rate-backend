begin;
-- Catalogue-only context. No FK or write path into inventory/financial records.
create table tcg.reference_regional_price_context (
 reference_key text primary key check(reference_key ~ '^r:[a-f0-9]{32}$'),
 identity_sha256 text not null check(identity_sha256 ~ '^[a-f0-9]{64}$'),
 quotes jsonb not null default '[]'::jsonb check(jsonb_typeof(quotes)='array' and octet_length(quotes::text)<=65536),
 checked_at timestamptz,
 expires_at timestamptz,
 retry_after timestamptz,
 lease_token uuid,
 lease_until timestamptz,
 check((lease_token is null)=(lease_until is null))
);
create table tcg.reference_regional_price_history (
 reference_key text not null,
 identity_sha256 text not null,
 quotes_sha256 text not null,
 quotes jsonb not null check(jsonb_typeof(quotes)='array' and octet_length(quotes::text)<=65536),
 recorded_at timestamptz not null default clock_timestamp(),
 primary key(reference_key,identity_sha256,quotes_sha256)
);
create table tcg.reference_regional_provider_budget (
 provider text primary key check(provider='TCGDEX'),
 request_day date not null,
 requests integer not null default 0 check(requests between 0 and 500),
 blocked_until timestamptz
);
-- Only the backend DB role receives grants. Existing API membership checks apply.
alter table tcg.reference_regional_price_context enable row level security;
alter table tcg.reference_regional_price_context force row level security;
alter table tcg.reference_regional_price_history enable row level security;
alter table tcg.reference_regional_price_history force row level security;
alter table tcg.reference_regional_provider_budget enable row level security;
alter table tcg.reference_regional_provider_budget force row level security;
revoke all on tcg.reference_regional_price_context,tcg.reference_regional_price_history,tcg.reference_regional_provider_budget from public,anon,authenticated,service_role,tcg_api;
grant select,insert,update on tcg.reference_regional_price_context,tcg.reference_regional_provider_budget to tcg_api;
grant select,insert on tcg.reference_regional_price_history to tcg_api;
create policy regional_context_backend on tcg.reference_regional_price_context to tcg_api
 using(tcg.current_user_id() is not null) with check(tcg.current_user_id() is not null);
create policy regional_history_read on tcg.reference_regional_price_history for select to tcg_api using(tcg.current_user_id() is not null);
create policy regional_history_insert on tcg.reference_regional_price_history for insert to tcg_api with check(tcg.current_user_id() is not null);
create policy regional_budget_backend on tcg.reference_regional_provider_budget to tcg_api
 using(tcg.current_user_id() is not null) with check(tcg.current_user_id() is not null);
comment on table tcg.reference_regional_price_context is 'Exact regional catalogue aggregates only; never physical Market Value, Store Price, portfolio or settlement input.';
comment on table tcg.reference_regional_price_history is 'Append-only regional aggregate observations retaining original provider and FX timestamps.';
commit;
