"""Bounded, exact-print R2 cache for *reference-only* provider artwork.

This is deliberately separate from the rights-approved canonical-media mirror:
it never approves the image for Shopify, listings, or public CDN publication.
The current reference row and its original URL remain authoritative. Opt-in
operation must be limited to provider sources for which Drop Rate has assessed
the applicable use and redistribution terms.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from .object_storage import ObjectStorageError, configured_object_storage
from .r2_media import optimized_media_bytes
from .recognition_images import reference_image_bytes, reference_display_min_dimension
from .access_control import require_platform_admin
from .db import user_connection
from .database_capacity import check_database_capacity

logger = logging.getLogger(__name__)
MIRROR_WORKER_LOCK = 847220098


class ReferenceActorPool:
    """Apply the existing maintenance actor on every short database lease."""
    def __init__(self, pool, actor):
        self.pool = pool
        self.actor = UUID(str(actor))

    @asynccontextmanager
    async def acquire(self):
        async with user_connection(self.pool, self.actor, 'r2-reference-'+str(uuid4())) as connection:
            await require_platform_admin(connection)
            yield connection


def worker_enabled() -> bool:
    return (os.getenv('TCG_R2_REFERENCE_CACHE_WORKER_ENABLED','false').lower() in ('true','1')
            and os.getenv('TCG_R2_REFERENCE_CACHE_APPLY_ENABLED','false').lower() in ('true','1'))

PENDING_REFERENCE_IMAGES_SQL = """
with pending as (
select r.provider,r.system_code,r.language,r.provider_id,r.image_url,
       case when m.source_url=r.image_url then m.failure_count else 0 end as failure_count,
       coalesce(m.status='RETRY' and m.source_url=r.image_url,false) as is_retry,
       m.next_retry_at
from tcg.reference_cards r
left join tcg.reference_image_mirrors m
  using(provider,system_code,language,provider_id)
where r.image_url is not null
  and ((r.provider='TCGdex' and r.system_code='POKEMON_TCG'
         and split_part(r.image_url,'/',3) in ('assets.tcgdex.net','cardtrader.com'))
       or (r.provider='Naruto Card Game Archive'
           and r.system_code in ('NARUTO_BANDAI_LEGACY','NARUTO_KAYOU')
           and split_part(r.image_url,'/',3)='narutocardgame.gg')
       or (r.provider='Bandai Official' and
           r.system_code in ('DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD')
           and split_part(r.image_url,'/',3)='www.dbs-cardgame.com')
       or (r.provider in ('Punk Records','Bandai Official')
           and r.system_code='ONE_PIECE_CARD_GAME'
           and split_part(r.image_url,'/',3) in
               ('en.onepiece-cardgame.com','www.onepiece-cardgame.com')))
  and (m.provider is null or m.source_url is distinct from r.image_url
       or (m.status='RETRY' and m.next_retry_at<=now()))
), ranked as (
  select *,row_number() over (
    partition by is_retry order by next_retry_at nulls last,random()
  ) as queue_position
  from pending
)
select provider,system_code,language,provider_id,image_url,failure_count
from ranked
-- Reserve four places for due retries; fill the rest with new/changed images.
-- Either queue may fill unused places when the other queue is exhausted.
order by case when is_retry and queue_position<=4 then 0
              when not is_retry then 1 else 2 end,queue_position
limit $1
"""

RECORD_REFERENCE_IMAGE_SQL = """
insert into tcg.reference_image_mirrors as mirror
    (provider,system_code,language,provider_id,source_url,object_key,
     content_sha256,size_bytes,status,failure_count,verified_at)
select r.provider,r.system_code,r.language,r.provider_id,r.image_url,
       $6,$7,$8,'VERIFIED',0,clock_timestamp()
from tcg.reference_cards r
where (r.provider,r.system_code,r.language,r.provider_id)=($1,$2,$3,$4)
  and r.image_url=$5
on conflict (provider,system_code,language,provider_id) do update
  set source_url=excluded.source_url,object_key=excluded.object_key,
      content_sha256=excluded.content_sha256,size_bytes=excluded.size_bytes,
      status='VERIFIED',failure_count=0,next_retry_at=null,
      last_error_code=null,verified_at=clock_timestamp(),
      updated_at=clock_timestamp()
  where mirror.status='RETRY' or mirror.source_url is distinct from excluded.source_url
returning provider_id
"""

RECORD_REFERENCE_FAILURE_SQL = """
insert into tcg.reference_image_mirrors as mirror
    (provider,system_code,language,provider_id,source_url,status,
     failure_count,next_retry_at,last_error_code)
select r.provider,r.system_code,r.language,r.provider_id,r.image_url,
       'RETRY',1,$6,$7
from tcg.reference_cards r
where (r.provider,r.system_code,r.language,r.provider_id)=($1,$2,$3,$4)
  and r.image_url=$5
on conflict (provider,system_code,language,provider_id) do update
  set source_url=excluded.source_url,status='RETRY',object_key=null,
      content_sha256=null,size_bytes=null,verified_at=null,
      failure_count=case when mirror.source_url=excluded.source_url
        then least(mirror.failure_count+1,1000000) else 1 end,
      next_retry_at=excluded.next_retry_at,last_error_code=excluded.last_error_code,
      updated_at=clock_timestamp()
  where mirror.status='RETRY' or mirror.source_url is distinct from excluded.source_url
returning provider_id
"""


def accepted_reference_url(url: str, provider: str, system_code: str) -> bool:
    """Use the same strict URL/printing rules as the live reference-image route."""
    from .catalogue_browser import provider_reference_artwork_url
    return provider_reference_artwork_url(url, provider, system_code)


async def _record_failure(pool: Any, item: dict, *, request_id: str, code: str) -> None:
    previous = max(0, int(item.get('failure_count') or 0))
    minutes = min(360, 5 * (2 ** min(previous, 6)))
    retry = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("select set_config('tcg.request_id',$1,true)",request_id)
            await connection.fetchval(RECORD_REFERENCE_FAILURE_SQL,
                *(item[k] for k in ('provider','system_code','language','provider_id','image_url')),
                retry,code)


async def mirror_reference_images(pool: Any, *, limit: int, request_id: str) -> dict:
    """Small, restartable batches; no stock, price or rights-status mutation."""
    if not 1 <= limit <= 20:
        raise ValueError('Reference mirror batch must contain 1–20 images')
    store = configured_object_storage()
    if store is None:
        raise ObjectStorageError('Private R2 is not configured')
    async with pool.acquire() as connection:
        candidates = [dict(row) for row in await connection.fetch(PENDING_REFERENCE_IMAGES_SQL, limit)]

    result = {'examined':len(candidates),'mirrored':0,'skipped':0,'failed':0,
              'remaining_possible':len(candidates)==limit}
    semaphore = asyncio.Semaphore(4)

    async def process(item: dict) -> str:
        async with semaphore:
            url = str(item['image_url'] or '').strip()
            if not accepted_reference_url(url,item['provider'],item['system_code']):
                reason = 'INVALID_REFERENCE_URL'
            else:
                try:
                    payload = await reference_image_bytes(url,max_bytes=4_000_000,
                                                          timeout_seconds=12.0)
                    if payload is None:
                        reason = 'SOURCE_UNAVAILABLE'
                    else:
                        content = await asyncio.to_thread(optimized_media_bytes,payload,
                            min_dimension=reference_display_min_dimension(url))
                        receipt = await asyncio.to_thread(store.put_verified_media,content)
                        if receipt['verified'] is not True:
                            raise ObjectStorageError('R2 byte verification failed')
                        async with pool.acquire() as connection:
                            async with connection.transaction():
                                await connection.execute(
                                    "select set_config('tcg.request_id',$1,true)",request_id)
                                saved = await connection.fetchval(RECORD_REFERENCE_IMAGE_SQL,
                                    *(item[k] for k in ('provider','system_code','language','provider_id','image_url')),
                                    receipt['key'],receipt['sha256'],receipt['size_bytes'])
                        return 'mirrored' if saved else 'skipped'
                except Exception as exc:
                    logger.warning('Reference artwork mirror failed for exact printing (%s)',
                                   type(exc).__name__)
                    reason = 'IMAGE_OR_STORAGE_FAILURE'
            try:
                await _record_failure(pool,item,request_id=request_id,code=reason)
            except Exception as exc:
                logger.warning('Unable to record a reference image retry (%s)',type(exc).__name__)
            return 'failed'

    if candidates:
        statuses = await asyncio.gather(*(process(item) for item in candidates))
        for status in statuses:
            result[status] += 1
    return result


async def run_reference_mirror_loop(pool: Any, actor) -> None:
    """Resume durable exact-image work in the existing API, with one writer.

    A batch has at most 20 identities and four downloads at once. Content hashes
    and the exact source recheck make a restart safe. Failed sources retain their
    per-image retry backoff; the app keeps the original source until verified.
    """
    actor_pool = ReferenceActorPool(pool, actor)
    while worker_enabled():
        delay=30
        try:
            async with pool.acquire() as lock:
                acquired=await lock.fetchval('select pg_try_advisory_lock($1)',MIRROR_WORKER_LOCK)
                if acquired:
                    try:
                        # R2 holds the bytes, but each image still commits a small
                        # exact-printing receipt in Postgres. Check before any
                        # provider download or object upload, on every batch.
                        capacity=await check_database_capacity(lock)
                        if not capacity.refresh_allowed:
                            logger.warning('CATALOGUE_R2_REFERENCE_MEDIA_DEFERRED %s',
                                           json.dumps(capacity.report(),sort_keys=True))
                            delay=300
                        else:
                            report=await mirror_reference_images(actor_pool,limit=20,
                                request_id='r2-reference-worker-'+str(uuid4()))
                            logger.warning('CATALOGUE_R2_REFERENCE_MEDIA_BATCH %s',
                                           json.dumps({**report,'database_bytes':capacity.database_bytes},sort_keys=True))
                            if report['examined']==0:
                                delay=300
                            elif report['failed']>=max(1,report['examined']//2):
                                delay=60
                            else:
                                delay=2
                    finally:
                        await lock.execute('select pg_advisory_unlock($1)',MIRROR_WORKER_LOCK)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error('CATALOGUE_R2_REFERENCE_MEDIA_WORKER_FAILED type=%s',type(exc).__name__)
            delay=60
        await asyncio.sleep(delay)
