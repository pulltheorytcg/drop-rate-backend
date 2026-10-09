begin;

-- Apply after the first catalogue valuation pass has been verified.
create or replace function tcg.recognition_catalogue_reference_value(p_catalogue_id uuid,p_language text default null)
returns table(market_value_minor bigint,recommended_retail_minor bigint,pricing_updated_at timestamptz,basis_condition text,basis_language text)
language sql stable security definer set search_path=pg_catalog as $function$
 select s.market_value_minor,s.recommended_retail_minor,s.evidence_checked_at,
        coalesce(s.basis_condition,case when s.seal_status='SEALED' then 'Sealed' end),s.basis_language
 from tcg.catalogue_market_snapshots s join tcg.catalogue_products p on p.id=s.catalogue_id
 where tcg.current_user_id() is not null and s.catalogue_id=p_catalogue_id
   and s.identity_digest=md5(concat_ws(chr(31),p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language))
   and s.grading_company is null and s.grade is null
   and s.evidence_checked_at>=now()-interval '7 days' and s.evidence_checked_at<=now()
   and s.oldest_sale_at>=now()-interval '90 days'
   and (nullif(btrim(coalesce(p_language,'')),'') is null or lower(s.basis_language)=lower(btrim(p_language)))
 order by case lower(coalesce(s.basis_condition,'')) when 'near mint' then 0 when 'nm' then 0 else 1 end,
   s.evidence_checked_at desc,s.calculated_at desc,s.id limit 1
$function$;
revoke all on function tcg.recognition_catalogue_reference_value(uuid,text) from public,anon,authenticated,service_role;
grant execute on function tcg.recognition_catalogue_reference_value(uuid,text) to tcg_api;

commit;
