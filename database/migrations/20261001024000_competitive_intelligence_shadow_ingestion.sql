begin;

-- Signed shadow-ingestion path for approved Competitive Intelligence sources.
-- This function is the only database write primitive exposed to automation for
-- competitor observations. It does not publish, price, purchase or mutate commerce.

alter table tcg.competitive_observations
    add column automation_workflow_key text,
    add column automation_workflow_version text,
    add column automation_execution_id text,
    add constraint competitive_observations_automation_provenance_check
        check (
            (
                actor_type='HUMAN'
                and automation_workflow_key is null
                and automation_workflow_version is null
                and automation_execution_id is null
            )
            or
            (
                actor_type='SYSTEM'
                and automation_workflow_key is not null
                and char_length(automation_workflow_key) between 2 and 120
                and automation_workflow_version is not null
                and char_length(automation_workflow_version) between 1 and 80
                and automation_execution_id is not null
                and char_length(automation_execution_id) between 1 and 255
            )
        );

create index competitive_observations_automation_execution_idx
    on tcg.competitive_observations(
        automation_workflow_key,
        automation_execution_id,
        created_at desc
    )
    where actor_type='SYSTEM';

create or replace function tcg.ingest_competitive_observation_system(
    p_request_id text,
    p_workflow_key text,
    p_workflow_version text,
    p_execution_id text,
    p_source_id uuid,
    p_dedupe_key text,
    p_observation_type text,
    p_subject text,
    p_facts jsonb,
    p_evidence jsonb,
    p_confidence numeric,
    p_relevance numeric,
    p_observed_at timestamptz,
    p_source_published_at timestamptz default null
)
returns table(observation_id uuid, duplicate boolean)
language plpgsql
security definer
set search_path=pg_catalog
as $$
declare
    v_source record;
    v_existing tcg.competitive_observations%rowtype;
    v_workflow_key text := btrim(coalesce(p_workflow_key,''));
    v_workflow_version text := btrim(coalesce(p_workflow_version,''));
    v_execution_id text := btrim(coalesce(p_execution_id,''));
    v_inserted_id uuid;
    v_dedupe_key text := btrim(coalesce(p_dedupe_key,''));
    v_observation_type text := upper(btrim(coalesce(p_observation_type,'')));
    v_subject text := btrim(coalesce(p_subject,''));
    v_confidence numeric(6,5) := round(coalesce(p_confidence,-1),5);
    v_relevance numeric(6,5) := round(coalesce(p_relevance,-1),5);
begin
    if v_workflow_key <> 'competitive-intelligence' then
        raise exception 'Competitive automation workflow key is invalid' using errcode='23514';
    end if;
    if char_length(v_workflow_version) < 1 or char_length(v_workflow_version) > 80 then
        raise exception 'Competitive automation workflow version is invalid' using errcode='23514';
    end if;
    if char_length(v_execution_id) < 1 or char_length(v_execution_id) > 255 then
        raise exception 'Competitive automation execution id is invalid' using errcode='23514';
    end if;
    if p_source_id is null then
        raise exception 'Competitive source is required' using errcode='23514';
    end if;
    if char_length(v_dedupe_key) < 1 or char_length(v_dedupe_key) > 255 then
        raise exception 'Competitive observation dedupe key is invalid' using errcode='23514';
    end if;
    if v_observation_type not in (
        'PRODUCT_LAUNCH','PRICE','PROMOTION','STOCK','MERCHANDISING',
        'CRO','SEO','CONTENT','SOCIAL','CHANNEL','REVIEW','CUSTOMER_PAIN','OTHER'
    ) then
        raise exception 'Competitive observation type is invalid' using errcode='23514';
    end if;
    if char_length(v_subject) < 1 or char_length(v_subject) > 500 then
        raise exception 'Competitive observation subject is invalid' using errcode='23514';
    end if;
    if p_facts is null or jsonb_typeof(p_facts) <> 'object' then
        raise exception 'Competitive observation facts must be an object' using errcode='23514';
    end if;
    if p_evidence is null or jsonb_typeof(p_evidence) <> 'array' then
        raise exception 'Competitive observation evidence must be an array' using errcode='23514';
    end if;
    if v_confidence < 0 or v_confidence > 1
       or v_relevance < 0 or v_relevance > 1 then
        raise exception 'Competitive observation scores are invalid' using errcode='23514';
    end if;
    if p_observed_at is null or p_observed_at > clock_timestamp() + interval '5 minutes' then
        raise exception 'Competitive observation timestamp is invalid' using errcode='23514';
    end if;
    if p_source_published_at is not null
       and p_source_published_at > p_observed_at + interval '5 minutes' then
        raise exception 'Competitive source publication timestamp is invalid' using errcode='23514';
    end if;

    select
        s.id,
        s.competitor_id,
        s.source_url,
        s.rights_status,
        s.collection_method,
        s.terms_review_status,
        s.status as source_status,
        c.status as competitor_status
    into v_source
    from tcg.competitor_sources s
    join tcg.competitors c on c.id=s.competitor_id
    where s.id=p_source_id;

    if not found then
        raise exception 'Competitive source not found' using errcode='23503';
    end if;
    if v_source.competitor_status <> 'APPROVED' then
        raise exception 'Competitive competitor is not approved' using errcode='55000';
    end if;
    if v_source.source_status <> 'ACTIVE' then
        raise exception 'Competitive source is not active' using errcode='55000';
    end if;
    if v_source.collection_method='MANUAL_REVIEW' then
        raise exception 'Manual-review source cannot use automated ingestion' using errcode='55000';
    end if;
    if v_source.terms_review_status <> 'REVIEWED' then
        raise exception 'Competitive source terms are not approved for automation' using errcode='55000';
    end if;

    if nullif(btrim(coalesce(p_request_id,'')),'') is not null then
        perform set_config('tcg.request_id',btrim(p_request_id),true);
    end if;
    perform set_config('tcg.competitive_automation_actor','automation:competitive-intelligence',true);

    select *
    into v_existing
    from tcg.competitive_observations
    where dedupe_key=v_dedupe_key;

    if found then
        if v_existing.source_id = p_source_id
           and v_existing.competitor_id = v_source.competitor_id
           and v_existing.observation_type = v_observation_type
           and v_existing.subject = v_subject
           and v_existing.facts = p_facts
           and v_existing.evidence = p_evidence
           and v_existing.confidence = v_confidence
           and v_existing.relevance = v_relevance
           and v_existing.observed_at = p_observed_at
           and v_existing.source_published_at is not distinct from p_source_published_at
           and v_existing.actor_type = 'SYSTEM'
           and v_existing.created_by_user_id is null
        then
            observation_id := v_existing.id;
            duplicate := true;
            return next;
            return;
        end if;

        raise exception 'Competitive observation dedupe key collision'
            using errcode='23505';
    end if;

    insert into tcg.competitive_observations(
        competitor_id,
        source_id,
        dedupe_key,
        observation_type,
        subject,
        source_url,
        facts,
        evidence,
        confidence,
        relevance,
        rights_status,
        observed_at,
        source_published_at,
        actor_type,
        created_by_user_id,
        automation_workflow_key,
        automation_workflow_version,
        automation_execution_id
    ) values (
        v_source.competitor_id,
        p_source_id,
        v_dedupe_key,
        v_observation_type,
        v_subject,
        v_source.source_url,
        p_facts,
        p_evidence,
        v_confidence,
        v_relevance,
        v_source.rights_status,
        p_observed_at,
        p_source_published_at,
        'SYSTEM',
        null,
        v_workflow_key,
        v_workflow_version,
        v_execution_id
    )
    returning id into v_inserted_id;

    observation_id := v_inserted_id;
    duplicate := false;
    return next;
end;
$$;

revoke all on function tcg.ingest_competitive_observation_system(
    text,text,text,text,uuid,text,text,text,jsonb,jsonb,numeric,numeric,timestamptz,timestamptz
) from public;
revoke all on function tcg.ingest_competitive_observation_system(
    text,text,text,text,uuid,text,text,text,jsonb,jsonb,numeric,numeric,timestamptz,timestamptz
) from anon,authenticated,service_role,tcg_auditor;
grant execute on function tcg.ingest_competitive_observation_system(
    text,text,text,text,uuid,text,text,text,jsonb,jsonb,numeric,numeric,timestamptz,timestamptz
) to tcg_api;

create or replace function tcg.audit_competitive_intelligence_change()
returns trigger
language plpgsql
security definer
set search_path=pg_catalog
as $
declare
    v_old jsonb := case when tg_op='INSERT' then null else to_jsonb(old) end;
    v_new jsonb := case when tg_op='DELETE' then null else to_jsonb(new) end;
    v_row jsonb := coalesce(v_new,v_old);
    v_entity_id uuid := nullif(v_row->>'id','')::uuid;
    v_actor text := coalesce(
        nullif(current_setting('tcg.competitive_automation_actor',true),''),
        nullif(current_setting('tcg.user_id',true),''),
        session_user::text
    );
begin
    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values (
        v_actor,
        nullif(current_setting('tcg.request_id',true),''),
        'COMPETITIVE_INTELLIGENCE_' || tg_op,
        upper(tg_table_name),
        v_entity_id,
        v_old,
        v_new
    );
    return null;
end;
$;

revoke all on function tcg.audit_competitive_intelligence_change() from public;
revoke all on function tcg.audit_competitive_intelligence_change()
    from anon,authenticated,service_role;
grant execute on function tcg.audit_competitive_intelligence_change() to tcg_api;

commit;
