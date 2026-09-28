begin;

alter table tcg.recognition_feedback
    drop constraint if exists recognition_feedback_outcome_check;
alter table tcg.recognition_feedback
    add constraint recognition_feedback_outcome_check
    check (outcome in (
        'CONFIRMED_TOP',
        'CORRECTED_TO_CANDIDATE',
        'CORRECTED_BY_SEARCH',
        'REJECTED_ALL'
    ));

alter table tcg.recognition_feedback
    drop constraint if exists recognition_feedback_check;
alter table tcg.recognition_feedback
    add constraint recognition_feedback_check
    check (
        (
            outcome in (
                'CONFIRMED_TOP',
                'CORRECTED_TO_CANDIDATE',
                'CORRECTED_BY_SEARCH'
            )
            and selected_catalogue_id is not null
        )
        or
        (
            outcome='REJECTED_ALL'
            and selected_catalogue_id is null
        )
    );

alter table tcg.recognition_learning_examples
    drop constraint if exists recognition_learning_examples_label_outcome_check;
alter table tcg.recognition_learning_examples
    add constraint recognition_learning_examples_label_outcome_check
    check (label_outcome in (
        'CONFIRMED_TOP',
        'CORRECTED_TO_CANDIDATE',
        'CORRECTED_BY_SEARCH',
        'REJECTED_ALL'
    ));

alter table tcg.recognition_learning_examples
    drop constraint if exists recognition_learning_examples_check;
alter table tcg.recognition_learning_examples
    add constraint recognition_learning_examples_check
    check (
        (
            label_outcome in (
                'CONFIRMED_TOP',
                'CORRECTED_TO_CANDIDATE',
                'CORRECTED_BY_SEARCH'
            )
            and selected_catalogue_id is not null
        )
        or
        (
            label_outcome='REJECTED_ALL'
            and selected_catalogue_id is null
        )
    );

create or replace function tcg.validate_recognition_feedback()
returns trigger
language plpgsql
set search_path=pg_catalog
as $function$
declare
    v_run_owner uuid;
    v_top_catalogue uuid;
    v_run_status text;
begin
    select r.owner_id,r.top_catalogue_id,r.status
      into v_run_owner,v_top_catalogue,v_run_status
    from tcg.recognition_runs r
    where r.id=new.run_id;

    if v_run_owner is null then
        raise exception 'Recognition run not found'
            using errcode='23503';
    end if;
    if v_run_owner <> new.owner_id then
        raise exception 'Recognition feedback owner mismatch'
            using errcode='23514';
    end if;
    if v_run_status not in ('EXACT_CANDIDATE','NEEDS_REVIEW','NO_MATCH') then
        raise exception 'Only completed recognition runs can be labelled'
            using errcode='23514';
    end if;

    if new.outcome='CONFIRMED_TOP'
       and new.selected_catalogue_id is distinct from v_top_catalogue then
        raise exception 'Confirmed-top label must select the run top candidate'
            using errcode='23514';
    end if;

    if new.outcome='CORRECTED_TO_CANDIDATE'
       and not exists (
            select 1
            from tcg.recognition_candidates c
            where c.run_id=new.run_id
              and c.catalogue_id=new.selected_catalogue_id
              and not c.hard_rejected
       ) then
        raise exception 'Candidate correction must select a viable recognition candidate'
            using errcode='23514';
    end if;

    if new.outcome='CORRECTED_BY_SEARCH'
       and not exists (
            select 1
            from tcg.catalogue_products p
            join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
            where p.id=new.selected_catalogue_id
              and p.product_type='CARD'
       ) then
        raise exception 'Search correction must select a recognised catalogue card'
            using errcode='23514';
    end if;

    if new.supersedes_feedback_id is not null and not exists (
        select 1
        from tcg.recognition_feedback f
        where f.id=new.supersedes_feedback_id
          and f.run_id=new.run_id
          and f.owner_id=new.owner_id
    ) then
        raise exception 'Superseded feedback must belong to the same recognition run'
            using errcode='23514';
    end if;

    return new;
end;
$function$;

revoke all on function tcg.validate_recognition_feedback() from public;
grant execute on function tcg.validate_recognition_feedback() to tcg_api;

create or replace function tcg.recognition_catalogue_reference_value(
    p_catalogue_id uuid,
    p_language text default null
)
returns table(
    market_value_minor bigint,
    recommended_retail_minor bigint,
    pricing_updated_at timestamptz,
    basis_condition text,
    basis_language text
)
language sql
stable
security definer
set search_path=pg_catalog
as $function$
    select
        ps.market_value_minor,
        ps.recommended_retail_minor,
        ps.calculated_at,
        i.condition,
        i.language
    from tcg.pricing_snapshots ps
    join tcg.inventory_items i on i.id=ps.inventory_id
    where ps.catalogue_id=p_catalogue_id
      and i.grading_company is null
      and i.grade is null
      and ps.market_value_minor is not null
      and (
        nullif(btrim(coalesce(p_language,'')),'') is null
        or lower(coalesce(i.language,''))=lower(btrim(p_language))
      )
    order by
      case lower(coalesce(i.condition,''))
        when 'near mint' then 0
        when 'nm' then 0
        else 1
      end,
      ps.calculated_at desc,
      ps.id
    limit 1
$function$;

revoke all on function tcg.recognition_catalogue_reference_value(uuid,text)
from public,anon,authenticated,service_role;
grant execute on function tcg.recognition_catalogue_reference_value(uuid,text) to tcg_api;

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
      and e.label_outcome in (
        'CONFIRMED_TOP',
        'CORRECTED_TO_CANDIDATE',
        'CORRECTED_BY_SEARCH'
      )
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
          and e.label_outcome in (
            'CONFIRMED_TOP',
            'CORRECTED_TO_CANDIDATE',
            'CORRECTED_BY_SEARCH'
          )
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
