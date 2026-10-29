-- Read-only full-denominator coverage including valid asking estimates.
-- Verified after PR #781, main e17af29e0aae3c78f9d5bfd9a5ebe0f0c04df3c5.
with coverage as (
 select 'CARD'::text as kind,r.system_code,r.language,
   case when (r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language='English' and (r.set_id,s.name) in (('A1','Genetic Apex'),('P-A','Promos-A'),('A1a','Mythical Island'),('A2','Space-Time Smackdown'),('A2a','Triumphant Light'),('A2b','Shining Revelry'),('A3','Celestial Guardians'),('A3a','Extradimensional Crisis'),('A3b','Eevee Grove'),('A4','Wisdom of Sea and Sky'),('A4a','Secluded Springs'),('B1','Mega Rising'),('B1a','Crimson Blaze'),('B2','Fantastical Parade'),('B2a','Paldean Wonders'))) then 'NOT_APPLICABLE_DIGITAL'
        when p.market_value_minor>0 and p.pricing_updated_at>=now()-interval '7 days'
          and p.quotes->0->>'source'='CARDMARKET_BULK_SINGLES' then 'MIXED_LANGUAGE_GUIDE'
        when p.market_value_minor>0 and p.pricing_updated_at>=now()-interval '7 days' then 'REFERENCE_AVAILABLE'
        when b.market_value_minor>0 then 'MIXED_LANGUAGE_GUIDE'
        when a.provider_id is not null then 'ASKING_ESTIMATE'
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
left join (
 select other.provider,other.system_code,other.language,other.set_id,
   regexp_replace(lower(regexp_replace(regexp_replace(split_part(other.card_number,'/',1),'_p[0-9]+$','','i'),'[^[:alnum:]]','','g')),'^0+([0-9])','\1') as number_alias,count(*)::integer as reference_group_count
 from tcg.reference_cards other join (
   select distinct cached_ref.provider,cached_ref.system_code,cached_ref.language,cached_ref.set_id
   from tcg.reference_cards cached_ref join tcg.reference_asking_prices cached
   using(provider,system_code,language,provider_id)
 ) asking_sets using(provider,system_code,language,set_id)
 group by other.provider,other.system_code,other.language,other.set_id,regexp_replace(lower(regexp_replace(regexp_replace(split_part(other.card_number,'/',1),'_p[0-9]+$','','i'),'[^[:alnum:]]','','g')),'^0+([0-9])','\1')
) asking_groups on (asking_groups.provider,asking_groups.system_code,asking_groups.language,asking_groups.set_id)=
 (r.provider,r.system_code,r.language,r.set_id) and asking_groups.number_alias=regexp_replace(lower(regexp_replace(regexp_replace(split_part(r.card_number,'/',1),'_p[0-9]+$','','i'),'[^[:alnum:]]','','g')),'^0+([0-9])','\1')
left join tcg.reference_asking_prices a
 on (a.provider,a.system_code,a.language,a.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and a.reference_identity=jsonb_build_object('name',r.name,'set_id',r.set_id,
   'card_number',r.card_number,'set_name',s.name,'finish',r.finish,'rarity',r.rarity)
 and a.evidence->'matching_reference_evidence'=jsonb_build_object('provider_variant',r.evidence->'provider_variant','variant_title_terms',r.evidence->'variant_title_terms','set_title_terms',r.evidence->'set_title_terms','set_name',r.evidence->'set_name')
 and a.evidence->'reference_group_count'=to_jsonb(asking_groups.reference_group_count)
 and a.method_version='EBAY_UK_RAW_ASK_V1' and a.currency='GBP'
 and a.evidence->>'source'='EBAY_OFFICIAL_BROWSE'
 and a.evidence->>'shipping_basis'='ITEM_PLUS_SHIPPING'
 and a.evidence->>'shipping_context'='CONFIGURED_SHOP_POSTCODE_BENCHMARK'
 and a.evidence->>'condition'='Near Mint'
 and a.evidence->>'finish' in ('Normal','Holo','Reverse Holo','Foil','Parallel','Alt Art','Manga')
 and a.estimate_minor>0 and a.estimate_high_minor>=a.estimate_minor
 and a.listing_count>=3 and a.seller_count>=3 and a.seller_count<=a.listing_count
 and a.observed_at<=now() and a.observed_at>=now()-interval '3 days'
 and a.expires_at>now() and a.expires_at<=a.observed_at+interval '3 days'
 and not ((r.provider='TCGdex' and r.system_code='POKEMON_TCG'
 and r.language='English' and (r.set_id,s.name) in (('A1','Genetic Apex'),('P-A','Promos-A'),('A1a','Mythical Island'),('A2','Space-Time Smackdown'),('A2a','Triumphant Light'),('A2b','Shining Revelry'),('A3','Celestial Guardians'),('A3a','Extradimensional Crisis'),('A3b','Eevee Grove'),('A4','Wisdom of Sea and Sky'),('A4a','Secluded Springs'),('B1','Mega Rising'),('B1a','Crimson Blaze'),('B2','Fantastical Parade'),('B2a','Paldean Wonders'))))

 union all
 select 'SEALED',r.system_code,r.language,
   case when p.market_value_minor>0 and p.pricing_updated_at>=now()-interval '7 days' then 'MIXED_LANGUAGE_GUIDE'
        when p.pricing_updated_at<now()-interval '7 days' then 'STALE_EVIDENCE'
        when r.system_code not in ('POKEMON_TCG','ONE_PIECE_CARD_GAME',
             'DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD') then 'PROVIDER_FEED_REQUIRED'
        when nullif(r.evidence->>'cardmarket_product_id','') is null then 'PROVIDER_MAPPING_REQUIRED'
        when p.checked_at is null then 'AWAITING_DAILY_REFRESH' else 'EXACT_QUOTE_UNAVAILABLE' end,p.checked_at,
   (nullif(btrim(r.provider_id),'') is not null and nullif(btrim(r.name),'') is not null
    and nullif(btrim(r.set_id),'') is not null and nullif(btrim(r.source_url),'') is not null)
 from tcg.reference_sealed_products r left join tcg.reference_sealed_market_prices p using(provider,system_code,language,provider_id)
)
select count(*) as total,count(*) filter(where status in ('REFERENCE_AVAILABLE','MIXED_LANGUAGE_GUIDE','ASKING_ESTIMATE')) as supported,count(*) filter(where status='ASKING_ESTIMATE') as asking_only from coverage where kind='CARD' and status<>'NOT_APPLICABLE_DIGITAL';
