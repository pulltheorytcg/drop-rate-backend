begin;

-- Public sold-market evidence belongs to an identity, never to its current owner.
create table tcg.catalogue_market_snapshots (
 id uuid primary key default gen_random_uuid(),
 catalogue_id uuid not null references tcg.catalogue_products(id),
 identity_digest text not null,basis_key text not null,
 basis_condition text,basis_language text not null,grading_company text,grade text,seal_status text,
 market_value_minor bigint not null check(market_value_minor>0),
 recommended_retail_minor bigint not null check(recommended_retail_minor>0),
 confidence numeric(5,4) not null check(confidence between 0 and 1),
 algorithm_version text not null check(algorithm_version='drop-rate-market-v4'),
 oldest_sale_at timestamptz not null,evidence_checked_at timestamptz not null,
 calculation_day date not null,calculated_at timestamptz not null default clock_timestamp(),
 evidence_digest text not null,evidence jsonb not null check(evidence->>'input_sale_count'='5'),
 check((grading_company is null)=(grade is null)),
 unique(catalogue_id,identity_digest,basis_key,calculation_day,evidence_digest)
);
create index catalogue_market_current_idx on tcg.catalogue_market_snapshots(catalogue_id,evidence_checked_at desc,calculated_at desc);
alter table tcg.catalogue_market_snapshots enable row level security;
alter table tcg.catalogue_market_snapshots force row level security;
create policy catalogue_market_admin on tcg.catalogue_market_snapshots for all to postgres using(true) with check(true);
create policy catalogue_market_read on tcg.catalogue_market_snapshots for select to tcg_api using((select tcg.current_user_id()) is not null);
create policy catalogue_market_insert on tcg.catalogue_market_snapshots for insert to tcg_api with check((select tcg.is_platform_admin()));
revoke all on tcg.catalogue_market_snapshots from public,anon,authenticated,tcg_api;
grant select,insert on tcg.catalogue_market_snapshots to tcg_api;


alter table tcg.catalogue_job_runs drop constraint catalogue_job_runs_job_check;
alter table tcg.catalogue_job_runs add constraint catalogue_job_runs_job_check
 check(job in ('REFERENCE_PRICES','SHOPIFY_SYNC','SEALED_REFERENCE_PRICES','CATALOGUE_COVERAGE','CATALOGUE_VALUES'));
comment on table tcg.catalogue_market_snapshots is 'Immutable catalogue-wide v4 values independent of inventory; evidence_checked_at is provider ingestion time, never the recalculation clock.';
commit;
