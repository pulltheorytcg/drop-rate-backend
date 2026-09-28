begin;

-- Restricted owner accounts may run recognition only inside their own active owner
-- membership. Global model/reference maintenance remains platform-admin only.

drop policy if exists api_insert on tcg.recognition_runs;
create policy api_insert on tcg.recognition_runs
    for insert to tcg_api
    with check (
        tcg.current_access_role() in ('PLATFORM_ADMIN','OWNER')
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
        and created_by_user_id=tcg.current_user_id()
    );

drop policy if exists api_update on tcg.recognition_runs;
create policy api_update on tcg.recognition_runs
    for update to tcg_api
    using (
        tcg.current_access_role() in ('PLATFORM_ADMIN','OWNER')
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
    )
    with check (
        tcg.current_access_role() in ('PLATFORM_ADMIN','OWNER')
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
    );

drop policy if exists api_insert on tcg.recognition_candidates;
create policy api_insert on tcg.recognition_candidates
    for insert to tcg_api
    with check (
        tcg.current_access_role() in ('PLATFORM_ADMIN','OWNER')
        and exists (
            select 1
            from tcg.recognition_runs r
            join tcg.owner_memberships m on m.owner_id=r.owner_id
            where r.id=recognition_candidates.run_id
              and m.user_id=tcg.current_user_id()
              and m.active
        )
    );

drop policy if exists api_insert on tcg.recognition_feedback;
create policy api_insert on tcg.recognition_feedback
    for insert to tcg_api
    with check (
        tcg.current_access_role() in ('PLATFORM_ADMIN','OWNER')
        and actor_user_id=tcg.current_user_id()
        and owner_id in (
            select m.owner_id
            from tcg.owner_memberships m
            where m.user_id=tcg.current_user_id()
              and m.active
        )
    );

-- Safe server-side retrieval of global verified reference fingerprints. The caller
-- cannot read ownership, source image bytes, user data or model-management rows.
create or replace function tcg.recognition_reference_hint_rows(
    p_system_code text,
    p_max_rows integer default 10000
)
returns table(
    catalogue_id uuid,
    media_asset_id uuid,
    system_code text,
    source_fingerprints jsonb,
    trust_level text
)
language sql
stable
security definer
set search_path=pg_catalog
as $function$
    select
        rf.catalogue_id,
        rf.media_asset_id,
        rf.system_code,
        rf.source_fingerprints,
        rf.trust_level
    from tcg.recognition_reference_fingerprints rf
    join tcg.media_assets ma on ma.id=rf.media_asset_id
    where rf.fingerprint_version='dhash16-multicrop-rotate-v1'
      and (p_system_code is null or rf.system_code=p_system_code)
      and ma.source_status='ACTIVE'
      and ma.rights_status='VERIFIED'
      and ma.version=rf.media_asset_version
      and ma.public_source_url=rf.source_url
    order by
        case rf.trust_level when 'VERIFIED' then 0 else 1 end,
        rf.updated_at desc,
        rf.id
    limit least(greatest(coalesce(p_max_rows,10000),1),10000)
$function$;

revoke all on function tcg.recognition_reference_hint_rows(text,integer)
from public,anon,authenticated,service_role;
grant execute on function tcg.recognition_reference_hint_rows(text,integer) to tcg_api;

-- Safe global learning retrieval: only human-labelled TRAIN fingerprints and the
-- selected canonical printing are exposed to the recognition engine.
create or replace function tcg.recognition_learning_hint_rows(
    p_system_code text,
    p_max_examples integer default 300
)
returns table(
    selected_catalogue_id uuid,
    source_fingerprints jsonb
)
language sql
stable
security definer
set search_path=pg_catalog
as $function$
    select e.selected_catalogue_id,e.source_fingerprints
    from tcg.recognition_learning_examples e
    where e.system_code=p_system_code
      and e.dataset_split='TRAIN'
      and e.selected_catalogue_id is not null
      and e.label_outcome in ('CONFIRMED_TOP','CORRECTED_TO_CANDIDATE')
      and not exists (
          select 1
          from tcg.recognition_learning_examples newer
          where newer.supersedes_example_id=e.id
      )
    order by e.created_at desc,e.id desc
    limit least(greatest(coalesce(p_max_examples,300),1),1000)
$function$;

revoke all on function tcg.recognition_learning_hint_rows(text,integer)
from public,anon,authenticated,service_role;
grant execute on function tcg.recognition_learning_hint_rows(text,integer) to tcg_api;

create or replace function tcg.recognition_learning_visual_rows(
    p_catalogue_ids uuid[],
    p_max_examples_per_candidate integer default 8
)
returns table(
    selected_catalogue_id uuid,
    source_fingerprints jsonb
)
language sql
stable
security definer
set search_path=pg_catalog
as $function$
    with active as (
        select
            e.id,
            e.selected_catalogue_id,
            e.source_fingerprints,
            e.created_at,
            row_number() over (
                partition by e.selected_catalogue_id
                order by e.created_at desc,e.id desc
            ) as recency_rank
        from tcg.recognition_learning_examples e
        where e.selected_catalogue_id=any(coalesce(p_catalogue_ids,array[]::uuid[]))
          and e.dataset_split='TRAIN'
          and e.label_outcome in ('CONFIRMED_TOP','CORRECTED_TO_CANDIDATE')
          and not exists (
              select 1
              from tcg.recognition_learning_examples newer
              where newer.supersedes_example_id=e.id
          )
    )
    select active.selected_catalogue_id,active.source_fingerprints
    from active
    where active.recency_rank <= least(greatest(coalesce(p_max_examples_per_candidate,8),1),32)
$function$;

revoke all on function tcg.recognition_learning_visual_rows(uuid[],integer)
from public,anon,authenticated,service_role;
grant execute on function tcg.recognition_learning_visual_rows(uuid[],integer) to tcg_api;

commit;
