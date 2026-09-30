"""Resumable reference-only sync; invoke explicitly as an authorised admin.

PYTHONPATH=backend python backend/scripts/sync_reference_library.py --actor-user-id UUID
No scheduler or startup hook is installed by this command.
"""
import argparse
import asyncio
import json
from uuid import UUID, uuid4

from app.db import create_pool, user_connection
from app.reference_feeds import ReferenceFeeds
from app.reference_library import save_reference_set
from app.settings import get_settings

SOURCES=('tcgdex','punk','dragon_ball_masters','dragon_ball_fusion','naruto_kayou','naruto_bandai')

async def sync(pool, actor, sources):
    async with user_connection(pool,actor,str(uuid4())) as conn:
        if not await conn.fetchval('select tcg.is_platform_admin()'):
            raise PermissionError('Reference sync requires a platform administrator')
    report={}
    for source in sources:
        feed=ReferenceFeeds()
        sets=cards=0
        async with user_connection(pool,actor,str(uuid4())) as conn:
            run_id=await conn.fetchval("insert into tcg.reference_sync_runs(source,status) values($1,'RUNNING') returning id",source)
        status='INCOMPLETE'
        try:
            async for record,items in getattr(feed,source)():
                if sets>=2000 or cards+len(items)>200000:
                    raise ValueError('Reference feed exceeds import bounds')
                async with user_connection(pool,actor,str(uuid4())) as conn:
                    await save_reference_set(conn,record,items)
                sets+=1
                cards+=len({c['provider_id'] for c in items})
            status='INCOMPLETE' if feed.failures else 'COMPLETE'
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            feed.failures.append({'reason':type(exc).__name__})
        finally:
            await feed.close()
            async with user_connection(pool,actor,str(uuid4())) as conn:
                await conn.execute('''update tcg.reference_sync_runs set status=$2,
                    finished_at=now(),sets_loaded=$3,cards_loaded=$4,report=$5::jsonb where id=$1''',
                    run_id,status,sets,cards,json.dumps({'failures':feed.failures}))
        report[source]={'status':status,'sets':sets,'cards':cards,'failures':feed.failures}
    return report

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actor-user-id',type=UUID,required=True)
    parser.add_argument('--source',choices=SOURCES,action='append')
    args=parser.parse_args()
    pool=await create_pool(get_settings())
    try:
        report=await sync(pool,args.actor_user_id,args.source or SOURCES)
        print(json.dumps(report))
        return 0 if all(r['status']=='COMPLETE' for r in report.values()) else 1
    finally:
        await pool.close()

if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
