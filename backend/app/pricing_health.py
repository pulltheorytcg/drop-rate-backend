"""Drop Rate first-party pricing health telemetry.

This is an authenticated, read-only observability endpoint. It never pulls
provider content, schedules paid scrapers, publishes market values, changes
retail prices or modifies canonical inventory/ownership.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Mapping

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder

from .access_control import require_business_founder
from .auth import AuthenticatedUser, require_user
from .database_capacity import operator_bulk_hold_requested
from .db import user_connection
from .ebay_sold_normalization import REVISION as VERIFIED_UK_NORMALIZATION_REVISION
from .settings import get_settings

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing-health"])

# These are actual persisted data classifications. Asking prices and guides
# must not be included in market-value eligible UK sale counts.
INVENTORY_SQL = """
select count(*)::integer as active_items,
       count(*) filter (where market_value_minor is not null)::integer as stored_value_items,
       count(*) filter (where market_value_minor is not null and
           pricing_updated_at >= now() - interval '7 days')::integer as recently_updated_items,
       max(pricing_updated_at) as latest_pricing_update_at
from tcg.inventory_items
where status in ('DRAFT', 'INSPECTION', 'APPROVED', 'RESERVED')
"""

SOURCES_SQL = """
select source, observation_type,
       count(*)::integer as total_observations,
       count(*) filter (where ingested_at >= now() - interval '24 hours')::integer as ingested_24h,
       count(*) filter (where ingested_at >= now() - interval '7 days')::integer as ingested_7d,
       max(ingested_at) as last_ingested_at,
       max(observed_at) as last_sale_or_guide_at,
       count(*) filter (where
         source = 'EBAY' and observation_type = 'SOLD'
         and source_country = 'GB' and currency = 'GBP'
         and metadata->'provider_evidence'->>'normalization_revision' = $1
         and metadata->'provider_evidence'->>'item_location_country' = 'GB'
         and metadata->'provider_evidence'->>'sale_price_basis' in (
             'AUCTION_SOLD_PRICE',
             'DETAILS_CONFIRMED_NON_OFFER',
             'DETAILS_CONFIRMED_ACCEPTED_OFFER'
         )
       )::integer as normalized_uk_sold,
       count(*) filter (where
         source = 'EBAY' and observation_type = 'SOLD'
         and ingested_at >= now() - interval '24 hours'
         and source_country = 'GB' and currency = 'GBP'
         and metadata->'provider_evidence'->>'normalization_revision' = $1
         and metadata->'provider_evidence'->>'item_location_country' = 'GB'
         and metadata->'provider_evidence'->>'sale_price_basis' in (
             'AUCTION_SOLD_PRICE',
             'DETAILS_CONFIRMED_NON_OFFER',
             'DETAILS_CONFIRMED_ACCEPTED_OFFER'
         )
       )::integer as normalized_uk_sold_ingested_24h,
       max(ingested_at) filter (where
         source = 'EBAY' and observation_type = 'SOLD'
         and source_country = 'GB' and currency = 'GBP'
         and metadata->'provider_evidence'->>'normalization_revision' = $1
         and metadata->'provider_evidence'->>'item_location_country' = 'GB'
         and metadata->'provider_evidence'->>'sale_price_basis' in (
             'AUCTION_SOLD_PRICE',
             'DETAILS_CONFIRMED_NON_OFFER',
             'DETAILS_CONFIRMED_ACCEPTED_OFFER'
         )
       ) as last_normalized_uk_sold_ingested_at
from tcg.market_observations
group by source, observation_type
order by source, observation_type
"""

RUNS_SQL = """
select distinct on (source)
       source, status, trigger_type, completed_at,
       inserted_count, fetched_count, failed_mapping_count
from tcg.market_ingestion_runs
order by source, completed_at desc, created_at desc
"""


def _record(row: Mapping[str, Any] | Any) -> dict:
    return dict(row) if row else {}


def _as_int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _fresh(instant: object, now: datetime, hours: int) -> bool:
    return isinstance(instant, datetime) and instant.tzinfo is not None and (
        timedelta(0) <= now - instant <= timedelta(hours=hours)
    )


def _safe_run(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    # Never return provider response bodies, errors, listing content or secrets.
    return {
        "status": str(row.get("status") or "UNKNOWN"),
        "trigger": str(row.get("trigger_type") or "UNKNOWN"),
        "completed_at": row.get("completed_at"),
        "inserted": _as_int(row.get("inserted_count")),
        "failed_mappings": _as_int(row.get("failed_mapping_count")),
    }


def summarise_pricing_health(
    inventory: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
    runs: list[Mapping[str, Any]],
    *,
    now: datetime,
    ingestion_enabled: bool,
    ebay_legacy_refresh_enabled: bool,
    catalogue_refresh_enabled: bool,
    bulk_hold: bool,
) -> dict[str, Any]:
    """Interpret actual source state without turning guides/asks into sold values."""
    if now.tzinfo is None:
        raise ValueError("Pricing health requires an aware clock")
    inventories = _record(inventory)
    active = _as_int(inventories.get("active_items"))
    stored = min(_as_int(inventories.get("stored_value_items")), active)
    recently = min(_as_int(inventories.get("recently_updated_items")), stored)
    rows = {(str(r.get("source") or ""), str(r.get("observation_type") or "")): _record(r)
            for r in observations}
    runs_by_source = {str(r.get("source") or ""): _record(r) for r in runs}
    sold = rows.get(("EBAY", "SOLD"), {})
    guide = rows.get(("CARDMARKET", "PRICE_GUIDE"), {})
    verified_total = _as_int(sold.get("normalized_uk_sold"))
    verified_new = _as_int(sold.get("normalized_uk_sold_ingested_24h"))
    old_sold_total = _as_int(sold.get("total_observations"))
    guide_total = _as_int(guide.get("total_observations"))
    guide_is_recent = _fresh(guide.get("last_ingested_at"), now, 48)
    sale_is_recent = _fresh(sold.get("last_normalized_uk_sold_ingested_at"), now, 24)
    ebay_run = _safe_run(runs_by_source.get("EBAY"))
    cardmarket_run = _safe_run(runs_by_source.get("CARDMARKET"))
    sources = [
        {
            "source": "EBAY_UK_SOLD", "label": "eBay UK completed sales",
            "role": "ACTUAL_SOLD_EVIDENCE",
            "status": ("FRESH_EVIDENCE" if verified_new > 0 and sale_is_recent
                       else "NO_RECENT_VERIFIED_EVIDENCE" if verified_total > 0
                       else "VERIFICATION_BLOCKED"),
            "stored_observations": old_sold_total,
            "normalized_uk_sold_observations": verified_total,
            "new_normalized_24h": verified_new,
            "new_observations_24h": _as_int(sold.get("ingested_24h")),
            "last_ingested_at": sold.get("last_ingested_at"),
            "last_eligible_at": sold.get("last_normalized_uk_sold_ingested_at"),
            "last_run": ebay_run,
            "detail": ("Sales must have exact UK identity, real paid-price proof "
                       "and approved provenance. Legacy unverified records do not qualify."),
        },
        {
            "source": "CARDMARKET_GUIDE", "label": "Cardmarket price guides",
            "role": "GUIDE_ONLY",
            "status": "CONTEXT_ONLY" if guide_is_recent else "STALE_CONTEXT",
            "stored_observations": guide_total,
            "new_observations_24h": _as_int(guide.get("ingested_24h")),
            "last_ingested_at": guide.get("last_ingested_at"),
            "last_run": cardmarket_run,
            "detail": "Guides cannot independently produce sold-backed Market Values.",
        },
        {
            "source": "EBAY_BROWSE", "label": "eBay official Browse",
            "role": "ASKING_ONLY",
            "status": "CONTEXT_ONLY",
            "stored_observations": None,
            "last_run": None,
            "detail": "Active listing asking prices are not completed sale prices.",
        },
        {
            "source": "EBAY_PRODUCT_RESEARCH", "label": "eBay Product Research",
            "role": "HUMAN_RESEARCH",
            "status": "AUTOMATED_ACCESS_NOT_VERIFIED",
            "stored_observations": None,
            "last_run": None,
            "detail": "An authenticated browser session does not grant unattended data collection rights.",
        },
    ]
    alerts: list[dict[str, str]] = []
    if verified_new == 0:
        alerts.append({
            "code": "NO_FRESH_QUALIFYING_UK_SOLD",
            "severity": "CRITICAL",
            "text": "No newly ingested qualifying UK completed-sale evidence in 24 hours.",
        })
    if verified_total == 0:
        alerts.append({
            "code": "NO_QUALIFYING_UK_SOLD_HISTORY",
            "severity": "WARNING",
            "text": "Stored eBay sales are not marked as eligible normalized UK paid-price evidence.",
        })
    if ebay_run and ebay_run["status"] == "FAILED":
        alerts.append({
            "code": "LAST_EBAY_RUN_FAILED",
            "severity": "WARNING",
            "text": "The most recent recorded eBay market job failed.",
        })
    if guide_total and not guide_is_recent:
        alerts.append({
            "code": "CARDMARKET_GUIDES_STALE",
            "severity": "WARNING",
            "text": "Cardmarket guide ingestion has not succeeded recently.",
        })
    if bulk_hold:
        alerts.append({
            "code": "OPERATOR_BULK_HOLD",
            "severity": "WARNING",
            "text": "The operator bulk-refresh safety hold is active.",
        })
    if not ingestion_enabled:
        alerts.append({
            "code": "MARKET_INGESTION_DISABLED",
            "severity": "WARNING",
            "text": "Automatic market ingestion is disabled pending permitted source access.",
        })
    if stored < active:
        alerts.append({
            "code": "MARKET_VALUE_COVERAGE_INCOMPLETE",
            "severity": "INFO",
            "text": "Some active inventory has no stored Market Value.",
        })
    overall = ("BLOCKED" if verified_new == 0 else
               "DEGRADED" if bulk_hold or not ingestion_enabled or stored < active else
               "OPERATIONAL")
    # Even a healthy DB count is not proof that source access is licensed.
    return {
        "checked_at": now,
        "overall_status": overall,
        "overall_label": ("Sold-price evidence blocked" if overall == "BLOCKED"
                          else "Needs attention" if overall == "DEGRADED"
                          else "Evidence arriving"),
        "inventory": {
            "active_items": active,
            "stored_value_items": stored,
            "missing_value_items": active - stored,
            "updated_last_7d": recently,
            "stored_coverage_pct": round(stored * 100 / active, 1) if active else 0.0,
            "latest_pricing_updated_at": inventories.get("latest_pricing_update_at"),
            "coverage_basis": "ACTIVE_PHYSICAL_INVENTORY_STORED_VALUES_NOT_VERIFIED_EVIDENCE",
        },
        "automation": {
            "market_ingestion_enabled": bool(ingestion_enabled),
            "legacy_ebay_refresh_enabled": bool(ebay_legacy_refresh_enabled),
            "catalogue_refresh_enabled": bool(catalogue_refresh_enabled),
            "bulk_refresh_held": bool(bulk_hold),
            "unattended_product_research_verified": False,
            "automatic_sold_value_publication_ready": False,
            "pricing_mode": "SAFE_MONITORING" if verified_new == 0 else "EVIDENCE_NEEDS_PUBLICATION_REVIEW",
        },
        "sources": sources,
        "alerts": alerts,
        "refresh_interval_seconds": 60,
    }


@router.get("/health")
async def live_pricing_health(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Founder-roster-only; actual PostgreSQL snapshot, never a canned report."""
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
        readonly_snapshot=True,
    ) as connection:
        await require_business_founder(connection)
        inventory = await connection.fetchrow(INVENTORY_SQL)
        observations = await connection.fetch(
            SOURCES_SQL, VERIFIED_UK_NORMALIZATION_REVISION
        )
        runs = await connection.fetch(RUNS_SQL)
    settings = get_settings()
    return jsonable_encoder(summarise_pricing_health(
        _record(inventory), [_record(x) for x in observations], [_record(x) for x in runs],
        now=datetime.now(timezone.utc),
        ingestion_enabled=settings.market_ingestion_enabled,
        ebay_legacy_refresh_enabled=settings.ebay_market_refresh_enabled,
        catalogue_refresh_enabled=settings.catalogue_daily_refresh_enabled,
        bulk_hold=operator_bulk_hold_requested(),
    ))
