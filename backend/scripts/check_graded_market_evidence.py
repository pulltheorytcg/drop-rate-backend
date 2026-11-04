"""Read-only, two-item maximum check of the configured sold-data provider.

Run with PYTHONPATH=backend and one or two explicit inventory UUIDs. Requires the
configured platform-admin maintenance actor. Never prints secrets or writes DB.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from app.access_control import require_platform_admin
from app.db import create_pool, user_connection
from app.ebay_sold_pricing import TrawlApiError, TrawlEbaySoldClient
from app.live_market_refresh import TARGET_SQL, eligibility, query_for, select_comps, value_comps
from app.settings import get_settings


async def check(ids):
    settings = get_settings()
    pool = await create_pool(settings)
    try:
        actor = UUID(settings.catalogue_maintenance_actor_user_id)
        async with user_connection(pool, actor, 'graded-evidence-check', readonly_snapshot=True) as connection:
            await require_platform_admin(connection)
            rows = await connection.fetch(TARGET_SQL + ' where i.id=any($1::uuid[])', ids)
        if len(rows) != len(ids):
            raise ValueError('All requested inventory items must be visible')
        client = TrawlEbaySoldClient(api_key=settings.trawl_api_key)
        for row in rows:
            target = dict(row)
            reason = eligibility(target)
            if reason or not (target['grading_company'] and target['grade']):
                print(json.dumps({'status': 'INELIGIBLE', 'inventory_id': str(target['id']),
                                  'reason': reason or 'EXACT_GRADE_REQUIRED'}), flush=True)
                continue
            try:
                payload = await client.sold(query=query_for(target), max_pages=1)
                now = datetime.now(timezone.utc)
                comps = select_comps(payload, target, now)
                value = value_comps(comps, target, now=now).market_value_minor if len(comps) == 5 else None
                print(json.dumps({'diagnostic': 'graded-evidence-check', 'inventory_id': str(target['id']),
                                  'normalization': payload.get('_normalization'), 'usage': payload.get('_usage'),
                                  'exact_count': len(comps), 'market_value_minor': value,
                                  'database_writes': 0}), flush=True)
            except TrawlApiError as exc:
                print(json.dumps({'diagnostic': 'graded-evidence-check', 'status': 'PROVIDER_UNAVAILABLE',
                                  'provider_status': exc.status_code, 'error': exc.detail,
                                  'database_writes': 0}), flush=True)
                break
    finally:
        await pool.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory_ids', nargs='+', type=UUID)
    args = parser.parse_args()
    ids = list(dict.fromkeys(args.inventory_ids))
    if not 1 <= len(ids) <= 2:
        parser.error('Supply one or two unique inventory UUIDs')
    asyncio.run(check(ids))
