"""Read-only, owner-independent market evidence for inventory presentation.

Admission, selling prices, financial snapshots and pricing policy never call this
module. Callers authorize physical rows first. No provider lookup or write occurs
while rendering inventory; catalogue history and its evidence timestamps remain
unchanged. Missing evidence is not an account-specific zero or a promised job.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from .language import clean_language
from .pricing_rules import MIN_STORE_PRICE_MINOR

SOLD = "CATALOGUE_EBAY_V4"
GUIDE = "CATALOGUE_CARDMARKET_V1"
MAX_AGE = timedelta(days=7)
SALE_AGE = timedelta(days=90)

# DISTINCT ON bounds the returned history to one result per physical basis and
# method. A new calculation cannot revive old evidence or a changed identity.
REFERENCE_VALUES_SQL = """
select distinct on(s.catalogue_id,s.basis_condition,s.basis_language,s.grading_company,s.grade,s.seal_status,s.evidence->>'method')
 s.id as snapshot_id,s.catalogue_id,s.basis_condition,s.basis_language,
 s.grading_company,s.grade,s.seal_status,s.market_value_minor,s.recommended_retail_minor,s.confidence,
 s.evidence_checked_at,s.oldest_sale_at,s.calculated_at,s.algorithm_version,
 s.evidence->>'method' as method,s.evidence->>'limitation' as limitation,
 s.evidence->>'input_sale_count' as input_sale_count,
 case when s.evidence->>'method'='CATALOGUE_CARDMARKET_V1'
      then tcg.cardmarket_reference_current(s.evidence) else true end as reference_current
from tcg.catalogue_market_snapshots s
join tcg.catalogue_products p on p.id=s.catalogue_id
where s.catalogue_id=any($1::uuid[])
 and s.identity_digest=md5(concat_ws(chr(31),p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language))
 and s.evidence->>'method' in ('CATALOGUE_EBAY_V4','CATALOGUE_CARDMARKET_V1')
 and s.evidence_checked_at<=$2 and s.calculated_at<=$2
 and not exists(select 1 from tcg.market_source_mappings m
   where m.catalogue_id=p.id and m.source=case when s.evidence->>'method'='CATALOGUE_EBAY_V4' then 'EBAY' else 'CARDMARKET' end
   and m.match_status in ('REVIEW','REJECTED'))
 and (s.evidence->>'method'<>'CATALOGUE_CARDMARKET_V1' or not exists(
   select 1 from tcg.provider_catalogue_mappings m where m.catalogue_id=p.id
   and m.provider_language=s.basis_language and m.match_status in ('REVIEW','REJECTED')))
order by s.catalogue_id,s.basis_condition,s.basis_language,s.grading_company,s.grade,s.seal_status,s.evidence->>'method',
 s.evidence_checked_at desc,s.calculated_at desc,s.id
"""


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _condition(value: Any) -> str:
    value = _text(value)
    return "near mint" if value == "nm" else value


def _time(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value if isinstance(value, datetime) and value.tzinfo is not None else None


def resolve_reference_value(item: dict, snapshots: list[dict], *, now: datetime) -> dict:
    """Select a reference, not a seller's price or another owner's valuation."""
    result = {"version": "SHARED_CATALOGUE_V1", "status": "UNAVAILABLE", "currency": "GBP",
              "market_value_minor": None, "recommended_retail_minor": None, "last_known_minor": None, "snapshot_id": None,
              "checked_at": None, "method": None, "basis": None,
              "reason": "No suitable shared market evidence for this exact version."}
    language = clean_language(item.get("language")) or clean_language(item.get("catalogue_language"))
    catalogue_language = clean_language(item.get("catalogue_language"))
    if not language or (catalogue_language and catalogue_language != language):
        result.update(status="NEEDS_DETAILS", reason="Confirm the printing and language to select its reference value.")
        return result
    company, grade = _text(item.get("grading_company")), _text(item.get("grade"))
    condition, seal = _condition(item.get("condition")), _text(item.get("seal_status"))
    kind = item.get("product_type")
    if (bool(company) != bool(grade) or (company and (condition or seal))
            or (kind == "CARD" and seal) or (kind != "CARD" and (company or condition))):
        result.update(status="NEEDS_DETAILS", reason="Check the raw, graded or sealed details for this copy.")
        return result
    if kind not in {"CARD", "SEALED", "COLLECTION"}:
        return result
    candidates = []
    for row in snapshots:
        if str(row.get("catalogue_id")) != str(item.get("catalogue_id")):
            continue
        if clean_language(row.get("basis_language")) != language:
            continue
        if row.get("algorithm_version") != "drop-rate-market-v4" or not row.get("reference_current"):
            continue
        method = row.get("method")
        if method == SOLD:
            if (str(row.get("input_sale_count")) != "5"
                    or (company, grade, seal) != (_text(row.get("grading_company")), _text(row.get("grade")), _text(row.get("seal_status")))
                    or condition != _condition(row.get("basis_condition"))
                    or (kind == "CARD" and not company and not condition)
                    or (kind != "CARD" and not seal)):
                continue
        elif method == GUIDE:
            # A guide remains explicitly an estimate, not an exact NM quote.
            # Unknown raw condition may see this labelled reference; worn raw,
            # slabs and sealed never inherit an ungraded guide.
            if (kind != "CARD" or company or grade or seal or condition not in {"", "near mint"}
                    or row.get("grading_company") or row.get("grade") or row.get("seal_status")):
                continue
        else:
            continue
        value, checked, calculated = row.get("market_value_minor"), _time(row.get("evidence_checked_at")), _time(row.get("calculated_at"))
        oldest = _time(row.get("oldest_sale_at"))
        if (type(value) is not int or value <= 0 or checked is None or calculated is None
                or checked > now or calculated > now):
            continue
        fresh = checked >= now - MAX_AGE
        if method == SOLD:
            if oldest is None or oldest > checked:
                continue
            fresh = fresh and oldest >= now - SALE_AGE
        candidates.append((fresh, method == SOLD, checked, calculated, str(row.get("snapshot_id")), row))
    if not candidates:
        if kind == "CARD" and not company and not condition:
            result.update(status="NEEDS_DETAILS", reason="Condition is not recorded; no suitable general reference guide is available.")
        return result
    fresh, _, checked, _, _, selected = max(candidates, key=lambda candidate: candidate[:5])
    estimate = selected["method"] == GUIDE
    basis = f"{language} · " + (f"{item.get('grading_company')} {item.get('grade')}" if company else item.get("condition") or item.get("seal_status") or "Raw reference")
    result.update(snapshot_id=str(selected["snapshot_id"]), checked_at=checked, method=selected["method"], basis=basis)
    if not fresh:
        result.update(status="STALE", last_known_minor=selected["market_value_minor"], reason="Last recorded evidence is stale; no current reference value is available.")
    else:
        # Reuse the algorithm output from this SAME eligible snapshot. Never
        # infer it from an asking price, stale per-copy cache or another basis.
        recommended = selected.get("recommended_retail_minor")
        if type(recommended) is int and recommended >= MIN_STORE_PRICE_MINOR:
            result["recommended_retail_minor"] = recommended
        result.update(status="REFERENCE_ESTIMATE" if estimate else "AVAILABLE", market_value_minor=selected["market_value_minor"],
                      reason=selected.get("limitation") or ("Guide across conditions/languages, not an exact-copy valuation." if estimate else "Shared exact-profile UK sold evidence."))
    return result


async def add_shared_reference_values(connection, items: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Enrich authorized response dictionaries only; never persist into inventory."""
    now = now or datetime.now(timezone.utc)
    catalogue_ids = list(dict.fromkeys(UUID(str(item["catalogue_id"])) for item in items if item.get("catalogue_id")))
    by_catalogue: dict[str, list[dict]] = defaultdict(list)
    for start in range(0, len(catalogue_ids), 100):
        for row in await connection.fetch(REFERENCE_VALUES_SQL, catalogue_ids[start:start+100], now):
            by_catalogue[str(row["catalogue_id"])].append(dict(row))
    for item in items:
        reference = resolve_reference_value(item, by_catalogue[str(item.get("catalogue_id"))], now=now)
        item["reference_value"] = reference
        # Compatibility fields belong to the response, NOT a financial write.
        item["market_value_minor"] = reference["market_value_minor"]
        item["recommended_retail_minor"] = reference["recommended_retail_minor"]
        item["pricing_updated_at"] = reference["checked_at"]
        item["pricing_method"] = "CARDMARKET_GUIDE_V1" if reference["method"] == GUIDE else "LIVE_EBAY_MARKET_V1" if reference["method"] == SOLD else None
        item["pricing_limitation"] = reference["reason"]
        item.pop("catalogue_reference", None)
        # An unfinished raw copy may display the shared NM comparison without
        # asserting its condition or adding that amount to portfolio totals.
        if (reference['status'] == 'NEEDS_DETAILS' and item.get('product_type') == 'CARD'
                and not any(item.get(k) for k in ('condition', 'grading_company', 'grade', 'seal_status'))):
            comparison = resolve_reference_value(dict(item, condition='Near Mint'),
                by_catalogue[str(item.get('catalogue_id'))], now=now)
            if comparison['status'] in {'AVAILABLE', 'STALE'}:
                item['catalogue_reference'] = dict(comparison, status='CONDITION_REFERENCE',
                    label='Near-mint reference', physical_valuation_eligible=False,
                    recommended_retail_minor=None,
                    reason='Shared near-mint reference. Record this copy’s condition before valuing it.')
    from .inventory_catalogue_reference import add_catalogue_references
    await add_catalogue_references(connection, items, now=now)
    return items


async def reference_portfolio(connection, owner_ids, *, statuses=("DRAFT", "INSPECTION", "APPROVED", "RESERVED")):
    """Current reference totals use the same values as list/detail views.

    The caller supplies its authenticated owner or the verified founder view's
    authorized owners. Each physical record is counted once; this does NOT
    reconcile known duplicate inventory records across two owner accounts.
    """
    ids = [UUID(str(value)) for value in owner_ids]
    if not ids:
        return []
    rows = await connection.fetch("""select i.id,i.owner_id,i.catalogue_id,i.inventory_code,
      i.condition,i.grading_company,i.grade,i.seal_status,i.language,i.status,
      p.language as catalogue_language,p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,
      i.store_price_minor,i.recommended_retail_minor
      from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
      where i.owner_id=any($1::uuid[]) and i.status=any($2::text[]) order by i.id""", ids, list(statuses))
    return await add_shared_reference_values(connection, [dict(row) for row in rows])


def reference_totals(items):
    valued = [item for item in items if item.get('market_value_minor') is not None]
    return {"count": len(items), "valued_count": len(valued), "unvalued_count": len(items)-len(valued),
            "total_minor": sum(item['market_value_minor'] for item in valued) if valued else None,
            "estimate_count": sum(item['reference_value']['status']=='REFERENCE_ESTIMATE' for item in valued)}


def recommended_totals(items):
    """Recommendations and private asking prices are separate, coverage-aware sums.

    Every input is an authorized physical record enriched by the shared resolver.
    Count copies, not catalogue groups; absent evidence is not a zero-price card.
    This function performs no calculation of a new price and no database writes.
    """
    eligible = [item for item in items
                if item.get("reference_value", {}).get("status") in {"AVAILABLE", "REFERENCE_ESTIMATE"}
                and type(item.get("recommended_retail_minor")) is int
                and item["recommended_retail_minor"] >= MIN_STORE_PRICE_MINOR]
    asking = [item["store_price_minor"] for item in items
              if type(item.get("store_price_minor")) is int and item["store_price_minor"] > 0]
    return {
        "active_inventory_count": len(items),
        "active_recommended_count": len(eligible),
        "active_unrecommended_count": len(items) - len(eligible),
        "active_recommended_retail_minor": sum(item["recommended_retail_minor"] for item in eligible) if eligible else None,
        "recommendation_guide_count": sum(item["reference_value"]["status"] == "REFERENCE_ESTIMATE" for item in eligible),
        "recorded_asking_count": len(asking),
        "recorded_asking_value_minor": sum(asking) if asking else None,
    }


def reference_top_groups(items, limit=5):
    grouped = {}
    for item in items:
        if item.get('market_value_minor') is None:
            continue
        key = (str(item['catalogue_id']), _condition(item.get('condition')), clean_language(item.get('language')) or clean_language(item.get('catalogue_language')),
               _text(item.get('grading_company')), _text(item.get('grade')), _text(item.get('seal_status')))
        if key not in grouped:
            grouped[key] = {**item, 'quantity': 0, 'holding_value_minor': 0}
        grouped[key]['quantity'] += 1
        grouped[key]['holding_value_minor'] += item['market_value_minor']
    return sorted(grouped.values(), key=lambda row: (-row['market_value_minor'], -row['holding_value_minor'], str(row['catalogue_id'])))[:limit]
