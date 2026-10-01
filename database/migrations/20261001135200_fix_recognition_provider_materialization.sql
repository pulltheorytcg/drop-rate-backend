begin;

-- Allow an authenticated Drop Rate owner to human-confirm an unmapped provider
-- printing without granting broad INSERT/UPDATE access to canonical tables.
-- The function re-derives every identity field from the persisted recognition
-- run/candidate and the read-only reference library. Browser-supplied catalogue
-- fields are never accepted.
create or replace function tcg.materialize_recognition_provider_candidate(
    p_run_id uuid,
    p_candidate_id uuid,
    p_min_score numeric default 0.82
)
returns table(
    catalogue_id uuid,
    catalogue_created boolean,
    mapping_created boolean,
    replayed boolean
)
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
    v_user_id uuid;
    v_candidate record;
    v_reference record;
    v_existing_mapping uuid;
    v_catalogue_id uuid;
    v_catalogue_created boolean := false;
    v_mapping_created boolean := false;
    v_identity_key text;
    v_game text;
    v_expected_system text;
    v_reference_number text;
    v_signal_number text;
    v_snapshot_number text;
    v_observed_number text;
    v_observed_number_confidence numeric;
    v_set_name text;
    v_variant text;
    v_rarity text;
    v_profile_system text;
begin
    v_user_id := tcg.current_user_id();
    if v_user_id is null then
        raise exception using
            errcode='42501',
            message='Authenticated user context is required';
    end if;

    if tcg.current_access_role() not in ('PLATFORM_ADMIN','OWNER') then
        raise exception using
            errcode='42501',
            message='Active Drop Rate owner access is required';
    end if;

    select
        r.owner_id,
        r.status,
        r.system_code,
        r.ai_observation,
        r.top_catalogue_id,
        c.id as candidate_id,
        c.source_kind,
        c.system_code as candidate_system_code,
        c.catalogue_id as candidate_catalogue_id,
        c.provider,
        c.provider_id,
        c.provider_language,
        c.rank,
        c.score,
        c.hard_rejected,
        c.signals,
        c.candidate_snapshot
    into v_candidate
    from tcg.recognition_runs r
    join tcg.recognition_candidates c on c.run_id=r.id
    where r.id=p_run_id
      and c.id=p_candidate_id
    for update of r,c;

    if not found then
        raise exception using
            errcode='P0002',
            message='Recognition candidate not found';
    end if;

    if not exists (
        select 1
        from tcg.owner_memberships m
        where m.owner_id=v_candidate.owner_id
          and m.user_id=v_user_id
          and m.active
    ) then
        raise exception using
            errcode='42501',
            message='Recognition candidate does not belong to the current owner';
    end if;

    if v_candidate.status not in ('EXACT_CANDIDATE','NEEDS_REVIEW','NO_MATCH') then
        raise exception using
            errcode='23514',
            message='Recognition run is not ready for provider confirmation';
    end if;

    if v_candidate.system_code is null
       or v_candidate.system_code <> v_candidate.candidate_system_code then
        raise exception using
            errcode='23514',
            message='Candidate system conflicts with the recognition run';
    end if;

    if v_candidate.candidate_catalogue_id is not null then
        return query
        select v_candidate.candidate_catalogue_id, false, false, true;
        return;
    end if;

    if v_candidate.source_kind <> 'PROVIDER'
       or v_candidate.hard_rejected
       or nullif(btrim(v_candidate.provider),'') is null
       or nullif(btrim(v_candidate.provider_id),'') is null
       or nullif(btrim(v_candidate.provider_language),'') is null then
        raise exception using
            errcode='23514',
            message='Candidate is not an eligible unmapped provider printing';
    end if;

    if coalesce(v_candidate.score,0) < greatest(coalesce(p_min_score,0.82),0.82) then
        raise exception using
            errcode='23514',
            message='Provider candidate score is below the materialization threshold';
    end if;

    if coalesce(nullif(v_candidate.signals #>> '{card_number,match}','')::numeric,0) < 0.99
       or coalesce(nullif(v_candidate.signals #>> '{card_number,ocr_conflict}','')::boolean,false)
       or coalesce(nullif(v_candidate.signals #>> '{provider,match}','')::numeric,0) < 0.90
       or coalesce(nullif(v_candidate.signals #>> '{language,match}','')::numeric,0) < 0.99 then
        raise exception using
            errcode='23514',
            message='Provider candidate evidence is not exact enough for human materialization';
    end if;

    select
        rc.provider,
        rc.system_code,
        rc.language,
        rc.provider_id,
        rc.set_id,
        rc.name,
        rc.card_number,
        rc.finish,
        rc.rarity,
        rc.image_url,
        rc.source_url,
        rc.evidence,
        rs.name as reference_set_name
    into v_reference
    from tcg.reference_cards rc
    join tcg.reference_sets rs
      on rs.provider=rc.provider
     and rs.system_code=rc.system_code
     and rs.language=rc.language
     and rs.set_id=rc.set_id
    where rc.provider=v_candidate.provider
      and rc.system_code=v_candidate.candidate_system_code
      and rc.language=v_candidate.provider_language
      and rc.provider_id=v_candidate.provider_id;

    if not found then
        raise exception using
            errcode='23514',
            message='Provider candidate is not backed by the persisted reference library';
    end if;

    v_reference_number := btrim(coalesce(v_reference.card_number,''));
    v_signal_number := btrim(coalesce(v_candidate.signals #>> '{card_number,candidate}',''));
    v_snapshot_number := btrim(coalesce(
        v_candidate.candidate_snapshot->>'base_card_id',
        v_candidate.candidate_snapshot->>'card_number',
        ''
    ));

    if v_reference_number='' then
        raise exception using
            errcode='23514',
            message='Persisted provider reference has no card number';
    end if;

    if v_signal_number<>'' and
       regexp_replace(upper(v_reference_number),'[^A-Z0-9]','','g')
       <> regexp_replace(upper(v_signal_number),'[^A-Z0-9]','','g') then
        raise exception using
            errcode='23514',
            message='Reference card number conflicts with recognition evidence';
    end if;

    if v_snapshot_number<>'' and
       regexp_replace(upper(v_reference_number),'[^A-Z0-9]','','g')
       <> regexp_replace(upper(v_snapshot_number),'[^A-Z0-9]','','g') then
        raise exception using
            errcode='23514',
            message='Provider snapshot conflicts with the persisted reference card';
    end if;

    v_game := btrim(coalesce(v_candidate.ai_observation->>'game',''));
    v_expected_system := case v_game
        when 'Pokemon' then 'POKEMON_TCG'
        when 'One Piece' then 'ONE_PIECE_CARD_GAME'
        when 'Dragon Ball Super Masters' then 'DRAGON_BALL_SUPER_MASTERS'
        when 'Dragon Ball Super Fusion World' then 'DRAGON_BALL_SUPER_FUSION_WORLD'
        when 'Naruto Kayou' then 'NARUTO_KAYOU'
        when 'Naruto Bandai Legacy' then 'NARUTO_BANDAI_LEGACY'
        when 'Naruto Bandai' then 'NARUTO_BANDAI'
        when 'Yu-Gi-Oh!' then 'YUGIOH'
        when 'Riftbound' then 'RIFTBOUND'
        when 'Disney Lorcana' then 'DISNEY_LORCANA'
        else null
    end;

    if v_expected_system is null or v_expected_system <> v_candidate.candidate_system_code then
        raise exception using
            errcode='23514',
            message='Observed game conflicts with the provider candidate system';
    end if;

    v_observed_number := btrim(coalesce(v_candidate.ai_observation->>'card_number',''));
    v_observed_number_confidence :=
        coalesce(nullif(v_candidate.ai_observation->>'card_number_confidence','')::numeric,0);

    if v_observed_number<>'' and v_observed_number_confidence>=0.70 and
       regexp_replace(upper(v_observed_number),'[^A-Z0-9]','','g')
       <> regexp_replace(upper(v_reference_number),'[^A-Z0-9]','','g') then
        raise exception using
            errcode='23514',
            message='Observed card number conflicts with the provider reference';
    end if;

    select pcm.catalogue_id
    into v_existing_mapping
    from tcg.provider_catalogue_mappings pcm
    where pcm.source_provider=v_candidate.provider
      and pcm.provider_entity_type='CARD_PRINTING'
      and pcm.provider_id=v_candidate.provider_id
      and pcm.provider_variant_key=''
      and pcm.provider_language=v_candidate.provider_language;

    if v_existing_mapping is not null then
        if not exists (
            select 1
            from tcg.catalogue_products p
            join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
            where p.id=v_existing_mapping
              and pr.system_code=v_candidate.candidate_system_code
              and regexp_replace(upper(coalesce(p.card_number,'')),'[^A-Z0-9]','','g')
                  = regexp_replace(upper(v_reference_number),'[^A-Z0-9]','','g')
              and lower(coalesce(p.language,''))=lower(v_candidate.provider_language)
        ) then
            raise exception using
                errcode='23514',
                message='Existing provider mapping conflicts with the current reference identity';
        end if;

        update tcg.recognition_candidates
        set catalogue_id=v_existing_mapping
        where id=p_candidate_id and run_id=p_run_id;

        if coalesce(v_candidate.rank,0)=1 and v_candidate.top_catalogue_id is null then
            update tcg.recognition_runs
            set top_catalogue_id=v_existing_mapping,
                updated_at=clock_timestamp(),
                version=version+1
            where id=p_run_id and owner_id=v_candidate.owner_id;
        end if;

        return query select v_existing_mapping, false, false, true;
        return;
    end if;

    v_identity_key :=
        'recognition-provider:v1:' ||
        lower(v_candidate.candidate_system_code) || ':' ||
        lower(v_candidate.provider) || ':' ||
        lower(v_candidate.provider_id) || ':' ||
        lower(v_candidate.provider_language);

    v_set_name := coalesce(
        nullif(btrim(v_candidate.candidate_snapshot->>'set_name'),''),
        nullif(btrim(v_reference.reference_set_name),''),
        'Reference set ' || v_reference.set_id
    );

    v_variant := coalesce(
        nullif(btrim(v_candidate.candidate_snapshot->>'art_treatment'),''),
        case
            when lower(v_candidate.provider_id) ~ '_p[0-9]+$' then 'Parallel'
            when lower(v_candidate.provider_id) ~ '_r[0-9]+$' then 'Reprint'
            else 'Base'
        end
    );

    v_rarity := coalesce(
        nullif(btrim(v_reference.rarity),''),
        nullif(btrim(v_candidate.candidate_snapshot->>'rarity'),''),
        'Unknown'
    );
    v_rarity := case lower(v_rarity)
        when 'superrare' then 'SR'
        when 'super rare' then 'SR'
        when 'secretrare' then 'SEC'
        when 'secret rare' then 'SEC'
        when 'rare' then 'R'
        when 'uncommon' then 'UC'
        when 'common' then 'C'
        when 'leader' then 'L'
        when 'promo' then 'P'
        else left(v_rarity,120)
    end;

    insert into tcg.catalogue_products(
        identity_key,product_type,game,name,set_name,
        card_number,variant,rarity,language
    )
    values(
        v_identity_key,'CARD',v_game,v_reference.name,v_set_name,
        v_reference_number,v_variant,v_rarity,v_candidate.provider_language
    )
    on conflict(identity_key) do nothing
    returning id into v_catalogue_id;

    if v_catalogue_id is not null then
        v_catalogue_created := true;
    else
        select p.id into v_catalogue_id
        from tcg.catalogue_products p
        where p.identity_key=v_identity_key;
    end if;

    if v_catalogue_id is null then
        raise exception using
            errcode='23514',
            message='Provider-backed catalogue identity could not be created';
    end if;

    insert into tcg.catalogue_product_profiles(
        catalogue_id,system_code,collectible_type,identity_status,
        set_code,printing_code,attributes
    )
    values(
        v_catalogue_id,
        v_candidate.candidate_system_code,
        'CARD',
        'NEEDS_REVIEW',
        case when position('-' in v_reference_number)>0
             then split_part(v_reference_number,'-',1)
             else null end,
        v_candidate.provider_id,
        jsonb_build_object(
            'source','HUMAN_CONFIRMED_PROVIDER_CANDIDATE',
            'recognition_run_id',p_run_id::text,
            'recognition_candidate_id',p_candidate_id::text,
            'provider',v_candidate.provider,
            'provider_id',v_candidate.provider_id,
            'provider_language',v_candidate.provider_language,
            'reference_set_id',v_reference.set_id,
            'reference_set_name',v_reference.reference_set_name,
            'reference_evidence',coalesce(v_reference.evidence,'{}'::jsonb),
            'requires_canonical_review',true
        )
    )
    on conflict on constraint catalogue_product_profiles_pkey do nothing;

    select pr.system_code into v_profile_system
    from tcg.catalogue_product_profiles pr
    where pr.catalogue_id=v_catalogue_id;

    if v_profile_system is null or v_profile_system<>v_candidate.candidate_system_code then
        raise exception using
            errcode='23514',
            message='Catalogue profile conflicts with the provider candidate system';
    end if;

    insert into tcg.provider_catalogue_mappings(
        catalogue_id,system_code,source_provider,provider_entity_type,
        provider_id,provider_variant_key,provider_language,
        source_reference,match_status,verification_basis,confidence,
        verified_by_user_id,verified_at,metadata
    )
    values(
        v_catalogue_id,
        v_candidate.candidate_system_code,
        v_candidate.provider,
        'CARD_PRINTING',
        v_candidate.provider_id,
        '',
        v_candidate.provider_language,
        v_reference.source_url,
        'VERIFIED',
        'HUMAN',
        v_candidate.score,
        v_user_id,
        clock_timestamp(),
        jsonb_build_object(
            'recognition_run_id',p_run_id::text,
            'recognition_candidate_id',p_candidate_id::text,
            'human_confirmed_from_scanner',true
        )
    )
    on conflict(source_provider,provider_entity_type,provider_id,provider_variant_key,provider_language)
    do nothing
    returning id into v_existing_mapping;

    if v_existing_mapping is not null then
        v_mapping_created := true;
    end if;

    select pcm.catalogue_id into v_existing_mapping
    from tcg.provider_catalogue_mappings pcm
    where pcm.source_provider=v_candidate.provider
      and pcm.provider_entity_type='CARD_PRINTING'
      and pcm.provider_id=v_candidate.provider_id
      and pcm.provider_variant_key=''
      and pcm.provider_language=v_candidate.provider_language;

    if v_existing_mapping is null or v_existing_mapping<>v_catalogue_id then
        raise exception using
            errcode='23514',
            message='Provider printing was mapped concurrently to a different catalogue identity';
    end if;

    update tcg.recognition_candidates
    set catalogue_id=v_catalogue_id
    where id=p_candidate_id and run_id=p_run_id;

    if coalesce(v_candidate.rank,0)=1 and v_candidate.top_catalogue_id is null then
        update tcg.recognition_runs
        set top_catalogue_id=v_catalogue_id,
            updated_at=clock_timestamp(),
            version=version+1
        where id=p_run_id and owner_id=v_candidate.owner_id;
    end if;

    return query
    select v_catalogue_id,v_catalogue_created,v_mapping_created,false;
end
$function$;

revoke all on function tcg.materialize_recognition_provider_candidate(uuid,uuid,numeric)
from public,anon,authenticated,service_role;
grant execute on function tcg.materialize_recognition_provider_candidate(uuid,uuid,numeric)
to tcg_api;

commit;
