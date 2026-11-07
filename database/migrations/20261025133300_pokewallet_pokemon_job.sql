-- Allow only the new read-only/dry-run-first Japanese Pokemon price-import job.
-- This label is a receipt type; it does not alter inventory or price tables.
alter table tcg.catalogue_job_runs
 drop constraint if exists catalogue_job_runs_job_check;

alter table tcg.catalogue_job_runs
 add constraint catalogue_job_runs_job_check
 check (job = any(array[
  'REFERENCE_PRICES','SHOPIFY_SYNC','SEALED_REFERENCE_PRICES',
  'CATALOGUE_COVERAGE','CATALOGUE_VALUES','CARDMARKET_VALUES',
  'POKEWALLET_PRICES','POKEWALLET_DBS_PRICES','POKEWALLET_POKEMON_PRICES'
]::text[]));
