-- Admit one independent, quota-governed free price-guide job. Existing job
-- names and ownership/settlement records remain unchanged.
alter table tcg.catalogue_job_runs
 drop constraint catalogue_job_runs_job_check;

alter table tcg.catalogue_job_runs
 add constraint catalogue_job_runs_job_check
 check (job = any(array[
  'REFERENCE_PRICES','SHOPIFY_SYNC','SEALED_REFERENCE_PRICES',
  'CATALOGUE_COVERAGE','CATALOGUE_VALUES','CARDMARKET_VALUES',
  'POKEWALLET_PRICES'
]::text[]));
