"""Rights-gated, content-addressed private R2 mirrors for catalogue artwork.

The database remains authoritative for every approved media record and current
price. R2 only owns reproducible image bytes. No physical scans or private
seller files may enter this mirroring path.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import ImageOps

from .object_storage import ObjectStorageError, configured_object_storage
from .recognition_images import RecognitionImageError, ReferenceImagePayload, _open_image, _reference_http_client

logger = logging.getLogger(__name__)

# Only explicitly approved provider-owned/rights-cleared canonical sources.
# CardTrader listing photos, eBay, Shopify seller photos and customer scans are
# intentionally excluded even if separately approved for storefront display.
MIRROR_PROVIDER_HOSTS = {
    "TCGdex": {"assets.tcgdex.net"},
    "Punk Records": {"en.onepiece-cardgame.com", "www.onepiece-cardgame.com"},
    "Bandai Official": {"www.dbs-cardgame.com"},
    "Bandai One Piece Official": {"en.onepiece-cardgame.com", "www.onepiece-cardgame.com"},
}
MIRROR_PROVIDERS = frozenset(MIRROR_PROVIDER_HOSTS)
MIRROR_HOSTS = frozenset(host for hosts in MIRROR_PROVIDER_HOSTS.values() for host in hosts)

PENDING_MIRRORS_SQL = """
select m.id,m.public_source_url,m.source_provider,m.source_type
from tcg.media_assets m
left join tcg.media_object_mirrors mirror
  on mirror.media_asset_id=m.id and mirror.source_url=m.public_source_url
where m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
  and m.media_kind='IMAGE' and m.side='FRONT'
  and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
  and m.rights_tier='STOREFRONT_ALLOWED'
  and m.source_status='ACTIVE' and m.revoked_at is null
  and m.source_type in ('OFFICIAL_PROVIDER','LICENSED_PROVIDER')
  and m.source_provider=any($1::text[])
  and split_part(split_part(m.public_source_url,'/',3),':',1)=any($3::text[])
  and mirror.id is null
-- Failed source hosts must not starve later approved assets on repeat runs.
-- This queue is presently restricted to a few hundred verified assets.
order by random()
limit $2
"""

RECORD_MIRROR_SQL = """
insert into tcg.media_object_mirrors as mirror
  (media_asset_id,source_url,object_key,content_sha256,size_bytes)
select m.id,m.public_source_url,$3,$4,$5
from tcg.media_assets m
where m.id=$1 and m.public_source_url=$2
  and m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
  and m.media_kind='IMAGE' and m.side='FRONT'
  and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
  and m.rights_tier='STOREFRONT_ALLOWED'
  and m.source_status='ACTIVE' and m.revoked_at is null
  and m.source_type in ('OFFICIAL_PROVIDER','LICENSED_PROVIDER')
  and m.source_provider=any($6::text[])
  and m.source_provider=$7 and m.source_type=$8
on conflict (media_asset_id) do update
  set source_url=excluded.source_url,object_key=excluded.object_key,
      content_sha256=excluded.content_sha256,size_bytes=excluded.size_bytes,
      verified_at=clock_timestamp(),updated_at=clock_timestamp()
  where mirror.source_url is distinct from excluded.source_url
returning id
"""


def approved_source_url(url: str, provider: str, source_type: str) -> bool:
    if provider not in MIRROR_PROVIDERS or source_type not in {'OFFICIAL_PROVIDER', 'LICENSED_PROVIDER'}:
        return False
    try:
        parts = urlsplit(url)
        return (parts.scheme == 'https' and parts.hostname in MIRROR_PROVIDER_HOSTS[provider]
                and parts.port in {None, 443} and parts.username is None
                and parts.password is None and not parts.fragment and bool(parts.path))
    except (TypeError, ValueError):
        return False



async def reference_image_bytes(url: str, *, max_bytes: int = 4_000_000,
                                timeout_seconds: float = 12.0) -> ReferenceImagePayload | None:
    """R2 reproduction never follows a redirect beyond the approved source URL."""
    if (type(max_bytes) is not int or not 1 <= max_bytes <= 4_000_000
            or not 0 < timeout_seconds <= 12
            or not any(approved_source_url(url,p,"LICENSED_PROVIDER") for p in MIRROR_PROVIDERS)):
        return None
    try:
        async with asyncio.timeout(timeout_seconds):
            async with _reference_http_client().stream(
                "GET",url,follow_redirects=False,timeout=httpx.Timeout(timeout_seconds),
                headers={"Accept":"image/webp,image/png,image/jpeg,image/avif"}) as response:
                if response.status_code != 200:
                    return None
                content_type=response.headers.get("content-type","").split(";",1)[0].lower()
                if content_type not in {"image/jpeg","image/png","image/webp","image/avif"}:
                    return None
                length=response.headers.get("content-length")
                if length is not None and (not length.isdigit() or int(length)>max_bytes):
                    return None
                chunks=[]
                size=0
                async for chunk in response.aiter_bytes():
                    size+=len(chunk)
                    if size>max_bytes:
                        return None
                    chunks.append(chunk)
                data=b"".join(chunks)
                if not data:
                    return None
                return ReferenceImagePayload(content_type=content_type,data=data)
    except (httpx.HTTPError,TimeoutError):
        return None


def optimized_media_bytes(payload: ReferenceImagePayload, *, min_dimension: int = 200) -> bytes:
    """Deterministic, EXIF-stripped, bounded WebP; never upload source HTML/SVG."""
    image, _, _ = _open_image(payload.data, min_dimension=min_dimension)
    image = ImageOps.exif_transpose(image)
    image.thumbnail((960, 1344))
    image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
    output = io.BytesIO()
    image.save(output, 'WEBP', quality=84, method=4)
    data = output.getvalue()
    if not data or len(data) > 10_000_000:
        raise RecognitionImageError('Optimized media exceeds the allowed size')
    return data


def with_signed_mirror(row: Any) -> dict:
    """Sign only DB-selected mirrors; keep the provider URL as fallback.

    Reference-only caches are separately gated and never promote a reference
    image into the rights-approved canonical media path.
    """
    item = dict(row)
    key = item.pop('r2_object_key', None)
    reference_key = item.pop('r2_reference_object_key', None)
    approved_enabled = os.getenv('TCG_R2_MEDIA_DELIVERY_ENABLED', 'false').lower() in ('true', '1')
    reference_enabled = os.getenv('TCG_R2_REFERENCE_CACHE_DELIVERY_ENABLED','false').lower() in ('true','1')
    selected = (key if key and approved_enabled else None) or (
        reference_key if reference_key and reference_enabled else None)
    if not selected:
        return item
    try:
        store = configured_object_storage()
        if store is not None:
            item['r2_image_url'] = store.signed_media_url(selected)
    except Exception as exc:
        # An R2 outage or a configuration issue must not break catalogue JSON.
        logger.warning('R2 image signing unavailable; falling back to provider (%s)',type(exc).__name__)
    return item


async def mirror_approved_media(pool: Any, *, limit: int, request_id: str,
                                candidate_ids: list | None = None) -> dict:
    """Idempotent, small HMAC-command batch; no owner or price mutations."""
    if not 1 <= limit <= 5:
        raise ValueError('Mirroring batch must contain between 1 and 5 assets')
    store = configured_object_storage()
    if store is None:
        raise ObjectStorageError('Private object storage is disabled')
    async with pool.acquire() as connection:
        query=PENDING_MIRRORS_SQL
        args=[sorted(MIRROR_PROVIDERS),limit,sorted(MIRROR_HOSTS)]
        if candidate_ids is not None:
            if not 1 <= len(candidate_ids) <= 5:
                raise ValueError("Operator candidate batch must contain 1 to 5 IDs")
            query=query.replace("and mirror.id is null","and mirror.id is null and m.id=any($4::uuid[])")
            args.append(candidate_ids)
        candidates = await connection.fetch(query,*args)
    result = {'examined': len(candidates), 'mirrored': 0, 'skipped': 0, 'failed': 0,
              'remaining_possible': len(candidates) == limit}
    for candidate in candidates:
        url = str(candidate['public_source_url'] or '').strip()
        if not approved_source_url(url, str(candidate['source_provider']), str(candidate['source_type'])):
            result['skipped'] += 1
            continue
        try:
            payload = await reference_image_bytes(url, max_bytes=4_000_000, timeout_seconds=12.0)
            if payload is None:
                result['failed'] += 1
                continue
            image_bytes = await asyncio.to_thread(optimized_media_bytes, payload)
            receipt = await asyncio.to_thread(store.put_verified_media, image_bytes)
            if receipt['verified'] is not True:
                raise ObjectStorageError('Read-back was not verified')
            async with pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute("select set_config('tcg.request_id',$1,true)", request_id)
                    saved = await connection.fetchval(
                        RECORD_MIRROR_SQL, candidate['id'], url, receipt['key'],
                        receipt['sha256'], receipt['size_bytes'], sorted(MIRROR_PROVIDERS),
                        candidate['source_provider'],candidate['source_type'],
                    )
            if saved:
                result['mirrored'] += 1
            else:
                # Source/rights/approval changed during external I/O, or a
                # parallel worker won. Never publish a now-invalid mirror.
                result['skipped'] += 1
        except Exception as exc:
            # Never disclose the source URLs, S3 endpoint or credentials in
            # automation response bodies; a later batch can safely retry.
            logger.warning('R2 approved media mirror failed for asset %s (%s)',
                           str(candidate['id'])[-8:],type(exc).__name__)
            result['failed'] += 1
    return result
