begin;

-- Historical alignment for production migration 20261001140820.
-- This function was applied during the interrupted recognition repair session.
-- It is human-selected, review-gated reference materialisation; it does not
-- auto-approve identity, publish inventory, or alter recognition evidence.
create or replace function tcg.select_recognition_reference(
    p_run_id uuid,
    p_provider text,
    p_system text,
    p_language text,
    p_provider_id text
)
returns uuid
language plpgsql
security definer
set search_path=pg_catalog
as $function$
declare
 v_user uuid := tcg.current_user_id();
 v_ref record;
 v_id uuid;
 v_key text;
 v_game text;
begin
 if v_user is null or coalesce(tcg.current_access_role(),'') not in ('PLATFORM_ADMIN','OWNER') then
   raise exception 'Owner access required' using errcode='42501';
 end if;
 if not exists (
   select 1 from tcg.recognition_runs r join tcg.owner_memberships m on m.owner_id=r.owner_id
   where r.id=p_run_id and m.user_id=v_user and m.active
     and r.status in ('EXACT_CANDIDATE','NEEDS_REVIEW','NO_MATCH','FAILED')
 ) then
   raise exception 'Completed owner scan required' using errcode='42501';
 end if;
 select c.*,s.name as reference_set_name into v_ref
 from tcg.reference_cards c join tcg.reference_sets s using(provider,system_code,language,set_id)
 where c.provider=p_provider and c.system_code=p_system and c.language=p_language
   and c.provider_id=p_provider_id and btrim(c.card_number)<>''
   and (s.release_date is null or s.release_date<=current_date);
 if not found then
   raise exception 'Reference printing not found' using errcode='P0002';
 end if;
 v_game := case p_system
   when 'POKEMON_TCG' then 'Pokemon' when 'ONE_PIECE_CARD_GAME' then 'One Piece'
   when 'DRAGON_BALL_SUPER_MASTERS' then 'Dragon Ball Super Masters'
   when 'DRAGON_BALL_SUPER_FUSION_WORLD' then 'Dragon Ball Super Fusion World'
   when 'NARUTO_KAYOU' then 'Naruto Kayou' when 'NARUTO_BANDAI_LEGACY' then 'Naruto Bandai Legacy'
   when 'NARUTO_BANDAI' then 'Naruto Bandai' when 'YUGIOH' then 'Yu-Gi-Oh!'
   when 'RIFTBOUND' then 'Riftbound' when 'DISNEY_LORCANA' then 'Disney Lorcana' end;
 if v_game is null then
   raise exception 'Unsupported reference system' using errcode='23514';
 end if;
 select m.catalogue_id into v_id from tcg.provider_catalogue_mappings m
 join tcg.catalogue_products p on p.id=m.catalogue_id
 join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
 where m.source_provider=p_provider and m.system_code=p_system
   and m.provider_entity_type='CARD_PRINTING' and m.provider_id=p_provider_id
   and m.provider_variant_key='' and m.provider_language=p_language and m.match_status='VERIFIED'
   and pr.system_code=p_system and p.language=p_language and p.card_number=v_ref.card_number;
 if v_id is not null then return v_id; end if;
 v_key := 'recognition-provider:v1:' || lower(p_system)||':'||lower(p_provider)||':'||lower(p_provider_id)||':'||lower(p_language);
 insert into tcg.catalogue_products(identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
 values(v_key,'CARD',v_game,v_ref.name,v_ref.reference_set_name,v_ref.card_number,
        p_provider_id,coalesce(nullif(v_ref.rarity,''),'Unknown'),p_language)
 on conflict(identity_key) do nothing;
 select p.id into v_id from tcg.catalogue_products p where p.identity_key=v_key;
 if not exists(select 1 from tcg.catalogue_products p where p.id=v_id and p.game=v_game
    and p.language=p_language and p.card_number=v_ref.card_number) then
   raise exception 'Existing reference identity conflicts' using errcode='23514';
 end if;
 insert into tcg.catalogue_product_profiles(catalogue_id,system_code,collectible_type,identity_status,
    set_code,printing_code,attributes)
 values(v_id,p_system,'CARD','NEEDS_REVIEW',v_ref.set_id,p_provider_id,
    jsonb_build_object('source','HUMAN_SELECTED_REFERENCE','recognition_run_id',p_run_id,
      'selected_by_user_id',v_user,'provider',p_provider,'provider_id',p_provider_id,
      'provider_language',p_language,'reference_evidence',v_ref.evidence,'requires_canonical_review',true))
 on conflict(catalogue_id) do nothing;
 if not exists(select 1 from tcg.catalogue_product_profiles pr where pr.catalogue_id=v_id and pr.system_code=p_system) then
   raise exception 'Existing profile conflicts' using errcode='23514';
 end if;
 return v_id;
end;
$function$;

revoke all on function tcg.select_recognition_reference(uuid,text,text,text,text)
from public,anon,authenticated,service_role;
grant execute on function tcg.select_recognition_reference(uuid,text,text,text,text)
to tcg_api;

commit;
