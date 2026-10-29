-- Admit one opt-in, reference-only One Piece guide-recovery receipt. Preserve
-- the existing job allowlist; this does not affect pricing, inventory or RLS.
alter table tcg.catalogue_job_runs
 drop constraint if exists catalogue_job_runs_job_check;

alter table tcg.catalogue_job_runs
 add constraint catalogue_job_runs_job_check
 check (job = any(array[
  'REFERENCE_PRICES','SHOPIFY_SYNC','SEALED_REFERENCE_PRICES',
  'CATALOGUE_COVERAGE','CATALOGUE_VALUES','CARDMARKET_VALUES',
  'POKEWALLET_PRICES','POKEWALLET_DBS_PRICES','POKEWALLET_POKEMON_PRICES',
  'ONE_PIECE_OFFICIAL_BASE_GUIDES'
]::text[]));
