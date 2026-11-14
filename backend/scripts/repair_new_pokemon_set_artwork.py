"""Bounded Pokémon newest-set missing-artwork repair; read-only by default.

Source-only mode needs no production secrets; production apply requires an
authorized database actor plus DROP_RATE_POKEMON_NEW_ARTWORK_APPLY_CONFIRMED=YES.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID
from app.pokemon_new_set_artwork import MAX_ROWS, MAX_SECONDS, run


def log_progress(value):
    print("POKEMON_NEW_ARTWORK_PROGRESS "+json.dumps(value,sort_keys=True),flush=True)


async def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-only",action="store_true")
    ap.add_argument("--from-settings",action="store_true")
    ap.add_argument("--actor-user-id",type=UUID)
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--limit",type=int,default=MAX_ROWS)
    ap.add_argument("--max-seconds",type=int,default=MAX_SECONDS)
    args=ap.parse_args()
    if args.source_only and (args.apply or args.from_settings or args.actor_user_id):
        ap.error("--source-only cannot apply or acquire privileged credentials")
    if not args.source_only and not(args.from_settings or args.actor_user_id):
        ap.error("Select --source-only, --from-settings, or --actor-user-id")
    pool=None
    try:
        if args.source_only:
            report=await run(sample_only=True,max_rows=args.limit,max_seconds=args.max_seconds)
        else:
            from app.db import create_pool
            from app.settings import get_settings
            settings=get_settings()
            actor=args.actor_user_id or UUID(settings.catalogue_maintenance_actor_user_id)
            pool=await create_pool(settings)
            report=await run(pool,actor,apply=args.apply,max_rows=args.limit,
                             max_seconds=args.max_seconds,progress=log_progress)
    except Exception as exc:
        print("POKEMON_NEW_ARTWORK_RESULT "+json.dumps({
            "status":"FAILED_CLOSED","error_type":type(exc).__name__,"writes_confirmed":False
        }),flush=True)
        return 2
    finally:
        if pool:
            await pool.close()
    print("POKEMON_NEW_ARTWORK_RESULT "+json.dumps(report,sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
