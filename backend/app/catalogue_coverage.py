"""Catalogue-wide coverage receipts: missing evidence is never a zero price."""
from uuid import uuid4

from .db import user_connection

COVERAGE_SQL = '''with coverage as (
 select 'CARD'::text as kind,r.system_code,r.language,
   case when p.market_value_minor>0 and p.pricing_updated_at>=now()-interval '7 days'
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
 and (coalesce(p.quotes->0->>'source','')<>'CARDMARKET_BULK_SINGLES'
      or p.quotes->0->'reference_identity'=jsonb_build_object(
        'name',r.name,'set_id',r.set_id,'card_number',r.card_number,'set_name',s.name))
 left join tcg.reference_catalogue_prices b
 on (b.provider,b.system_code,b.language,b.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and b.pricing_updated_at>=now()-interval '7 days'
 and b.quotes->0->'reference_identity'=jsonb_build_object(
  'name',r.name,'set_id',r.set_id,'card_number',r.card_number,'set_name',s.name)
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
select kind,system_code,language,status,count(*)::int as products,min(checked_at) as oldest_check,
 count(*) filter(where not reference_complete)::int as incomplete_references
from coverage group by kind,system_code,language,status order by kind,system_code,language,status'''

# Availability is global by source/printing, not by owner or the cards anybody
# happens to have scanned. Do not count USD context, stale prices or unresolved
# mappings as verified GBP market values.
PRICED_REFERENCE_STATUSES = frozenset({"REFERENCE_AVAILABLE", "MIXED_LANGUAGE_GUIDE"})
# Actions describe the needed evidence, not a guarantee that it can be bought
# or that a source permits redistribution in a user-facing marketplace.
UNPRICED_REFERENCE_ACTIONS = {
    "SOURCE_ACCESS_REQUIRED": "Obtain permitted exact-print GBP market data for this game and language.",
    "PROVIDER_FEED_REQUIRED": "Obtain an approved provider feed covering this game and product type.",
    "PROVIDER_MAPPING_REQUIRED": "Resolve an exact provider product/printing mapping; do not infer parallels.",
    "EXACT_QUOTE_UNAVAILABLE": "Collect eligible recent quotes for the exact printing and language.",
    "AWAITING_DAILY_REFRESH": "Run or verify the existing daily reference refresh.",
    "STALE_EVIDENCE": "Refresh expired market evidence without rewriting price history.",
    "US_CONTEXT_ONLY": "Find a supported GBP/UK reference; USD listings alone are not GBP market value.",
}


def coverage_summary(rows):
    """Global, owner-independent evidence coverage and actionable missing reasons.

    All counts refer to global reference identities, never physical inventory
    copies. A reported market guide is not a sold-price/grade-specific valuation.
    """
    groups = {kind: {"total": 0, "priced": 0, "missing": 0} for kind in ("CARD", "SEALED")}
    by_game = {}
    by_status = {}
    for row in rows:
        kind = row["kind"]
        if kind not in groups:
            continue
        count = int(row["products"])
        if count < 0:
            raise ValueError("Invalid catalogue coverage count")
        status = str(row["status"])
        priced = count if status in PRICED_REFERENCE_STATUSES else 0
        bucket = by_game.setdefault(
            (kind, row["system_code"], row["language"]),
            {"total": 0, "priced": 0, "missing": 0, "status_counts": {}},
        )
        for group in (groups[kind], bucket):
            group["total"] += count
            group["priced"] += priced
            group["missing"] += count - priced
        bucket["status_counts"][status] = bucket["status_counts"].get(status, 0) + count
        by_status[status] = by_status.get(status, 0) + count

    missing_reasons = [
        {
            "status": status,
            "count": count,
            "next_action": UNPRICED_REFERENCE_ACTIONS.get(
                status, "Review the existing source/printing evidence before assigning a price."
            ),
            "needs_external_data_access": status in {"SOURCE_ACCESS_REQUIRED", "PROVIDER_FEED_REQUIRED"},
        }
        for status, count in by_status.items()
        if status not in PRICED_REFERENCE_STATUSES and count > 0
    ]
    missing_reasons.sort(key=lambda item: (-item["count"], item["status"]))
    return {
        "by_kind": groups,
        "by_game": [
            {"kind": kind, "system_code": system, "language": language, **stats}
            for (kind, system, language), stats in sorted(by_game.items())
        ],
        "by_status": dict(sorted(by_status.items())),
        "missing_by_reason": missing_reasons,
        "pricing_scope": "GLOBAL_REFERENCE_LIBRARY",
        "valuation_currency": "GBP",
        "note": (
            "Guides are estimates; missing, stale, US-only and unmapped sources "
            "are not current exact GBP market values. Accounts share the same references."
        ),
    }


async def record_coverage(pool,actor):
    from .catalogue_maintenance import receipt
    async with user_connection(pool,actor,str(uuid4())) as connection:
        rows=await connection.fetch(COVERAGE_SQL)
        canonical=await connection.fetchval('select count(*) from tcg.catalogue_products')
    items=[dict(row,oldest_check=row['oldest_check'].isoformat() if row['oldest_check'] else None) for row in rows]
    report={'scope':'ALL_REFERENCE_CARDS_AND_SEALED_PRODUCTS','items':items,
            'total':sum(row['products'] for row in items),'canonical_products':canonical,
            'store_price_updates':0, 'summary': coverage_summary(items)}
    await receipt(pool,actor,'CATALOGUE_COVERAGE','COMPLETE',report)
    return report
