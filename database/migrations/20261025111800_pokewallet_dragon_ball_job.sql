-- Record the free Dragon Ball catalogue-guides job without admitting arbitrary
-- job labels. The canonical prices, source history, inventory and settlements
-- are unaffected. This migration was applied to the live Supabase project
-- on 2026-10-25 after the first dry run exposed the missing CHECK label.
alter table tcg.catalogue_job_runs
 drop constraint if exists catalogue_job_runs_job_check;

alter table tcg.catalogue_job_runs
 add constraint catalogue_job_runs_job_check
 check (job = any(array[
  'REFERENCE_PRICES','SHOPIFY_SYNC','SEALED_REFERENCE_PRICES',
  'CATALOGUE_COVERAGE','CATALOGUE_VALUES','CARDMARKET_VALUES',
  'POKEWALLET_PRICES','POKEWALLET_DBS_PRICES'
]::text[]));
