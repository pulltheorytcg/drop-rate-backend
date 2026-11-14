"""Read-only source-quality pilot; no catalogue, inventory or Shopify writes.

Usage (with server-side settings only):
  python backend/scripts/probe_cardtrader_price_source.py --max-expansions 1

Do not add --apply; this tool intentionally has no apply pathway. A separate
reviewed release is required for any scheduled pricing-cache updates.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.access_control import require_platform_admin
from app.cardtrader_client import CardTraderClient
from app.database_capacity import CAPACITY_SQL, PRO_REFRESH_PAUSE_BYTES, assess_capacity
from app.db import create_pool, user_connection
from app.fx import EcbHistoricalFxProvider
from app.pricing_source_preflight import MAX_PREFLIGHT_EXPANSIONS, preview_cardtrader_expansions
from app.pricing_source_receipts import begin_preflight_receipt, complete_preflight_receipt
from app.settings import get_settings


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-expansions", type=int, default=1,
                        help="Read-only probe of 1..2 canonical CardTrader expansions")
    args = parser.parse_args(argv)
    if not 1 <= args.max_expansions <= MAX_PREFLIGHT_EXPANSIONS:
        parser.error("--max-expansions must be 1..2")
    return args


async def run(args):
    settings = get_settings()
    if not settings.cardtrader_api_token:
        return {"event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT",
                "status": "BLOCKED", "reason": "CARDTRADER_OFFICIAL_KEY_UNAVAILABLE"}
    actor = UUID(settings.catalogue_maintenance_actor_user_id or "")
    pool = await create_pool(settings)
    try:
        # This probe reads sources while the deliberate bulk-writer hold stays
        # active. Do not permit it on an unverified Free-plan configuration or
        # on a near-capacity/read-only database.
        async with user_connection(pool, actor, str(uuid4())) as connection:
            await require_platform_admin(connection)
            row = await connection.fetchrow(CAPACITY_SQL)
            state = assess_capacity(row["database_bytes"], row["default_read_only"])
            if (state.plan != "pro" or row["default_read_only"] != "off"
                    or row["database_bytes"] >= PRO_REFRESH_PAUSE_BYTES):
                return {"event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT",
                        "status": "BLOCKED", "reason": "PRO_CAPACITY_PREFLIGHT_NOT_SATISFIED"}
            # Advance the read-only pricing-source probe independently.
            # Older preflight receipts before PR #1094 recorded their last
            # release in by_release but no next_cursor. Never reuse these
            # diagnostic rows as the pricing writer's actual apply cursor.
            previous = await connection.fetchrow("""
                select coalesce(
                    report->>'next_cursor',
                    (select item->>'release'
                       from jsonb_array_elements(
                         case when jsonb_typeof(report->'by_release')='array'
                              then report->'by_release' else '[]'::jsonb end
                       ) with ordinality as details(item,position)
                      order by position desc limit 1)
                ) as cursor
                from tcg.catalogue_job_runs
                where job='CARDTRADER_SOURCE_PREFLIGHT' and status='COMPLETE'
                order by started_at desc limit 1
            """)
            if not previous or not previous["cursor"]:
                previous = await connection.fetchrow("""
                    select report->>'cursor' as cursor
                    from tcg.catalogue_job_runs
                    where job='CARDTRADER_EXPANSION_GUIDES' and status='COMPLETE'
                    order by started_at desc limit 1
                """)
        cursor = previous["cursor"] if previous else None
        # A distinct audit job leaves a durable, independent outcome even when
        # Railway's short-lived container stdout is unavailable. No catalogue
        # or financial records are modified. Never register this as the legacy
        # CARDTRADER_EXPANSION_GUIDES job: its cursor feeds the live price writer.
        receipt_id = uuid4()
        await begin_preflight_receipt(pool, actor, receipt_id,
                                      expansion_limit=args.max_expansions)
        try:
            report = await preview_cardtrader_expansions(
                pool, actor, EcbHistoricalFxProvider(timeout_seconds=6),
                CardTraderClient(api_token=settings.cardtrader_api_token, timeout_seconds=20),
                expansion_limit=args.max_expansions, previous_cursor=cursor,
            )
            report["status"] = "COMPLETE" if report["provider_failures"] == 0 else "INCOMPLETE"
            report["bulk_writer_hold_preserved"] = True
        except Exception as exc:
            # Only the exception CLASS is safe; raw upstream errors and
            # seller/credential-bearing URLs never enter the audit ledger.
            report = {"event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT",
                      "source": "CARDTRADER_EXPANSION_ASKING",
                      "evidence_kind": "ACTIVE_ASKING_NOT_SOLD",
                      "mode": "DRY_RUN", "status": "FAILED",
                      "error_class": type(exc).__name__,
                      "requested_expansions": args.max_expansions,
                      "bulk_writer_hold_preserved": True,
                      "inventory_writes": 0, "store_price_writes": 0,
                      "catalogue_price_writes": 0}
        await complete_preflight_receipt(pool, actor, receipt_id, report)
        report["receipt_id"] = str(receipt_id)
        return report
    finally:
        await pool.close()


def main() -> int:
    try:
        report = asyncio.run(run(arguments()))
    except Exception as exc:
        report = {"event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT",
                  "status": "FAILED", "reason": type(exc).__name__}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
