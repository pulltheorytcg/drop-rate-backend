begin;

-- Forward-only hardening for Competitive Intelligence opportunity replay.
-- The base persistence migration is already applied in production. Preserve the
-- original qualification decision separately from later lifecycle state.

alter table tcg.competitive_opportunities
    add column qualification_threshold numeric(6,5) not null default 0.72
        check (qualification_threshold between 0 and 1),
    add column qualification_state text not null default 'WATCH'
        check (qualification_state in ('WATCH','QUALIFIED'));

create or replace function tcg.prevent_competitive_qualification_mutation()
returns trigger
language plpgsql
set search_path=pg_catalog
as $$
begin
    if new.opportunity_key is distinct from old.opportunity_key
       or new.opportunity_type is distinct from old.opportunity_type
       or new.subject is distinct from old.subject
       or new.hypothesis is distinct from old.hypothesis
       or new.qualification_state is distinct from old.qualification_state
       or new.score is distinct from old.score
       or new.qualification_threshold is distinct from old.qualification_threshold
       or new.reasons is distinct from old.reasons
       or new.independent_sources is distinct from old.independent_sources
       or new.independent_origins is distinct from old.independent_origins
       or new.competitor_sources is distinct from old.competitor_sources
       or new.non_competitor_sources is distinct from old.non_competitor_sources
       or new.qualification_version is distinct from old.qualification_version
       or new.created_by_user_id is distinct from old.created_by_user_id
       or new.created_at is distinct from old.created_at
    then
        raise exception 'Competitive intelligence qualification contract is immutable'
            using errcode='55000';
    end if;
    return new;
end;
$$;

revoke all on function tcg.prevent_competitive_qualification_mutation() from public;
revoke all on function tcg.prevent_competitive_qualification_mutation()
    from anon,authenticated,service_role;
grant execute on function tcg.prevent_competitive_qualification_mutation() to tcg_api;

create trigger competitive_opportunities_qualification_immutable
    before update on tcg.competitive_opportunities
    for each row execute function tcg.prevent_competitive_qualification_mutation();

commit;
