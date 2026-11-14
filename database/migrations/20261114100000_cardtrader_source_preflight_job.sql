-- Independent, auditable provider-source preflights. Do not mix read-only
-- source checks with CARDTRADER_EXPANSION_GUIDES's live pricing cursor.
-- Retain all existing categories; no change to RLS, permissions, prices,
-- ownership, Shopify, audit history or operator bulk-write hold.
alter table tcg.catalogue_job_runs
  drop constraint if exists catalogue_job_runs_job_check;

alter table tcg.catalogue_job_runs
  add constraint catalogue_job_runs_job_check
  check (job = any(array[
    'REFERENCE_PRICES', 'SHOPIFY_SYNC', 'SEALED_REFERENCE_PRICES',
    'CATALOGUE_COVERAGE', 'CATALOGUE_VALUES', 'CARDMARKET_VALUES',
    'POKEWALLET_PRICES', 'POKEWALLET_DBS_PRICES',
    'POKEWALLET_POKEMON_PRICES', 'ONE_PIECE_OFFICIAL_BASE_GUIDES',
    'CARDTRADER_EXPANSION_GUIDES', 'DROP_RATE_DAILY_MODEL',
    'CARDTRADER_SOURCE_PREFLIGHT'
  ]::text[]));
