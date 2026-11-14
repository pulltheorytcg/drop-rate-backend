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
            previous = await connection.fetchrow("""
                select report->>'cursor' as cursor
                from tcg.catalogue_job_runs
                where job='CARDTRADER_EXPANSION_GUIDES' and status='COMPLETE'
                order by started_at desc limit 1
            """)
        cursor = previous["cursor"] if previous else None
        report = await preview_cardtrader_expansions(
            pool, actor, EcbHistoricalFxProvider(timeout_seconds=6),
            CardTraderClient(api_token=settings.cardtrader_api_token, timeout_seconds=20),
            expansion_limit=args.max_expansions, previous_cursor=cursor,
        )
        report["status"] = "COMPLETE" if report["provider_failures"] == 0 else "INCOMPLETE"
        report["bulk_writer_hold_preserved"] = True
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
