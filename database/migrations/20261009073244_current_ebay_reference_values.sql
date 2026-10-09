begin;

-- Keep the existing authenticated reference-only interface. A historical import
-- must not be returned after its active inventory valuation has been retired.
create or replace function tcg.recognition_catalogue_reference_value(
    p_catalogue_id uuid, p_language text default null
)
returns table(market_value_minor bigint,recommended_retail_minor bigint,
              pricing_updated_at timestamptz,basis_condition text,basis_language text)
language sql stable security definer set search_path=pg_catalog
as $function$
  select i.market_value_minor,i.recommended_retail_minor,i.pricing_updated_at,i.condition,i.language
  from tcg.inventory_items i
  join tcg.pricing_snapshots ps on ps.id=i.latest_pricing_snapshot_id and ps.inventory_id=i.id
  where tcg.current_user_id() is not null
    and i.catalogue_id=p_catalogue_id and ps.catalogue_id=i.catalogue_id and ps.owner_id=i.owner_id
    and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
    and i.grading_company is null and i.grade is null
    and i.market_value_minor is not null and i.market_value_minor=ps.market_value_minor
    and ps.algorithm_version='drop-rate-market-v4'
    and (ps.evidence->>'method'='LIVE_EBAY_MARKET_V1' or ps.sold_observation_count>=5)
    and ps.evidence->'sources' @> '[{"source":"EBAY"}]'::jsonb
    and i.pricing_updated_at>=now()-interval '7 days'
    and (nullif(btrim(coalesce(p_language,'')),'') is null
      or lower(coalesce(i.language,''))=lower(btrim(p_language)))
  order by case lower(coalesce(i.condition,'')) when 'near mint' then 0 when 'nm' then 0 else 1 end,
    i.pricing_updated_at desc,ps.id limit 1
$function$;
revoke all on function tcg.recognition_catalogue_reference_value(uuid,text) from public,anon,authenticated,service_role;
grant execute on function tcg.recognition_catalogue_reference_value(uuid,text) to tcg_api;

commit;
