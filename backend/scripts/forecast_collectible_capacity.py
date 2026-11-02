"""Advisory database-size forecast for proposed canonical CARD references.

Uses an actual read-only PostgreSQL snapshot when TCG_DATABASE_URL is present.
Otherwise supply all three numeric snapshot fields for an offline estimate.
No SQL writes, market pricing, R2 publication or Shopify operations occur.

Example (read-only in a configured backend runtime):
  PYTHONPATH=backend python backend/scripts/forecast_collectible_capacity.py --cards 1179
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os

import asyncpg

from app.collectible_capacity_forecast import (
    CardReferenceFootprint,
    forecast_card_reference_growth,
)


CAPACITY_METRICS_SQL = """select pg_database_size(current_database())::bigint as database_bytes,
    (select count(*)::bigint from tcg.reference_cards) as reference_card_rows,
    pg_total_relation_size('tcg.reference_cards')::bigint as reference_card_table_bytes"""


async def live_footprint(database_url: str) -> CardReferenceFootprint:
    """Single read-only transaction; never reads personal inventory rows."""
    conn = await asyncpg.connect(
        dsn=database_url, timeout=10, command_timeout=15,
        server_settings={"search_path": "pg_catalog,tcg", "statement_timeout": "15000"},
    )
    try:
        async with conn.transaction(readonly=True):
            row = await conn.fetchrow(CAPACITY_METRICS_SQL)
        if row is None:
            raise ValueError("Reference capacity snapshot unavailable")
        return CardReferenceFootprint(**dict(row))
    finally:
        await conn.close()


async def report(args: argparse.Namespace) -> dict:
    snapshot = (args.database_bytes, args.reference_rows, args.reference_table_bytes)
    if all(item is None for item in snapshot):
        dsn = os.getenv("TCG_DATABASE_URL")
        if not dsn:
            raise ValueError("TCG_DATABASE_URL or all three offline snapshot fields required")
        footprint = await live_footprint(dsn)
        evidence = "LIVE_READ_ONLY"
    elif all(item is not None for item in snapshot):
        footprint = CardReferenceFootprint(*snapshot)
        evidence = "OFFLINE_SNAPSHOT_RECHECK_BEFORE_IMPORT"
    else:
        raise ValueError("All three offline snapshot fields must be specified together")
    return {
        "evidence_mode": evidence,
        **forecast_card_reference_growth(
            footprint, proposed_reference_cards=args.cards,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=int, required=True,
                        help="Proposed distinct canonical card reference rows")
    parser.add_argument("--database-bytes", type=int)
    parser.add_argument("--reference-rows", type=int)
    parser.add_argument("--reference-table-bytes", type=int)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(report(args)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
