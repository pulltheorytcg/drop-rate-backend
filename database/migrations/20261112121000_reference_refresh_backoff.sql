begin;
set local lock_timeout='2s';
set local statement_timeout='30s';
-- Retry scheduling must never renew an existing evidence expiry/date.
alter table tcg.reference_market_prices add column retry_after timestamptz;
comment on column tcg.reference_market_prices.retry_after is 'Provider retry scheduling only; does not extend evidence expiry, observed_at, checked_at or pricing_updated_at.';
commit;
