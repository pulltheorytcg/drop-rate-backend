-- Read-only deterministic diagnostic sample; rerunning uses current freshness.
with coverage as (
 select r.provider,r.provider_id,r.set_id,s.name as set_name,r.name,r.card_number,r.finish,r.rarity,r.source_url,r.evidence,r.system_code,r.language,
   case when (r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language='English' and (r.set_id,s.name) in (('A1','Genetic Apex'),('P-A','Promos-A'),('A1a','Mythical Island'),('A2','Space-Time Smackdown'),('A2a','Triumphant Light'),('A2b','Shining Revelry'),('A3','Celestial Guardians'),('A3a','Extradimensional Crisis'),('A3b','Eevee Grove'),('A4','Wisdom of Sea and Sky'),('A4a','Secluded Springs'),('B1','Mega Rising'),('B1a','Crimson Blaze'),('B2','Fantastical Parade'),('B2a','Paldean Wonders'))) then 'NOT_APPLICABLE_DIGITAL'
        when p.market_value_minor>0 and p.pricing_updated_at>=now()-interval '7 days'
          and p.quotes->0->>'source'='CARDMARKET_BULK_SINGLES' then 'MIXED_LANGUAGE_GUIDE'
        when p.market_value_minor>0 and p.pricing_updated_at>=now()-interval '7 days' then 'REFERENCE_AVAILABLE'
        when b.market_value_minor>0 then 'MIXED_LANGUAGE_GUIDE'
        when p.quotes<>'[]'::jsonb and p.pricing_updated_at>=now()-interval '7 days' then 'US_CONTEXT_ONLY'
        when p.pricing_updated_at<now()-interval '7 days' then 'STALE_EVIDENCE'
        -- These languages/games have no licensed exact GBP source in the
        -- connected daily adapters. A different-language guide is not proof.
        when r.system_code in ('NARUTO_BANDAI_LEGACY','NARUTO_KAYOU')
          or (r.language='Japanese' and r.system_code in
             ('ONE_PIECE_CARD_GAME','DRAGON_BALL_SUPER_FUSION_WORLD'))
          then 'SOURCE_ACCESS_REQUIRED'
        when r.provider='TCGdex' and r.language in ('English','Japanese') and p.checked_at is null then 'AWAITING_DAILY_REFRESH'
        when r.provider='TCGdex' and r.language in ('English','Japanese') then 'EXACT_QUOTE_UNAVAILABLE'
        else 'PROVIDER_MAPPING_REQUIRED' end as status,
   greatest(p.checked_at,b.checked_at) as checked_at,
   (nullif(btrim(r.provider_id),'') is not null and nullif(btrim(r.name),'') is not null
    and nullif(btrim(r.set_id),'') is not null and nullif(btrim(r.card_number),'') is not null
    and nullif(btrim(r.source_url),'') is not null) as reference_complete
 from tcg.reference_cards r left join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_market_prices p
 on (p.provider,p.system_code,p.language,p.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and (coalesce(p.quotes->0->>'match_basis','')<>'CARDTRADER_MASTERS_NUMBER_RARITY_SINGLETON_CARDMARKET_ID'
      or r.rarity is not distinct from p.quotes->0->>'reference_rarity')
 and (coalesce(p.quotes->0->>'source','')<>'CARDMARKET_BULK_SINGLES'
      or p.quotes->0->'reference_identity'=jsonb_build_object(
        'name',r.name,'set_id',r.set_id,'card_number',r.card_number,'set_name',s.name))
 left join tcg.reference_catalogue_prices b
 on (b.provider,b.system_code,b.language,b.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and b.pricing_updated_at>=now()-interval '7 days'
 and b.quotes->0->'reference_identity'=jsonb_build_object(
  'name',r.name,'set_id',r.set_id,'card_number',r.card_number,'set_name',s.name)
), ranked as (select *,row_number() over(partition by system_code,language order by md5(provider||':'||provider_id)) as rn from coverage where status not in ('NOT_APPLICABLE_DIGITAL','REFERENCE_AVAILABLE','MIXED_LANGUAGE_GUIDE')) select provider,provider_id,system_code,language,set_id,set_name,name,card_number,finish,rarity,source_url,evidence,status from ranked where rn<=4 order by system_code,language,rn;
