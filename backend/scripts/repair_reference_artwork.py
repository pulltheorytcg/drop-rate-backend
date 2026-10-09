"""Explicit, idempotent artwork repair for existing One Piece references.

Dry-run by default; --apply writes only missing reference artwork and provenance.
No scheduler, new reference cards, canonical approvals or inventory writes.
"""
import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.access_control import require_platform_admin
from app.db import create_pool, user_connection
from app.reference_artwork import REPAIR_SQL, match_existing_artwork, punk_pack_artwork, punk_pack_url
from app.reference_feeds import ReferenceFeeds
from app.settings import get_settings


async def repair(pool, actor, *, apply=False):
    request_id = str(uuid4())
    async with user_connection(pool, actor, request_id) as conn:
        await require_platform_admin(conn)
        rows = await conn.fetch("""select language,set_id,provider_id,name from tcg.reference_cards
          where provider='Punk Records' and system_code='ONE_PIECE_CARD_GAME'
          and language in ('English','Japanese') and nullif(btrim(image_url),'') is null
          order by language,set_id,provider_id limit 10001""")
    if len(rows) > 10000:
        raise ValueError("Artwork repair exceeds bounded inventory")
    groups = defaultdict(list)
    for row in rows:
        groups[(row['language'], row['set_id'])].append(dict(row))
    report = {'apply': apply, 'requested': len(rows), 'matched': 0, 'updated': 0, 'packs': [], 'failures': []}
    if not groups:
        return report
    run_id = None
    if apply:
        async with user_connection(pool, actor, request_id) as conn:
            await require_platform_admin(conn)
            run_id = await conn.fetchval("insert into tcg.reference_sync_runs(source,status) values('punk_artwork_repair','RUNNING') returning id")
    feed = ReferenceFeeds()
    completed = False
    try:
        for (language, set_id), existing in groups.items():
            try:
                payload = await feed.get(punk_pack_url(language, set_id))
                artwork, evidence = punk_pack_artwork(payload, language=language, set_id=set_id)
                candidates = match_existing_artwork(existing, artwork)
                report['matched'] += len(candidates)
                changed = []
                if apply and candidates:
                    async with user_connection(pool, actor, request_id) as conn:
                        await require_platform_admin(conn)
                        evidence.update(checked_at=datetime.now(timezone.utc).isoformat(), actor_user_id=str(actor), run_id=str(run_id))
                        changed = await conn.fetch(REPAIR_SQL, language, set_id, json.dumps(candidates), json.dumps(evidence))
                    report['updated'] += len(changed)
                report['packs'].append({'language': language, 'set_id': set_id, 'matched': len(candidates), 'updated': len(changed)})
            except Exception as exc:
                report['failures'].append({'language': language, 'set_id': set_id, 'error': type(exc).__name__})
                break
        completed = not report['failures']
    finally:
        await feed.close()
        if run_id:
            async with user_connection(pool, actor, request_id) as conn:
                await require_platform_admin(conn)
                await conn.execute("""update tcg.reference_sync_runs set status=$2,finished_at=now(),
                  sets_loaded=$3,cards_loaded=$4,report=$5::jsonb where id=$1""", run_id,
                    'COMPLETE' if completed else 'INCOMPLETE', len(report['packs']), report['updated'], json.dumps(report))
    return report


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actor-user-id', type=UUID, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    pool = await create_pool(get_settings())
    try:
        report = await repair(pool, args.actor_user_id, apply=args.apply)
        print('REFERENCE_ARTWORK_REPAIR ' + json.dumps(report), flush=True)
        return 1 if report['failures'] else 0
    finally:
        await pool.close()


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
