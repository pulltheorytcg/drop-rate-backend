-- 10 Nov 2026. PREVIEW ONLY, not a migration, not an activated view or job.
-- Tested as a read-only SELECT on Supabase project ozrxenrdladkooixutmm.
-- Tier 1 = APPROVED or Shopify PUBLISHED physical CARD/SEALED records.
-- Tier 2 = reference_cards excluding exact TCG Pocket digital printings.
-- Tier 3 = active R2-only source publication counts, NOT price/art coverage.
-- CAUTION: database mirror metadata is NOT proof of object existence in Cloudflare R2.
-- CAUTION: fresh price screening is NOT full variant/condition/grade parity.
with
pocket_sets(set_id,set_name) as (values
 ('A1','Genetic Apex'),('P-A','Promos-A'),('A1a','Mythical Island'),
 ('A2','Space-Time Smackdown'),('A2a','Triumphant Light'),('A2b','Shining Revelry'),
 ('A3','Celestial Guardians'),('A3a','Extradimensional Crisis'),
 ('A3b','Eevee Grove'),('A4','Wisdom of Sea and Sky'),('A4a','Secluded Springs'),
 ('B1','Mega Rising'),('B1a','Crimson Blaze'),('B2','Fantastical Parade'),
 ('B2a','Paldean Wonders')),
t1 as (
 select i.id,i.catalogue_id,p.game,p.product_type,i.market_value_minor,
 i.pricing_updated_at,
 exists(select 1 from tcg.media_assets a join tcg.media_object_mirrors mm on mm.media_asset_id=a.id
 where a.catalogue_id=i.catalogue_id and a.approval_status='APPROVED'
 and mm.object_key is not null and mm.size_bytes>0) canonical_mirror_metadata
 from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
 where p.product_type in ('CARD','SEALED')
 and (i.status='APPROVED' or exists(
   select 1 from tcg.shopify_inventory_links l where l.inventory_id=i.id and l.sync_state='PUBLISHED'
 ))
),
t2 as (
 select r.system_code,r.language,r.provider,r.provider_id,r.image_url,
 m.status mirror_status,m.object_key,m.size_bytes,
 exists(select 1 from jsonb_array_elements(coalesce(p.quotes,'[]'::jsonb)) q
   where q->>'physical_valuation_eligible'='true'
   and q->>'reference_language'=r.language
   and (q->>'price_gbp_minor')~'^[0-9]+$'
   and (q->>'price_gbp_minor')::bigint>0
   and (q->>'observed_at')::timestamptz>=now()-interval '14 days') quote_fresh,
 exists(select 1 from jsonb_array_elements(coalesce(p.quotes,'[]'::jsonb)) q
   where q->>'physical_valuation_eligible'='true'
   and q->>'reference_language'=r.language
   and (q->>'price_gbp_minor')~'^[0-9]+$'
   and (q->>'price_gbp_minor')::bigint>0) quote_ever
 from tcg.reference_cards r
 left join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
 left join tcg.reference_image_mirrors m using(provider,system_code,language,provider_id)
 where not (r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language='English'
  and exists(select 1 from pocket_sets x where x.set_id=r.set_id and x.set_name=s.name))
)
select 'TIER_1' as tier,game,count(*)::bigint total,
 count(*) filter(where market_value_minor>0 and pricing_updated_at>=now()-interval '14 days')::bigint price_fresh_screen,
 count(*) filter(where market_value_minor>0 and (pricing_updated_at is null or pricing_updated_at<now()-interval '14 days'))::bigint stale,
 count(*) filter(where market_value_minor is null or market_value_minor<=0)::bigint missing_price_screen,
 count(*) filter(where canonical_mirror_metadata)::bigint image_mirror_db_metadata,
 count(*) filter(where not canonical_mirror_metadata)::bigint missing_image_mirror_db_metadata,
 'NOT_VERIFIED_R2_OR_ALL_VARIANTS'::text proof_level
from t1 group by game
union all
select 'TIER_2',case when system_code='POKEMON_TCG' then 'Pokemon'
 when system_code='ONE_PIECE_CARD_GAME' then 'One Piece'
 when system_code like 'DRAGON_BALL%' then 'Dragon Ball' else 'Naruto' end,
 count(*)::bigint,count(*) filter(where quote_fresh)::bigint,
 count(*) filter(where quote_ever and not quote_fresh)::bigint,
 count(*) filter(where not quote_ever)::bigint,
 count(*) filter(where image_url like 'http%' and mirror_status='VERIFIED'
  and object_key is not null and size_bytes>0)::bigint,
 count(*) filter(where not (image_url like 'http%' and mirror_status='VERIFIED'
  and object_key is not null and size_bytes>0))::bigint,
 'ONE_ELIGIBLE_QUOTE_ONLY_R2_UNVERIFIED'::text
from t2 group by case when system_code='POKEMON_TCG' then 'Pokemon'
 when system_code='ONE_PIECE_CARD_GAME' then 'One Piece'
 when system_code like 'DRAGON_BALL%' then 'Dragon Ball' else 'Naruto' end
union all
select 'TIER_3',case when system_code='MAGIC_THE_GATHERING' then 'Magic'
 when system_code='YUGIOH' then 'Yu-Gi-Oh'
 when system_code='DISNEY_LORCANA' then 'Lorcana' else system_code end,
 sum(record_count)::bigint,null::bigint,null::bigint,null::bigint,
 null::bigint,null::bigint,'UNMEASURED_R2_SOURCE_ONLY'::text
from tcg_private.r2_first_catalogue_publications
where active and system_code in ('MAGIC_THE_GATHERING','YUGIOH','DISNEY_LORCANA')
group by system_code
order by tier,game;
