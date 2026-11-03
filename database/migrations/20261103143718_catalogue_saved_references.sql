begin;

-- Saved catalogue references belong to a signed-in person. They do not create
-- ownership, physical copies, market values or selling intent.
create table tcg.catalogue_saved_references (
    user_id uuid not null references auth.users(id) on delete cascade,
    reference_key text not null check (
        reference_key ~ '^([rs]:[a-f0-9]{32}|c:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$'
    ),
    created_at timestamptz not null default now(),
    primary key (user_id, reference_key)
);

alter table tcg.catalogue_saved_references enable row level security;
alter table tcg.catalogue_saved_references force row level security;
revoke all on tcg.catalogue_saved_references from public, anon, authenticated, service_role, tcg_api;
grant select, insert, delete on tcg.catalogue_saved_references to tcg_api;

create policy catalogue_saved_read on tcg.catalogue_saved_references
    for select to tcg_api using (user_id = (select tcg.current_user_id()));
create policy catalogue_saved_insert on tcg.catalogue_saved_references
    for insert to tcg_api with check (user_id = (select tcg.current_user_id()));
create policy catalogue_saved_delete on tcg.catalogue_saved_references
    for delete to tcg_api using (user_id = (select tcg.current_user_id()));

-- No UPDATE grant or policy: neither account identity nor a saved key can be
-- reassigned. Existing FastAPI membership checks still run for every request.
comment on table tcg.catalogue_saved_references is
    'Private account bookmarks. No inferred ownership; legacy device saves require explicit user import.';

commit;
