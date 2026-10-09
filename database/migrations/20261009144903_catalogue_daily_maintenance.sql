begin;

-- Operational receipts contain no credentials or provider response bodies.
create table tcg.catalogue_job_runs (
 id uuid primary key default gen_random_uuid(),
 job text not null check(job in ('REFERENCE_PRICES','SHOPIFY_SYNC')),
 actor_user_id uuid not null,
 started_at timestamptz not null default now(),
 finished_at timestamptz,
 status text not null check(status in ('RUNNING','COMPLETE','INCOMPLETE','FAILED')),
 report jsonb not null default '{}'::jsonb
);
create index catalogue_job_runs_due_idx on tcg.catalogue_job_runs(job,started_at desc);
alter table tcg.catalogue_job_runs enable row level security;
alter table tcg.catalogue_job_runs force row level security;
create policy catalogue_job_runs_admin on tcg.catalogue_job_runs for all to postgres using(true) with check(true);
create policy catalogue_job_runs_api on tcg.catalogue_job_runs for all to tcg_api
 using((select tcg.is_platform_admin()))
 with check((select tcg.is_platform_admin()) and actor_user_id=(select tcg.current_user_id()));
revoke all on tcg.catalogue_job_runs from public,anon,authenticated;
grant select,insert,update on tcg.catalogue_job_runs to tcg_api;

-- Provider packaging references remain separate from approved canonical stock.
create table tcg.reference_sealed_products (
 provider text not null,
 system_code text not null references tcg.collectible_systems(code),
 language text not null,
 provider_id text not null,
 set_id text not null,
 name text not null,
 product_type text not null,
 image_url text,
 source_url text not null check(source_url like 'https://%'),
 evidence jsonb not null default '{}'::jsonb,
 refreshed_at timestamptz not null default now(),
 primary key(provider,system_code,language,provider_id),
 foreign key(provider,system_code,language,set_id) references tcg.reference_sets(provider,system_code,language,set_id)
);
create index reference_sealed_sets_idx on tcg.reference_sealed_products(provider,system_code,language,set_id);
alter table tcg.reference_sealed_products enable row level security;
alter table tcg.reference_sealed_products force row level security;
create policy reference_sealed_admin on tcg.reference_sealed_products for all to postgres using(true) with check(true);
create policy reference_sealed_read on tcg.reference_sealed_products for select to tcg_api using((select tcg.current_user_id()) is not null);
create policy reference_sealed_insert on tcg.reference_sealed_products for insert to tcg_api with check((select tcg.is_platform_admin()));
create policy reference_sealed_update on tcg.reference_sealed_products for update to tcg_api using((select tcg.is_platform_admin())) with check((select tcg.is_platform_admin()));
revoke all on tcg.reference_sealed_products from public,anon,authenticated;
grant select,insert,update on tcg.reference_sealed_products to tcg_api;
commit;
