-- Immediate owner intake: only processing metadata becomes writable.
-- No inventory/canonical/financial data rewrite and no new public grants.
do $$
begin
    if not exists(select 1 from pg_class where oid='tcg.import_batches'::regclass and relrowsecurity and relforcerowsecurity) then
        raise exception 'Import batch RLS must already be enabled and forced';
    end if;
    if exists(select 1 from pg_roles where rolname='tcg_api' and (rolsuper or rolbypassrls)) then
        raise exception 'Runtime role must remain restricted';
    end if;
    if has_table_privilege('tcg_api','tcg.import_batches','UPDATE') then
        raise exception 'Unexpected broad UPDATE grant; review permissions first';
    end if;
end $$;
alter table tcg.import_batches add column if not exists automatic_intake boolean not null default false;
alter table tcg.import_batches add column if not exists last_auto_apply_version integer check(last_auto_apply_version >= 1);
grant update(version,status,committed_at,automatic_intake,last_auto_apply_version) on tcg.import_batches to tcg_api;
create unique index if not exists import_batches_one_open_automatic_per_owner
    on tcg.import_batches(owner_id) where automatic_intake and status='PREVIEW';
