begin;

alter table tcg.import_batches
    add column if not exists filename text,
    add column if not exists adapter text not null default 'LEGACY',
    add column if not exists status text not null default 'COMMITTED'
        check (status in ('PREVIEW', 'COMMITTED', 'CANCELLED')),
    add column if not exists warnings jsonb not null default '[]'::jsonb,
    add column if not exists version integer not null default 1 check (version >= 1),
    add column if not exists committed_at timestamptz;

create table tcg.import_candidates (
    id uuid primary key default gen_random_uuid(),
    batch_id uuid not null references tcg.import_batches(id) on delete cascade,
    owner_id uuid not null references tcg.owners(id),
    source_row integer not null check (source_row > 0),
    quantity integer not null default 1 check (quantity > 0 and quantity <= 1000),
    raw_record jsonb not null,
    normalized_record jsonb not null,
    catalogue_id uuid references tcg.catalogue_products(id),
    status text not null check (status in ('READY', 'REVIEW', 'COMMITTED', 'SKIPPED')),
    issues jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique (batch_id, source_row)
);

create index import_candidates_batch_status_idx
    on tcg.import_candidates(batch_id, status, source_row);
create index import_candidates_owner_created_idx
    on tcg.import_candidates(owner_id, created_at desc);

alter table tcg.import_candidates enable row level security;

create policy admin_access on tcg.import_candidates
    for all to postgres using (true) with check (true);
create policy own_records on tcg.import_candidates
    for all to tcg_api
    using (owner_id in (select id from tcg.owners))
    with check (owner_id in (select id from tcg.owners));

grant select, insert, update on tcg.import_candidates to tcg_api;
revoke delete on tcg.import_candidates from tcg_api;

create function tcg.audit_import_candidate_change()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog
as $$
begin
    insert into tcg.audit_events(
        actor, request_id, action, entity_type, entity_id, old_values, new_values
    ) values (
        coalesce(nullif(current_setting('tcg.user_id', true), ''), session_user::text),
        nullif(current_setting('tcg.request_id', true), ''),
        tg_op,
        tg_table_name,
        case when tg_op = 'DELETE' then old.id else new.id end,
        case when tg_op = 'INSERT' then null else to_jsonb(old) end,
        case when tg_op = 'DELETE' then null else to_jsonb(new) end
    );
    return null;
end;
$$;
revoke all on function tcg.audit_import_candidate_change() from public;

create trigger import_candidates_audit
    after insert or update or delete on tcg.import_candidates
    for each row execute function tcg.audit_import_candidate_change();

commit;
