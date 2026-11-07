begin;

-- Reference-only data remains under the caller's role and existing policies.
-- A bulk reference that changed identity or lost its quote cannot keep pricing
-- physical copies from an old cached snapshot. Older TCGdex guides keep their
-- existing exact-variant contract.
create function tcg.cardmarket_reference_current(p_evidence jsonb)
returns boolean language sql stable security invoker set search_path=pg_catalog as $function$
 select case
 when p_evidence->'quote'->>'source'='TCGDEX_CARDMARKET' then true
 when p_evidence->'quote'->>'source'='CARDMARKET_BULK_SINGLES' then exists(
   select 1 from tcg.reference_cards r
   join tcg.reference_sets rs using(provider,system_code,language,set_id)
   join tcg.reference_market_prices m using(provider,system_code,language,provider_id)
   where r.provider=p_evidence->'reference'->>'provider'
     and r.system_code=p_evidence->'reference'->>'system_code'
     and r.language=p_evidence->'reference'->>'reference_language'
     and r.provider_id=p_evidence->'reference'->>'provider_id'
     and r.set_id=p_evidence->'reference'->>'set_id'
     and (rs.release_date is null or rs.release_date<=current_date)
     and p_evidence->'quote'->'reference_identity'=jsonb_build_object(
       'name',r.name,'set_id',r.set_id,'card_number',r.card_number,'set_name',rs.name)
     and p_evidence->'quote'->'reference_rarity'=coalesce(to_jsonb(r.rarity),'null'::jsonb)
     and m.quotes @> jsonb_build_array(p_evidence->'quote'))
 else false end
$function$;
revoke all on function tcg.cardmarket_reference_current(jsonb) from public,anon,authenticated,service_role;
grant execute on function tcg.cardmarket_reference_current(jsonb) to tcg_api;

create or replace function tcg.catalogue_reference_value_v2(p_catalogue_id uuid,p_language text default null)
returns table(market_value_minor bigint,recommended_retail_minor bigint,pricing_updated_at timestamptz,
 basis_condition text,basis_language text,valuation_source text)
language sql stable security invoker set search_path=pg_catalog as $function$
 select s.market_value_minor,s.recommended_retail_minor,s.evidence_checked_at,
  case when s.evidence->>'method'='CATALOGUE_CARDMARKET_V1' then 'Cardmarket guide · mixed languages and conditions'
       else coalesce(s.basis_condition,case when s.seal_status='SEALED' then 'Sealed' end)||' · '||s.basis_language end,
  s.basis_language,case when s.evidence->>'method'='CATALOGUE_CARDMARKET_V1' then 'CARDMARKET_ESTIMATE' else 'STORED_SNAPSHOT' end
 from tcg.catalogue_market_snapshots s join tcg.catalogue_products p on p.id=s.catalogue_id
 where tcg.current_user_id() is not null and s.catalogue_id=p_catalogue_id
 and s.identity_digest=md5(concat_ws(chr(31),p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language))
 and s.grading_company is null and s.grade is null
 and s.evidence_checked_at between now()-interval '7 days' and now()
 and ((s.evidence->>'method'='CATALOGUE_EBAY_V4' and s.oldest_sale_at>=now()-interval '90 days')
      or (s.evidence->>'method'='CATALOGUE_CARDMARKET_V1'
        and tcg.cardmarket_reference_current(s.evidence)
        and not exists(select 1 from tcg.market_source_mappings m where m.catalogue_id=p.id
          and m.source='CARDMARKET' and m.match_status in ('REVIEW','REJECTED'))
        and not exists(select 1 from tcg.provider_catalogue_mappings m where m.catalogue_id=p.id
          and m.provider_language=s.basis_language
          and m.match_status in ('REVIEW','REJECTED'))))
 and (nullif(btrim(coalesce(p_language,'')),'') is null or lower(s.basis_language)=lower(btrim(p_language)))
 order by (s.evidence->>'method'='CATALOGUE_EBAY_V4') desc,
  case lower(coalesce(s.basis_condition,'')) when 'near mint' then 0 when 'nm' then 0 else 1 end,
  s.evidence_checked_at desc,s.calculated_at desc,s.id limit 1
$function$;
revoke all on function tcg.catalogue_reference_value_v2(uuid,text) from public,anon,authenticated,service_role;
grant execute on function tcg.catalogue_reference_value_v2(uuid,text) to tcg_api;
commit;
