begin;

create table tcg.market_ingestion_runs (
    id uuid primary key default gen_random_uuid(),
    requested_by_owner_id uuid not null references tcg.owners(id),
    source text not null check (source in ('EBAY', 'COLLECTR', 'TCGPLAYER', 'CARDMARKET')),
    trigger_type text not null default 'MANUAL'
        check (trigger_type in ('MANUAL', 'SCHEDULED')),
    status text not null
        check (status in ('SUCCEEDED', 'PARTIAL', 'FAILED', 'BLOCKED')),
    mapping_count integer not null default 0 check (mapping_count >= 0),
    fetched_count integer not null default 0 check (fetched_count >= 0),
    inserted_count integer not null default 0 check (inserted_count >= 0),
    duplicate_count integer not null default 0 check (duplicate_count >= 0),
    failed_mapping_count integer not null default 0 check (failed_mapping_count >= 0),
    errors jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    started_at timestamptz not null,
    completed_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    check (completed_at >= started_at),
    check (inserted_count + duplicate_count <= fetched_count)
);

create index market_ingestion_runs_source_time_idx
    on tcg.market_ingestion_runs(source, completed_at desc);
create index market_ingestion_runs_owner_time_idx
    on tcg.market_ingestion_runs(requested_by_owner_id, completed_at desc);

alter table tcg.market_ingestion_runs enable row level security;

create policy admin_access on tcg.market_ingestion_runs
    for all to postgres using (true) with check (true);
create policy own_read on tcg.market_ingestion_runs
    for select to tcg_api
    using (requested_by_owner_id in (select id from tcg.owners));
create policy own_insert on tcg.market_ingestion_runs
    for insert to tcg_api
    with check (requested_by_owner_id in (select id from tcg.owners));

grant select, insert on tcg.market_ingestion_runs to tcg_api;
revoke update, delete on tcg.market_ingestion_runs from tcg_api;

create trigger market_ingestion_runs_audit
    after insert on tcg.market_ingestion_runs
    for each row execute function tcg.audit_market_change();

commit;
