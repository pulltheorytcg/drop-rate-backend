begin;

alter table tcg.import_batches
    drop constraint import_batches_owner_id_source_key,
    drop constraint import_batches_source_check;

alter table tcg.import_batches
    add column filename text,
    add column status text not null default 'COMMITTED'
        check (status in ('PREVIEW', 'COMMITTED', 'CANCELLED')),
    add column warning_count integer not null default 0 check (warning_count >= 0),
    add column error_count integer not null default 0 check (error_count >= 0),
    add column version integer not null default 1 check (version >= 1),
    add column committed_at timestamptz,
    add constraint import_batches_source_check check (
        source in ('COLLECTR_OPENING', 'COLLECTR', 'GENERIC_CSV', 'EBAY_PURCHASE_HISTORY', 'HOLODEX')
    ),
    add constraint import_batches_owner_hash_key unique (owner_id, source_sha256);

update tcg.import_batches
set committed_at = created_at
where status = 'COMMITTED' and committed_at is null;

create table tcg.import_rows (
    id uuid primary key default gen_random_uuid(),
    import_batch_id uuid not null references tcg.import_batches(id) on delete cascade,
    owner_id uuid not null references tcg.owners(id),
    row_number integer not null check (row_number > 0),
    quantity integer not null check (quantity > 0 and quantity <= 500),
    raw_record jsonb not null,
    normalized_record jsonb not null,
    match_status text not null
        check (match_status in ('MATCHED', 'NEW_CATALOGUE', 'AMBIGUOUS', 'INVALID')),
    catalogue_id uuid references tcg.catalogue_products(id),
    issues jsonb not null default '[]'::jsonb
        check (jsonb_typeof(issues) = 'array'),
    created_at timestamptz not null default now(),
    unique (import_batch_id, row_number)
);

create index import_batches_owner_created_idx
    on tcg.import_batches(owner_id, created_at desc);

create index import_rows_batch_idx
    on tcg.import_rows(import_batch_id, row_number);

alter table tcg.import_rows enable row level security;

create policy admin_access on tcg.import_rows
    for all to postgres
    using (true)
    with check (true);

create policy own_records on tcg.import_rows
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

grant select, insert, update on tcg.import_rows to tcg_api;

create trigger import_rows_audit
    after insert or update or delete on tcg.import_rows
    for each row execute function tcg.audit_change();

commit;
