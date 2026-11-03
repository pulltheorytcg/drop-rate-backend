begin;

-- Only approved version pointers live here. Source records, manifests and the
-- rebuildable search index are not copied into PostgreSQL.
create table tcg_private.r2_first_catalogue_publications (
    provider text not null check(provider ~ '^[a-z0-9][a-z0-9_.-]{0,63}$'),
    system_code text not null references tcg.collectible_systems(code),
    language text not null check(length(language) between 1 and 32),
    manifest_sha256 text not null check(manifest_sha256 ~ '^[a-f0-9]{64}$'),
    source_revision text not null check(length(source_revision) between 1 and 256),
    permission_ref text not null check(length(permission_ref) between 1 and 512),
    source_url text not null check(source_url like 'https://%' and length(source_url)<=2048),
    record_count integer not null check(record_count between 1 and 250000),
    released_record_count integer not null check(released_record_count between 0 and record_count),
    raw_bytes integer not null check(raw_bytes between 1 and 128000000),
    set_count integer not null check(set_count between 0 and 250000),
    generation bigint not null check(generation>0),
    active boolean not null default true,
    published_at timestamptz not null default now(),
    published_by uuid not null references auth.users(id),
    primary key(provider,system_code,language)
);

create table tcg_private.r2_first_catalogue_events (
    id uuid primary key default gen_random_uuid(),
    provider text not null,
    system_code text not null,
    language text not null,
    old_manifest_sha256 text,
    new_manifest_sha256 text not null,
    generation bigint not null,
    active boolean not null,
    actor_user_id uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    unique(provider,system_code,language,generation)
);

-- An exact provider identity is linked only when a person selects that item.
-- The pinned source digest is evidence, NOT approval of the physical printing.
create table tcg_private.r2_first_catalogue_links (
    reference_key text primary key check(reference_key ~ '^x:[a-f0-9]{64}$'),
    catalogue_id uuid not null unique references tcg.catalogue_products(id),
    provider text not null,
    system_code text not null,
    language text not null,
    provider_id text not null check(length(provider_id) between 1 and 256),
    source_manifest_sha256 text not null check(source_manifest_sha256 ~ '^[a-f0-9]{64}$'),
    created_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    unique(provider,system_code,language,provider_id),
    check(reference_key='x:' || encode(sha256(convert_to(
        array_to_json(array[provider,system_code,language,provider_id])::text,'UTF8')),'hex')),
    foreign key(provider,system_code,language)
        references tcg_private.r2_first_catalogue_publications(provider,system_code,language)
);

create index r2_first_publications_system_idx
    on tcg_private.r2_first_catalogue_publications(system_code);
create index r2_first_publications_actor_idx
    on tcg_private.r2_first_catalogue_publications(published_by);
create index r2_first_events_actor_idx on tcg_private.r2_first_catalogue_events(actor_user_id);
create index r2_first_links_actor_idx on tcg_private.r2_first_catalogue_links(created_by);

alter table tcg_private.r2_first_catalogue_publications enable row level security;
alter table tcg_private.r2_first_catalogue_publications force row level security;
alter table tcg_private.r2_first_catalogue_events enable row level security;
alter table tcg_private.r2_first_catalogue_events force row level security;
alter table tcg_private.r2_first_catalogue_links enable row level security;
alter table tcg_private.r2_first_catalogue_links force row level security;
revoke all on tcg_private.r2_first_catalogue_publications,
    tcg_private.r2_first_catalogue_events,tcg_private.r2_first_catalogue_links
    from public,anon,authenticated,service_role,tcg_api;
grant select,insert,update on tcg_private.r2_first_catalogue_publications to tcg_api;
grant select,insert on tcg_private.r2_first_catalogue_events to tcg_api;
grant select,insert on tcg_private.r2_first_catalogue_links to tcg_api;

create policy r2_first_publication_read on tcg_private.r2_first_catalogue_publications
    for select to tcg_api using((select tcg.current_access_role()) is not null);
create policy r2_first_publication_insert on tcg_private.r2_first_catalogue_publications
    for insert to tcg_api with check((select tcg.is_platform_admin())
        and published_by=(select tcg.current_user_id()));
create policy r2_first_publication_update on tcg_private.r2_first_catalogue_publications
    for update to tcg_api using((select tcg.is_platform_admin()))
    with check((select tcg.is_platform_admin()) and published_by=(select tcg.current_user_id()));
create policy r2_first_event_read on tcg_private.r2_first_catalogue_events
    for select to tcg_api using((select tcg.is_platform_admin()));
create policy r2_first_event_insert on tcg_private.r2_first_catalogue_events
    for insert to tcg_api with check((select tcg.is_platform_admin())
        and actor_user_id=(select tcg.current_user_id()) and pg_trigger_depth()=1);
create policy r2_first_link_read on tcg_private.r2_first_catalogue_links
    for select to tcg_api using((select tcg.current_access_role()) is not null);
create policy r2_first_link_insert on tcg_private.r2_first_catalogue_links
    for insert to tcg_api with check((select tcg.current_access_role()) is not null
        and created_by=(select tcg.current_user_id())
        and exists(select 1 from tcg_private.r2_first_catalogue_publications p
          where p.provider=r2_first_catalogue_links.provider
            and p.system_code=r2_first_catalogue_links.system_code
            and p.language=r2_first_catalogue_links.language and p.active
            and p.manifest_sha256=r2_first_catalogue_links.source_manifest_sha256)
        and exists(select 1 from tcg.catalogue_products c
          where c.id=r2_first_catalogue_links.catalogue_id
            and c.identity_key='r2:v1:' || substring(r2_first_catalogue_links.reference_key from 3)));

-- Invoker security: this cannot bypass the caller's grants or RLS. Every
-- publication change and its audit event commit or roll back together.
create function tcg_private.r2_first_publication_audit() returns trigger
language plpgsql security invoker set search_path=pg_catalog,tcg_private as $$
begin
    if tg_op='INSERT' then
        if new.generation<>1 then raise exception 'Initial generation must be one' using errcode='23514'; end if;
    else
        if row(new.provider,new.system_code,new.language) is distinct from
           row(old.provider,old.system_code,old.language) then
            raise exception 'Publication identity is immutable' using errcode='23514';
        end if;
        if new.generation<>old.generation+1 then
            raise exception 'Publication generation must advance once' using errcode='23514';
        end if;
    end if;
    insert into tcg_private.r2_first_catalogue_events
        (provider,system_code,language,old_manifest_sha256,new_manifest_sha256,generation,active,actor_user_id)
    values(new.provider,new.system_code,new.language,
        case when tg_op='UPDATE' then old.manifest_sha256 else null end,
        new.manifest_sha256,new.generation,new.active,new.published_by);
    return new;
end $$;
revoke all on function tcg_private.r2_first_publication_audit() from public,anon,authenticated,service_role;
grant execute on function tcg_private.r2_first_publication_audit() to tcg_api;
create trigger r2_first_publication_audit before insert or update
    on tcg_private.r2_first_catalogue_publications for each row
    execute function tcg_private.r2_first_publication_audit();

alter table tcg.catalogue_saved_references
    drop constraint catalogue_saved_references_reference_key_check;
alter table tcg.catalogue_saved_references
    add constraint catalogue_saved_references_reference_key_check check(
        reference_key ~ '^([rs]:[a-f0-9]{32}|x:[a-f0-9]{64}|c:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$');

comment on table tcg_private.r2_first_catalogue_publications is
    'Approved immutable R2 metadata generations. No physical ownership, artwork permission or market-price approval.';
comment on table tcg_private.r2_first_catalogue_links is
    'On-demand exact reference-to-canonical identity links; immutable evidence, never inferred physical identity approval.';
commit;
