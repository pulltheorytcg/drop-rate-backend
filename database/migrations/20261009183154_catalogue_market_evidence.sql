begin;

alter table tcg.reference_market_prices add column refresh_revision integer not null default 1;
-- A US-only reference is useful evidence, but must not manufacture a GBP value.
alter table tcg.reference_market_prices drop constraint reference_market_prices_check1;
alter table tcg.reference_market_prices add constraint reference_market_prices_value_evidence_check check (
 (market_value_minor is null and market_value_high_minor is null and
   ((quotes='[]'::jsonb and pricing_updated_at is null) or
    (quotes<>'[]'::jsonb and pricing_updated_at is not null and
     not jsonb_path_exists(quotes,'$[*] ? (@.source != "TCGDEX_TCGPLAYER")'))))
 or (market_value_minor is not null and market_value_high_minor is not null and market_value_high_minor>=market_value_minor
     and pricing_updated_at is not null and jsonb_array_length(quotes)>0)
);

create table tcg.reference_sealed_market_prices (
 provider text not null,system_code text not null,language text not null,provider_id text not null,
 quotes jsonb not null default '[]'::jsonb check(jsonb_typeof(quotes)='array' and jsonb_array_length(quotes)<=40),
 market_value_minor bigint check(market_value_minor>0),market_value_high_minor bigint,
 pricing_updated_at timestamptz,checked_at timestamptz not null,expires_at timestamptz not null,
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,provider_id)
  references tcg.reference_sealed_products(provider,system_code,language,provider_id),
 check(expires_at>checked_at),
 check((market_value_minor is null and market_value_high_minor is null and pricing_updated_at is null and quotes='[]'::jsonb)
   or (market_value_minor is not null and market_value_high_minor is not null and market_value_high_minor>=market_value_minor
       and pricing_updated_at is not null and jsonb_array_length(quotes)>0))
);
alter table tcg.reference_sealed_market_prices enable row level security;
alter table tcg.reference_sealed_market_prices force row level security;
create policy sealed_market_admin on tcg.reference_sealed_market_prices for all to postgres using(true) with check(true);
create policy sealed_market_read on tcg.reference_sealed_market_prices for select to tcg_api using((select tcg.current_user_id()) is not null);
create policy sealed_market_write on tcg.reference_sealed_market_prices for all to tcg_api
 using((select tcg.is_platform_admin())) with check((select tcg.is_platform_admin()));
revoke all on tcg.reference_sealed_market_prices from public,anon,authenticated;
grant select,insert,update on tcg.reference_sealed_market_prices to tcg_api;

create table tcg.reference_market_history (
 id uuid primary key default gen_random_uuid(),
 reference_kind text not null check(reference_kind in ('CARD','SEALED')),
 provider text not null,system_code text not null,language text not null,provider_id text not null,
 quotes jsonb not null check(jsonb_typeof(quotes)='array'),quote_digest text not null,
 market_value_minor bigint,market_value_high_minor bigint,pricing_updated_at timestamptz,
 recorded_at timestamptz not null default clock_timestamp(),
 unique(reference_kind,provider,system_code,language,provider_id,quote_digest)
);
create index reference_market_history_timeline on tcg.reference_market_history
 (reference_kind,provider,system_code,language,provider_id,recorded_at desc);
alter table tcg.reference_market_history enable row level security;
alter table tcg.reference_market_history force row level security;
create policy reference_history_admin on tcg.reference_market_history for all to postgres using(true) with check(true);
create policy reference_history_read on tcg.reference_market_history for select to tcg_api using((select tcg.current_user_id()) is not null);
revoke all on tcg.reference_market_history from public,anon,authenticated,tcg_api;
grant select on tcg.reference_market_history to tcg_api;

create function tcg.record_reference_market_history() returns trigger
language plpgsql security definer set search_path=pg_catalog as $$
begin
 insert into tcg.reference_market_history(reference_kind,provider,system_code,language,provider_id,
  quotes,quote_digest,market_value_minor,market_value_high_minor,pricing_updated_at)
 values(TG_ARGV[0],new.provider,new.system_code,new.language,new.provider_id,new.quotes,md5(new.quotes::text),
  new.market_value_minor,new.market_value_high_minor,new.pricing_updated_at)
 on conflict(reference_kind,provider,system_code,language,provider_id,quote_digest) do nothing;
 return new;
end;$$;
revoke all on function tcg.record_reference_market_history() from public,anon,authenticated,tcg_api;
create trigger reference_market_history after insert or update on tcg.reference_market_prices
 for each row execute function tcg.record_reference_market_history('CARD');
create trigger sealed_market_history after insert or update on tcg.reference_sealed_market_prices
 for each row execute function tcg.record_reference_market_history('SEALED');
-- Preserve the currently known pre-migration evidence with its original date.
insert into tcg.reference_market_history(reference_kind,provider,system_code,language,provider_id,
 quotes,quote_digest,market_value_minor,market_value_high_minor,pricing_updated_at)
select 'CARD',provider,system_code,language,provider_id,quotes,md5(quotes::text),
 market_value_minor,market_value_high_minor,pricing_updated_at from tcg.reference_market_prices
where quotes<>'[]'::jsonb;

alter table tcg.catalogue_job_runs drop constraint catalogue_job_runs_job_check;
alter table tcg.catalogue_job_runs add constraint catalogue_job_runs_job_check
 check(job in ('REFERENCE_PRICES','SHOPIFY_SYNC','SEALED_REFERENCE_PRICES','CATALOGUE_COVERAGE'));
comment on table tcg.reference_market_history is 'Immutable public reference-price evidence; no owner, inventory or Store Price authority.';
comment on table tcg.reference_sealed_market_prices is 'Exact provider ID joins to mixed-language packaging guides; never a physical-copy valuation.';
commit;
