"""Bounded administrator backfill of existing rights-approved private R2 media.

Dry-run is the default. Every DB lease rechecks the configured administrator.
A soft deadline stops between batches; in-flight S3 verification is never cancelled.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import time
from contextlib import asynccontextmanager
from uuid import UUID,uuid4

from app.access_control import require_platform_admin
from app.db import create_pool,user_connection
from app.settings import get_settings
from app.r2_media import MIRROR_HOSTS,MIRROR_PROVIDERS,PENDING_MIRRORS_SQL,mirror_approved_media
from app.recognition_images import close_reference_http_client


class AdministratorPool:
    def __init__(self,pool,actor,request_id):
        self.pool,self.actor,self.request_id=pool,actor,request_id

    @asynccontextmanager
    async def acquire(self):
        async with user_connection(self.pool,self.actor,self.request_id) as connection:
            await require_platform_admin(connection)
            yield connection


async def pending(pool):
    async with pool.acquire() as connection:
        return await connection.fetch(PENDING_MIRRORS_SQL,sorted(MIRROR_PROVIDERS),501,sorted(MIRROR_HOSTS))


async def run_with_pool(pool,actor,*,apply=False,max_batches=100,max_seconds=120,batch_size=5):
    if (type(apply) is not bool or type(max_batches) is not int or not 1<=max_batches<=100
            or type(max_seconds) is not int or not 1<=max_seconds<=180
            or type(batch_size) is not int or not 1<=batch_size<=5):
        raise ValueError("R2_BACKFILL_LIMITS_INVALID")
    request_id="r2-approved-backfill:"+str(uuid4())
    authorized=AdministratorPool(pool,UUID(str(actor)),request_id)
    initial=await pending(authorized)
    report={"mode":"APPLY" if apply else "DRY_RUN","candidate_count":len(initial),
            "candidate_count_capped":len(initial)==501,"maximum_candidates":500,
            "administrator_authorized":True,"soft_max_seconds":max_seconds,
            "examined":0,"mirrored":0,"failed":0,"skipped":0,"batches":0}
    if not apply:
        return {**report,"mutations":0}
    ids=[r["id"] for r in initial[:500]]
    deadline=time.monotonic()+max_seconds
    attempted=[]
    for offset in range(0,len(ids),batch_size):
        if report["batches"]>=max_batches or time.monotonic()>=deadline:
            break
        batch=ids[offset:offset+batch_size]
        result=await mirror_approved_media(authorized,limit=len(batch),
            request_id=request_id,candidate_ids=batch)
        attempted.extend(batch)
        for key in ("examined","mirrored","failed","skipped"):
            report[key]+=result[key]
        report["batches"]+=1
        print("R2_APPROVED_BATCH "+json.dumps({"batch":report["batches"],**result},sort_keys=True),flush=True)
    remaining=await pending(authorized)
    report.update(remaining_candidates=len(remaining),remaining_count_capped=len(remaining)==501,
        attempted_candidates=len(attempted),unattempted_from_snapshot=len(ids)-len(attempted),
        status="COMPLETE" if not remaining else "PARTIAL",committed=True)
    return report


async def run(**kwargs):
    settings=get_settings()
    actor=settings.catalogue_maintenance_actor_user_id
    if not actor:
        raise ValueError("R2_BACKFILL_ADMINISTRATOR_REQUIRED")
    actor=UUID(actor)
    pool=await create_pool(settings)
    try:
        return await run_with_pool(pool,actor,**kwargs)
    finally:
        await close_reference_http_client()
        await pool.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--max-batches",type=int,default=100)
    parser.add_argument("--max-seconds",type=int,default=120)
    parser.add_argument("--batch-size",type=int,default=5)
    args=parser.parse_args()
    try:
        result=asyncio.run(run(apply=args.apply,max_batches=args.max_batches,
                              max_seconds=args.max_seconds,batch_size=args.batch_size))
    except Exception as exc:
        print("R2_APPROVED_BACKFILL "+json.dumps({"status":"FAILED_RECONCILE_BEFORE_RETRY",
              "error_type":type(exc).__name__}),flush=True)
        raise SystemExit(2)
    print("R2_APPROVED_BACKFILL "+json.dumps(result,sort_keys=True),flush=True)


if __name__=="__main__":
    main()
