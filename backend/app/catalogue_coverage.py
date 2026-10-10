"""Catalogue-wide coverage receipts: missing evidence is never a zero price."""
from uuid import uuid4

from .db import user_connection

COVERAGE_SQL = '''with coverage as (
 select 'CARD'::text as kind,r.system_code,r.language,
   case when p.market_value_minor is not null and p.pricing_updated_at>=now()-interval '7 days'
          and p.quotes->0->>'source'='CARDMARKET_BULK_SINGLES' then 'MIXED_LANGUAGE_GUIDE'
        when p.market_value_minor is not null and p.pricing_updated_at>=now()-interval '7 days' then 'REFERENCE_AVAILABLE'
        when b.market_value_minor is not null then 'MIXED_LANGUAGE_GUIDE'
        when p.quotes<>'[]'::jsonb and p.pricing_updated_at>=now()-interval '7 days' then 'US_CONTEXT_ONLY'
        when p.pricing_updated_at<now()-interval '7 days' then 'STALE_EVIDENCE'
        when r.provider='TCGdex' and r.language in ('English','Japanese') and p.checked_at is null then 'AWAITING_DAILY_REFRESH'
        when r.provider='TCGdex' and r.language in ('English','Japanese') then 'EXACT_QUOTE_UNAVAILABLE'
        else 'PROVIDER_MAPPING_REQUIRED' end as status,
   greatest(p.checked_at,b.checked_at) as checked_at,
   (nullif(btrim(r.provider_id),'') is not null and nullif(btrim(r.name),'') is not null
    and nullif(btrim(r.set_id),'') is not null and nullif(btrim(r.card_number),'') is not null
    and nullif(btrim(r.source_url),'') is not null) as reference_complete
 from tcg.reference_cards r left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
 left join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_catalogue_prices b
 on (b.provider,b.system_code,b.language,b.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and b.pricing_updated_at>=now()-interval '7 days'
 and b.quotes->0->'reference_identity'=jsonb_build_object(
  'name',r.name,'set_id',r.set_id,'card_number',r.card_number,'set_name',s.name)
 union all
 select 'SEALED',r.system_code,r.language,
   case when p.market_value_minor is not null and p.pricing_updated_at>=now()-interval '7 days' then 'MIXED_LANGUAGE_GUIDE'
        when p.pricing_updated_at<now()-interval '7 days' then 'STALE_EVIDENCE'
        when r.system_code not in ('POKEMON_TCG','ONE_PIECE_CARD_GAME',
             'DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD') then 'PROVIDER_FEED_REQUIRED'
        when nullif(r.evidence->>'cardmarket_product_id','') is null then 'PROVIDER_MAPPING_REQUIRED'
        when p.checked_at is null then 'AWAITING_DAILY_REFRESH' else 'EXACT_QUOTE_UNAVAILABLE' end,p.checked_at,
   (nullif(btrim(r.provider_id),'') is not null and nullif(btrim(r.name),'') is not null
    and nullif(btrim(r.set_id),'') is not null and nullif(btrim(r.source_url),'') is not null)
 from tcg.reference_sealed_products r left join tcg.reference_sealed_market_prices p using(provider,system_code,language,provider_id)
)
select kind,system_code,language,status,count(*)::int as products,min(checked_at) as oldest_check,
 count(*) filter(where not reference_complete)::int as incomplete_references
from coverage group by kind,system_code,language,status order by kind,system_code,language,status'''


async def record_coverage(pool,actor):
    from .catalogue_maintenance import receipt
    async with user_connection(pool,actor,str(uuid4())) as connection:
        rows=await connection.fetch(COVERAGE_SQL)
        canonical=await connection.fetchval('select count(*) from tcg.catalogue_products')
    items=[dict(row,oldest_check=row['oldest_check'].isoformat() if row['oldest_check'] else None) for row in rows]
    report={'scope':'ALL_REFERENCE_CARDS_AND_SEALED_PRODUCTS','items':items,
            'total':sum(row['products'] for row in items),'canonical_products':canonical,
            'store_price_updates':0}
    await receipt(pool,actor,'CATALOGUE_COVERAGE','COMPLETE',report)
    return report
