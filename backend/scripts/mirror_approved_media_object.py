"""Bounded Railway operator job for rights-approved media → private R2.

Defaults to a read-only count. Use --apply only after migration, R2 health,
source-licence review and backend tests. No arbitrary URLs or object deletion.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import uuid4

import asyncpg

from app.r2_media import MIRROR_HOSTS, MIRROR_PROVIDERS, PENDING_MIRRORS_SQL, mirror_approved_media


async def run(limit: int, apply: bool) -> dict:
    dsn = os.getenv('TCG_DATABASE_URL', '').strip()
    if not dsn:
        raise RuntimeError('Database connection is not configured')
    pool = await asyncpg.create_pool(dsn=dsn,min_size=1,max_size=2,command_timeout=20)
    try:
        if apply:
            result = await mirror_approved_media(pool,limit=limit,
                                                 request_id=f'r2-media-pilot:{uuid4()}')
            if result['failed']:
                raise RuntimeError('At least one image could not be mirrored and verified')
            return {'mode':'APPLIED','result':result}
        async with pool.acquire() as connection:
            rows = await connection.fetch(PENDING_MIRRORS_SQL,sorted(MIRROR_PROVIDERS),limit,
                                          sorted(MIRROR_HOSTS))
        return {'mode':'DRY_RUN','candidate_count':len(rows),'limit':limit,'mutations':0}
    finally:
        await pool.close()


def main() -> None:
    parser=argparse.ArgumentParser(description='Private R2 approved-media mirror pilot')
    parser.add_argument('--limit',type=int,default=1,choices=range(1,6))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    result=asyncio.run(run(args.limit,args.apply))
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
