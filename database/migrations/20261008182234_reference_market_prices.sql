begin;

-- Public provider reference cache only. Physical inventory prices and their
-- immutable market observations/snapshots are deliberately separate.
create table tcg.reference_market_prices (
 provider text not null,
 system_code text not null,
 language text not null,
 provider_id text not null,
 quotes jsonb not null default '[]'::jsonb check(jsonb_typeof(quotes)='array' and jsonb_array_length(quotes)<=40),
 market_value_minor bigint check(market_value_minor>0),
 market_value_high_minor bigint,
 pricing_updated_at timestamptz,
 checked_at timestamptz not null,
 expires_at timestamptz not null check(expires_at>checked_at),
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,provider_id)
   references tcg.reference_cards(provider,system_code,language,provider_id),
 check ((market_value_minor is null and market_value_high_minor is null and pricing_updated_at is null and quotes='[]'::jsonb)
     or (market_value_minor is not null and market_value_high_minor is not null and market_value_high_minor>=market_value_minor and pricing_updated_at is not null and jsonb_array_length(quotes)>0))
);
alter table tcg.reference_market_prices enable row level security;
alter table tcg.reference_market_prices force row level security;
create policy reference_market_prices_admin on tcg.reference_market_prices for all to postgres using(true) with check(true);
-- Only the trusted server role can cache provider responses. Supabase browser
-- roles receive no table privileges; the HTTP API accepts catalogue keys only.
create policy reference_market_prices_server on tcg.reference_market_prices for all to tcg_api
 using((select tcg.current_user_id()) is not null) with check((select tcg.current_user_id()) is not null);
revoke all on tcg.reference_market_prices from public,anon,authenticated;
grant select,insert,update on tcg.reference_market_prices to tcg_api;
revoke delete on tcg.reference_market_prices from tcg_api;

comment on table tcg.reference_market_prices is 'Display-only public raw-card price references with source/finish/FX provenance; never physical inventory or Store Price authority.';
commit;
