-- Admit the read-only / opt-in catalogue-only CardTrader expansion guide
-- receipt. Retain every existing job label; never broaden RLS or touch
-- physical inventory, prices, orders, or ownership.
alter table tcg.catalogue_job_runs
 drop constraint if exists catalogue_job_runs_job_check;

alter table tcg.catalogue_job_runs
 add constraint catalogue_job_runs_job_check
 check (job = any(array[
  'REFERENCE_PRICES','SHOPIFY_SYNC','SEALED_REFERENCE_PRICES',
  'CATALOGUE_COVERAGE','CATALOGUE_VALUES','CARDMARKET_VALUES',
  'POKEWALLET_PRICES','POKEWALLET_DBS_PRICES','POKEWALLET_POKEMON_PRICES',
  'ONE_PIECE_OFFICIAL_BASE_GUIDES','CARDTRADER_EXPANSION_GUIDES'
 ]::text[]));
