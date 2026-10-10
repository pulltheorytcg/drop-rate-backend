begin;

-- Independent source cache: a TCGdex miss/outage cannot erase a direct guide.
create table tcg.reference_catalogue_prices (
 provider text not null,system_code text not null,language text not null,provider_id text not null,
 quotes jsonb not null default '[]'::jsonb check(jsonb_typeof(quotes)='array' and jsonb_array_length(quotes)<=40),
 market_value_minor bigint check(market_value_minor>0),market_value_high_minor bigint,
 pricing_updated_at timestamptz,checked_at timestamptz not null,expires_at timestamptz not null,
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,provider_id)
  references tcg.reference_cards(provider,system_code,language,provider_id),
 check(expires_at>checked_at),
 check((market_value_minor is null and market_value_high_minor is null and pricing_updated_at is null and quotes='[]'::jsonb)
   or (market_value_minor is not null and market_value_high_minor is not null and market_value_high_minor>=market_value_minor
       and pricing_updated_at is not null and jsonb_array_length(quotes)>0))
);
alter table tcg.reference_catalogue_prices enable row level security;
alter table tcg.reference_catalogue_prices force row level security;
create policy catalogue_guides_admin on tcg.reference_catalogue_prices for all to postgres using(true) with check(true);
create policy catalogue_guides_read on tcg.reference_catalogue_prices for select to tcg_api
 using((select tcg.current_user_id()) is not null);
create policy catalogue_guides_write on tcg.reference_catalogue_prices for all to tcg_api
 using((select tcg.is_platform_admin())) with check((select tcg.is_platform_admin()));
revoke all on tcg.reference_catalogue_prices from public,anon,authenticated,tcg_api;
grant select,insert,update on tcg.reference_catalogue_prices to tcg_api;
create trigger catalogue_guide_history after insert or update on tcg.reference_catalogue_prices
 for each row execute function tcg.record_reference_market_history('CARD');
comment on table tcg.reference_catalogue_prices is 'Inventory-independent, mixed-language catalogue guides with immutable provenance. Never physical valuation, identity approval or Store Price authority.';

commit;
