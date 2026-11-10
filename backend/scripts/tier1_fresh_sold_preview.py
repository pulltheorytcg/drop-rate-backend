"""One bounded, owner-authorized, READ-ONLY live UK sold-comparable pilot.

Never run this as the live API startup command. It performs exactly one Trawl
sold-search page for a fixed, already-approved physical item and writes nothing.
Result is an internal receipt, NOT a Market Value or Shopify update.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
from fastapi import HTTPException

class PilotSafetyError(RuntimeError):
    """Safe machine-readable error. Never includes owner or credentials."""
    pass

from app.access_control import require_platform_admin
from app.db import user_connection
from app.ebay_sold_normalization import has_normalized_uk_evidence
from app.ebay_sold_pricing import _fetch_comp_result

TARGET_CODE = "INV-3B801C9CE17B48DEA1EE0DD8AB38EA25"
IDENTITY = {
    "product_type": "CARD",
    "game": "Pokemon",
    "name": "Charmander",
    "set_name": "Phantasmal Flames",
    "card_number": "011/094",
    "variant": "Normal",
    "language": "English",
    "condition": "Near Mint",
    "grading_company": None,
    "grade": None,
    "seal_status": None,
}
READ_SQL = """
SELECT i.id,i.inventory_code,i.catalogue_id,i.owner_id,i.identity_confirmed,
 i.status,i.market_value_minor,i.store_price_minor,i.condition,i.language,
 i.grading_company,i.grade,i.seal_status,p.product_type,p.game,p.name,
 p.set_name,p.card_number,p.variant
FROM tcg.inventory_items i
JOIN tcg.catalogue_products p ON p.id=i.catalogue_id
WHERE i.inventory_code=$1
  AND i.status='APPROVED' AND i.identity_confirmed
  AND i.market_value_minor IS NULL
  AND EXISTS (
     SELECT 1 FROM tcg.shopify_inventory_links l
      WHERE l.inventory_id=i.id AND l.sync_state='PUBLISHED'
  )
"""

def safe_receipt(result: dict, *, now: datetime | None = None) -> dict:
    """One-page private report. Never echo listing titles, IDs or URLs."""
    now = now or datetime.now(timezone.utc)
    comps = list(result.get("comps") or [])
    eligible = [
        comp for comp in comps
        if comp.provider_evidence
        and has_normalized_uk_evidence({"provider_evidence": comp.provider_evidence})
    ]
    recent = [
        comp for comp in eligible
        if isinstance(comp.sold_at, datetime) and comp.sold_at.tzinfo
        and now - timedelta(days=14) <= comp.sold_at <= now + timedelta(minutes=5)
    ]
    all_normalized = len(comps) == 5 and len(eligible) == 5
    recent_enough = bool(recent)
    is_ready = result.get("status") == "READY" and all_normalized and recent_enough
    return {
        "scope": "ONE_CARD_UK_SOLD_READ_ONLY",
        "status": ("READY_FOR_SEPARATE_MANUAL_REVIEW" if is_ready
                   else "BLOCKED_INSUFFICIENT_OR_STALE_EVIDENCE"),
        "target_inventory_code": TARGET_CODE,
        "provider": "TRAWL_SOLD_API_NOT_OFFICIAL_EBAY",
        "requested_provider_pages": 1,
        "comparable_count": len(comps),
        "normalized_uk_sold_count": len(eligible),
        "recent_14d_count": len(recent),
        "sale_date_range": (
            [min(x.sold_at for x in eligible).date().isoformat(),
             max(x.sold_at for x in eligible).date().isoformat()]
            if eligible else None
        ),
        "candidate_market_value_minor": (result.get("market_value_minor") if is_ready else None),
        "result_is_not_a_current_market_value": True,
        "applied": False,
        "sql_or_r2_writes": False,
        "shopify_or_store_price_writes": False,
        "requires_separate_price_publication_review": True,
    }

async def run() -> dict:
    dsn = os.getenv("TCG_DATABASE_URL", "").strip()
    actor = os.getenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID", "").strip()
    if not dsn or not actor or not os.getenv("TCG_TRAWL_API_KEY", "").strip():
        raise PilotSafetyError("MISSING_EXISTING_REFERENCE")
    actor_id = UUID(actor)
    pool = await asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=1, command_timeout=12,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        async with user_connection(pool, actor_id, "tier1-sold-preview-one", readonly_snapshot=True) as conn:
            await require_platform_admin(conn)
            # On transaction-pooler endpoints, session defaults may not reflect
            # startup parameters. Always assert the actual in-flight, explicit
            # READ ONLY transaction, never a global role or session default.
            readonly = await conn.fetchval("SHOW transaction_read_only")
            if readonly != "on":
                raise PilotSafetyError("TRANSACTION_NOT_READ_ONLY")
            raw = await conn.fetchrow(READ_SQL, TARGET_CODE)
            if raw is None:
                raise PilotSafetyError("TARGET_NO_LONGER_ELIGIBLE")
            target = dict(raw)
            if any(target.get(key) != value for key, value in IDENTITY.items()):
                raise PilotSafetyError("EXACT_IDENTITY_CHANGED")
            if target["store_price_minor"] != 100:
                raise PilotSafetyError("EXISTING_STORE_PRICE_CHANGED")
            # The physical item's owner is not printed. Its ID is fixed and not
            # derived from any other founder's unapproved stock.
            target = {key: target[key] for key in (*IDENTITY, "catalogue_id")}
        # Provider I/O happens after closing the RLS-authorized DB lease.
        result = await asyncio.wait_for(_fetch_comp_result(target), timeout=50)
        return safe_receipt(result)
    finally:
        await pool.close()

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1, choices=[1])
    parser.add_argument("--read-only", action="store_true", required=True)
    args = parser.parse_args()
    if args.limit != 1:
        raise SystemExit("Only one item may be previewed")
    try:
        report = asyncio.run(run())
    except Exception as error:
        print("TIER1_SOLD_ONE_SHOT " + json.dumps({
            "status": "FAILED_CLOSED_NO_RETRY",
            "error_type": type(error).__name__,
            "safe_error_code": (
                str(error) if isinstance(error, PilotSafetyError)
                else "PROVIDER_429_NO_RETRY" if isinstance(error, HTTPException) and error.status_code == 429
                else "PROVIDER_OR_NETWORK_BLOCKED" if isinstance(error, HTTPException)
                else "OTHER_FAIL_CLOSED"
            ),
            "applied": False,
        }), flush=True)
        raise SystemExit(2)
    print("TIER1_SOLD_ONE_SHOT " + json.dumps(report, sort_keys=True), flush=True)

if __name__ == "__main__":
    main()
