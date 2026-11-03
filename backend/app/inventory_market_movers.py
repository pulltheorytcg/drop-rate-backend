"""Read-only movement of the same shared references shown in a collection.

Callers authorize and load physical copies with ``reference_portfolio`` first.
An old inventory cache, a catalogue-only comparison, or a recalculation of the
same old evidence cannot supply a current value or a manufactured weekly point.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from .inventory_reference_values import GUIDE, MAX_AGE, SOLD, _condition, _text, _time
from .language import clean_language


ACTIVE_STATUSES = {"DRAFT", "INSPECTION", "APPROVED", "RESERVED"}

# The current IDs come only from the authorized portfolio's shared resolver.
# Each lookup returns at most one baseline. The existing catalogue/time index
# bounds the scan; a page read never refreshes a provider or writes a snapshot.
HISTORY_SQL = """
select present.id as current_snapshot_id,present.catalogue_id,
 present.market_value_minor as current_value_minor,
 present.evidence_checked_at as current_at,present.calculated_at as current_recorded_at,
 present.evidence->>'method' as method,
 baseline.id as baseline_snapshot_id,baseline.market_value_minor as baseline_value_minor,
 baseline.evidence_checked_at as baseline_at,baseline.calculated_at as baseline_recorded_at
from tcg.catalogue_market_snapshots present
join tcg.catalogue_products p on p.id=present.catalogue_id
left join lateral (
 select history.id,history.market_value_minor,history.evidence_checked_at,history.calculated_at
 from tcg.catalogue_market_snapshots history
 where history.catalogue_id=present.catalogue_id
   and history.id<>present.id
   and history.identity_digest=present.identity_digest
   and history.basis_key=present.basis_key
   and history.basis_condition is not distinct from present.basis_condition
   and history.basis_language=present.basis_language
   and history.grading_company is not distinct from present.grading_company
   and history.grade is not distinct from present.grade
   and history.seal_status is not distinct from present.seal_status
   and history.algorithm_version=present.algorithm_version
   and history.evidence->>'method'=present.evidence->>'method'
   and history.evidence->>'source'=present.evidence->>'source'
   and history.evidence->>'ruleset_revision' is not distinct from present.evidence->>'ruleset_revision'
   and history.evidence->>'book_identity_digest' is not distinct from present.evidence->>'book_identity_digest'
   and history.market_value_minor>0
   and history.evidence_checked_at between
     present.evidence_checked_at-make_interval(days => $2::int+1)
     and present.evidence_checked_at-make_interval(days => greatest(1,$2::int-1))
   and history.calculated_at<=present.calculated_at-make_interval(days => greatest(1,$2::int-1))
   and history.evidence_checked_at<=history.calculated_at
   and (
     (history.evidence->>'method'='CATALOGUE_EBAY_V4'
       and history.evidence->>'input_sale_count'='5'
       and history.oldest_sale_at between history.evidence_checked_at-interval '90 days'
                                    and history.evidence_checked_at)
     or
     (history.evidence->>'method'='CATALOGUE_CARDMARKET_V1'
       and history.evidence->>'valuation_kind'='REFERENCE_ESTIMATE'
       and history.evidence->'reference'=present.evidence->'reference'
       and jsonb_build_array(
         history.evidence->'quote'->>'source',history.evidence->'quote'->>'finish',
         history.evidence->'quote'->>'source_field',history.evidence->'quote'->>'variant_id',
         history.evidence->'quote'->>'product_id',history.evidence->'quote'->>'original_currency',
         history.evidence->'quote'->>'fx_source',history.evidence->'quote'->>'reference_printing_id',
         history.evidence->'quote'->'reference_identity',history.evidence->'quote'->'reference_rarity')
       = jsonb_build_array(
         present.evidence->'quote'->>'source',present.evidence->'quote'->>'finish',
         present.evidence->'quote'->>'source_field',present.evidence->'quote'->>'variant_id',
         present.evidence->'quote'->>'product_id',present.evidence->'quote'->>'original_currency',
         present.evidence->'quote'->>'fx_source',present.evidence->'quote'->>'reference_printing_id',
         present.evidence->'quote'->'reference_identity',present.evidence->'quote'->'reference_rarity'))
   )
 order by abs(extract(epoch from history.evidence_checked_at-
     (present.evidence_checked_at-make_interval(days => $2::int)))),
   history.evidence_checked_at,history.calculated_at desc,history.id
 limit 1
) baseline on true
where present.id=any($1::uuid[])
 and present.identity_digest=md5(concat_ws(chr(31),p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language))
 and present.algorithm_version='drop-rate-market-v4'
 and present.evidence->>'method' in ('CATALOGUE_EBAY_V4','CATALOGUE_CARDMARKET_V1')
 and present.evidence_checked_at between $3::timestamptz-interval '7 days' and $3
 and present.evidence_checked_at<=present.calculated_at and present.calculated_at<=$3
 and present.market_value_minor>0
 and not exists(select 1 from tcg.market_source_mappings m
   where m.catalogue_id=p.id and m.source=case when present.evidence->>'method'='CATALOGUE_EBAY_V4' then 'EBAY' else 'CARDMARKET' end
   and m.match_status in ('REVIEW','REJECTED'))
 and (present.evidence->>'method'<>'CATALOGUE_CARDMARKET_V1' or (
   tcg.cardmarket_reference_current(present.evidence)
   and not exists(select 1 from tcg.provider_catalogue_mappings m where m.catalogue_id=p.id
     and m.provider_language=present.basis_language and m.match_status in ('REVIEW','REJECTED'))))
"""


def weekly_change_pct(current_minor: int | None, prior_minor: int | None) -> float | None:
    """Money inputs are integer pence; percentages are rounded deterministically."""
    if type(current_minor) is not int or type(prior_minor) is not int or prior_minor <= 0:
        return None
    # Database money is bigint; rejecting out-of-range inputs also excludes
    # non-finite or unbounded values from accidentally reaching the renderer.
    if not 0 <= current_minor <= 2**63-1 or prior_minor > 2**63-1:
        return None
    value = (Decimal(current_minor-prior_minor)*100/Decimal(prior_minor)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(value)


def _eligible(item: dict, now: datetime) -> bool:
    reference = item.get("reference_value") or {}
    checked = _time(reference.get("checked_at"))
    value = reference.get("market_value_minor")
    return (reference.get("status") in {"AVAILABLE", "REFERENCE_ESTIMATE"}
            and reference.get("method") in {SOLD, GUIDE}
            and type(value) is int and 0 < value <= 2**63-1
            and item.get("market_value_minor") == value
            and checked is not None and now-MAX_AGE <= checked <= now
            and bool(reference.get("snapshot_id")))


def _key(item: dict) -> str:
    fields = [str(item["catalogue_id"]), _condition(item.get("condition")),
              clean_language(item.get("language")) or clean_language(item.get("catalogue_language")),
              _text(item.get("grading_company")), _text(item.get("grade")), _text(item.get("seal_status")),
              item["reference_value"]["method"], str(item["reference_value"]["snapshot_id"])]
    return hashlib.sha256(json.dumps(fields).encode()).hexdigest()


async def shared_weekly_movers(connection, items: list[dict], *, window_days: int = 7,
                              now: datetime | None = None) -> dict:
    """Compare only the caller's authorized, currently valued physical profiles."""
    if type(window_days) is not int or not 1 <= window_days <= 90:
        raise ValueError("window_days must be between 1 and 90")
    now = now or datetime.now(timezone.utc)
    active = {str(item["id"]): item for item in items if item.get("status") in ACTIVE_STATUSES}
    current = [item for item in active.values() if _eligible(item, now)]
    groups = {}
    for item in sorted(current, key=lambda row: str(row["id"])):
        key = _key(item)
        if key not in groups:
            groups[key] = {"item": item, "quantity": 0}
        groups[key]["quantity"] += 1

    ids = list(dict.fromkeys(UUID(str(item["reference_value"]["snapshot_id"])) for item in current))
    history = {}
    for start in range(0, len(ids), 100):
        for row in await connection.fetch(HISTORY_SQL, ids[start:start+100], window_days, now):
            history[str(row["current_snapshot_id"])] = dict(row)

    comparisons = []
    for key, group in groups.items():
        item, quantity = group["item"], group["quantity"]
        reference = item["reference_value"]
        row = history.get(str(reference["snapshot_id"]))
        if not row or row.get("baseline_value_minor") is None:
            continue
        # Defend the response assembly as well as the SQL identity join.
        if (str(row["catalogue_id"]) != str(item["catalogue_id"])
                or row["method"] != reference["method"]
                or row["current_value_minor"] != reference["market_value_minor"]
                or _time(row["current_at"]) != _time(reference["checked_at"])):
            continue
        current_at, baseline_at = _time(row["current_at"]), _time(row["baseline_at"])
        current_recorded, baseline_recorded = _time(row.get("current_recorded_at")), _time(row.get("baseline_recorded_at"))
        gap_min = timedelta(days=max(1, window_days-1))
        if (baseline_at is None or current_recorded is None or baseline_recorded is None
                or not gap_min <= current_at-baseline_at <= timedelta(days=window_days+1)
                or not current_at <= current_recorded <= now
                or baseline_at > baseline_recorded or baseline_recorded > current_recorded-gap_min):
            continue
        percentage = weekly_change_pct(row["current_value_minor"], row["baseline_value_minor"])
        if percentage is None:
            continue
        selected = {field: item.get(field) for field in (
            "id", "catalogue_id", "inventory_code", "status", "condition", "grading_company", "grade",
            "language", "product_type", "game", "name", "set_name", "card_number", "variant", "rarity")}
        selected.update(row, pricing_key=key, inventory_id=item["id"], quantity=quantity,
                        change_pct=percentage, change_minor=row["current_value_minor"]-row["baseline_value_minor"],
                        current_market_value_minor=row["current_value_minor"],
                        prior_market_value_minor=row["baseline_value_minor"],
                        current_pricing_updated_at=row["current_at"], prior_calculated_at=row["baseline_at"],
                        comparison_kind="GUIDE_ESTIMATE" if reference["method"] == GUIDE else "SOLD_MARKET",
                        comparison_label="Guide estimate change" if reference["method"] == GUIDE else "Market value change",
                        comparison_days=round((current_at-baseline_at).total_seconds()/86400, 2))
        comparisons.append(selected)

    movers = sorted((row for row in comparisons if row["change_minor"] != 0),
                    key=lambda row: (-abs(row["change_pct"]), -abs(row["change_minor"]), row["pricing_key"]))
    status = ("EMPTY_COLLECTION" if not active else "NO_CURRENT_VALUES" if not current else
              "WAITING_FOR_HISTORY" if not comparisons else "NO_CHANGE" if not movers else "READY")
    return {"movers": movers, "summary": {
        "status": status, "scope": "OWN_COLLECTION", "valuation_basis": "SHARED_CATALOGUE_V1",
        "comparison_basis": "SHARED_CATALOGUE_HISTORY_V1", "window_days": window_days,
        "window_tolerance_days": 1, "as_of": now,
        "owned_item_count": len(active), "current_value_item_count": len(current),
        "current_value_product_count": len(groups), "comparable_product_count": len(comparisons),
        "comparable_item_count": sum(row["quantity"] for row in comparisons),
        "mover_product_count": len(movers), "unchanged_product_count": len(comparisons)-len(movers),
        "waiting_for_history_product_count": len(groups)-len(comparisons),
        "needs_details_item_count": sum((item.get("reference_value") or {}).get("status") == "NEEDS_DETAILS" for item in active.values()),
        "stale_item_count": sum((item.get("reference_value") or {}).get("status") == "STALE" for item in active.values()),
        "guide_comparison_count": sum(row["comparison_kind"] == "GUIDE_ESTIMATE" for row in comparisons),
        "history_ready": bool(comparisons),
        "earliest_baseline_at": min((row["baseline_at"] for row in comparisons), default=None),
        "latest_current_at": max((row["current_at"] for row in comparisons), default=None),
    }}
