"""Catalogue-wide coverage receipts: missing evidence is never a zero price."""
from uuid import uuid4

from .db import user_connection
from .reference_applicability import DIGITAL_REFERENCE_SQL
from .reference_asking_display import asking_cache_join

COVERAGE_SQL = f'''with coverage as (
 select 'CARD'::text as kind,r.system_code,r.language,
   case when {DIGITAL_REFERENCE_SQL} then 'NOT_APPLICABLE_DIGITAL'
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
   (a.provider_id is not null) as asking_estimate_available,
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
 {asking_cache_join()}
 union all
 select 'SEALED',r.system_code,r.language,
   case when p.market_value_minor>0 and p.pricing_updated_at>=now()-interval '7 days' then 'MIXED_LANGUAGE_GUIDE'
        when p.pricing_updated_at<now()-interval '7 days' then 'STALE_EVIDENCE'
        when r.system_code not in ('POKEMON_TCG','ONE_PIECE_CARD_GAME',
             'DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD') then 'PROVIDER_FEED_REQUIRED'
        when nullif(r.evidence->>'cardmarket_product_id','') is null then 'PROVIDER_MAPPING_REQUIRED'
        when p.checked_at is null then 'AWAITING_DAILY_REFRESH' else 'EXACT_QUOTE_UNAVAILABLE' end,p.checked_at,false,
   (nullif(btrim(r.provider_id),'') is not null and nullif(btrim(r.name),'') is not null
    and nullif(btrim(r.set_id),'') is not null and nullif(btrim(r.source_url),'') is not null)
 from tcg.reference_sealed_products r left join tcg.reference_sealed_market_prices p using(provider,system_code,language,provider_id)
)
select kind,system_code,language,status,count(*)::int as products,min(checked_at) as oldest_check,
 count(*) filter(where asking_estimate_available)::int as asking_estimates,
 count(*) filter(where not reference_complete)::int as incomplete_references
from coverage group by kind,system_code,language,status order by kind,system_code,language,status'''

# Availability is global by source/printing, not by owner or the cards anybody
# happens to have scanned. Do not count USD context, stale prices or unresolved
# mappings as verified GBP market values.
PRICED_REFERENCE_STATUSES = frozenset({"REFERENCE_AVAILABLE", "MIXED_LANGUAGE_GUIDE"})
PHYSICAL_CARD_COVERAGE_TARGET_BPS = 8900  # Current founder goal: 89%, exact integer threshold
# Actions describe the needed evidence, not a guarantee that it can be bought
# or that a source permits redistribution in a user-facing marketplace.
UNPRICED_REFERENCE_ACTIONS = {
    "NOT_APPLICABLE_DIGITAL": "Digital TCG Pocket reference; physical resale pricing does not apply.",
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
    digital_cards = 0
    asking_by_game = {}
    for row in rows:
        kind = row["kind"]
        if kind not in groups:
            continue
        count = int(row["products"])
        if count < 0:
            raise ValueError("Invalid catalogue coverage count")
        status = str(row["status"])
        if kind == "CARD" and status == "NOT_APPLICABLE_DIGITAL":
            digital_cards += count
        priced = count if status in PRICED_REFERENCE_STATUSES else 0
        asking_count = int(row.get("asking_estimates", 0))
        if asking_count < 0 or asking_count > count:
            raise ValueError("Invalid asking-estimate coverage count")
        # Only add a fallback for an otherwise unpriced physical reference.
        # Existing guides, digital records and sealed products never double count.
        if kind == "CARD" and status not in PRICED_REFERENCE_STATUSES and status != "NOT_APPLICABLE_DIGITAL":
            cohort = (row["system_code"], row["language"])
            asking_by_game[cohort] = asking_by_game.get(cohort, 0) + asking_count
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
    physical_total = groups["CARD"]["total"] - digital_cards
    physical_priced = groups["CARD"]["priced"]
    physical_missing = groups["CARD"]["missing"] - digital_cards
    if physical_total < 0 or physical_missing < 0 or physical_priced > physical_total:
        raise ValueError("Invalid physical-card coverage totals")

    # Never round a displayed percentage up to a passing target threshold.
    minimum_priced = (physical_total * PHYSICAL_CARD_COVERAGE_TARGET_BPS + 9999) // 10000
    remaining_to_target = max(0, minimum_priced - physical_priced)
    target_by_game = []
    combined_by_game = []
    for (kind, system, language), stats in sorted(by_game.items()):
        if kind != "CARD":
            continue
        eligible = stats["total"] - stats["status_counts"].get("NOT_APPLICABLE_DIGITAL", 0)
        if eligible <= 0:
            continue
        priced = stats["priced"]
        required = (eligible * PHYSICAL_CARD_COVERAGE_TARGET_BPS + 9999) // 10000
        target_by_game.append({
            "system_code": system, "language": language, "eligible": eligible,
            "priced": priced, "missing": eligible - priced,
            "coverage_percent": round(priced * 100 / eligible, 2),
            "additional_needed": max(0, required - priced),
            "target_met": priced >= required,
        })
        asking = asking_by_game.get((system, language), 0)
        combined_by_game.append({
            "system_code": system, "language": language, "eligible": eligible,
            "supported_reference_values": priced, "asking_price_estimates": asking,
            "covered": priced + asking, "missing": eligible - priced - asking,
            "coverage_percent": round((priced + asking) * 100 / eligible, 2),
            "additional_needed": max(0, required - priced - asking),
            "target_met": priced + asking >= required,
        })
    asking_total = sum(asking_by_game.values())
    combined_covered = physical_priced + asking_total
    return {
        "by_kind": groups,
        # Preserve all-reference totals for comparison with earlier receipts.
        # Digital records are explicitly NOT counted as newly priced cards.
        "physical_cards": {
            "total": groups["CARD"]["total"] - digital_cards,
            "priced": groups["CARD"]["priced"],
            "missing": groups["CARD"]["missing"] - digital_cards,
        },
        "non_physical_cards": digital_cards,
        "asking_price_estimates": {
            "scope": "OTHERWISE_UNPRICED_PHYSICAL_REFERENCE_CARDS",
            "count": asking_total,
            "status": "ASKING_PRICE_ESTIMATE",
            "source": "EBAY_OFFICIAL_BROWSE",
            "physical_valuation_eligible": False,
        },
        "combined_coverage_target": {
            "scope": "GLOBAL_PHYSICAL_REFERENCE_CARDS_WITH_ASKING_ESTIMATES",
            "target_percent": PHYSICAL_CARD_COVERAGE_TARGET_BPS // 100,
            "eligible": physical_total,
            "supported_reference_values": physical_priced,
            "asking_price_estimates": asking_total,
            "covered": combined_covered,
            "missing": physical_total - combined_covered,
            "minimum_covered": minimum_priced,
            "additional_needed": max(0, minimum_priced - combined_covered),
            "coverage_percent": round(combined_covered * 100 / physical_total, 2) if physical_total else 0.0,
            "target_met": physical_total > 0 and combined_covered >= minimum_priced,
            "by_game_language": combined_by_game,
            "disclaimer": (
                "Counts supported dated GBP references plus separately labelled current asking-price estimates. "
                "Asking prices are not completed sales or physical-copy valuations. "
                "Digital Pocket records are excluded; the original reference coverage metric is unchanged."
            ),
        },
        "coverage_target": {
            "scope": "GLOBAL_PHYSICAL_REFERENCE_CARDS",
            "target_percent": PHYSICAL_CARD_COVERAGE_TARGET_BPS // 100,
            "eligible": physical_total,
            "priced": physical_priced,
            "missing": physical_missing,
            "minimum_priced": minimum_priced,
            "additional_needed": remaining_to_target,
            "coverage_percent": round(physical_priced * 100 / physical_total, 2)
                if physical_total else 0.0,
            "target_met": physical_total > 0 and physical_priced >= minimum_priced,
            "priced_statuses": sorted(PRICED_REFERENCE_STATUSES),
            "by_game_language": target_by_game,
            "disclaimer": (
                "This counts supported dated GBP reference values or explicitly labelled guides. "
                "A guide is not an exact UK sold valuation; digital Pocket records are excluded."
            ),
        },
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
        # This private once-daily full-catalogue aggregation can exceed the
        # normal 15-second web/API query timeout on a cold 73k-row scan.
        # SET LOCAL is transaction-scoped (user_connection opens one), so this
        # bounded 45-second budget cannot leak to ordinary user requests.
        await connection.execute("select set_config('statement_timeout','45000',true)")
        rows=await connection.fetch(COVERAGE_SQL,timeout=50)
        canonical=await connection.fetchval('select count(*) from tcg.catalogue_products')
    items=[dict(row,oldest_check=row['oldest_check'].isoformat() if row['oldest_check'] else None) for row in rows]
    report={'scope':'ALL_REFERENCE_CARDS_AND_SEALED_PRODUCTS','items':items,
            'total':sum(row['products'] for row in items),'canonical_products':canonical,
            'store_price_updates':0, 'summary': coverage_summary(items)}
    await receipt(pool,actor,'CATALOGUE_COVERAGE','COMPLETE',report)
    return report
