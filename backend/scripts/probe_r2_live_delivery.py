"""Read-only production proof of catalogue-selected private R2 image delivery.

Prints booleans/counts only. Never prints signed URLs, object keys or credentials.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from uuid import UUID

import httpx
from app.access_control import require_platform_admin
from app.catalogue_browser import SOURCE_CTE,product_query,with_artwork_path
from app.db import create_pool,user_connection
from app.r2_media import with_signed_mirror
from app.settings import get_settings

async def main():
    enabled=os.getenv("TCG_R2_MEDIA_DELIVERY_ENABLED","false").lower() in ("true","1")
    if not enabled:
        raise RuntimeError("APPROVED_DELIVERY_DISABLED")
    settings=get_settings()
    actor=UUID(settings.catalogue_maintenance_actor_user_id)
    pool=await create_pool(settings)
    try:
        async with user_connection(pool,actor,"r2-delivery-readonly-proof") as connection:
            access=await require_platform_admin(connection)
            candidates=await connection.fetch("""
              select m.catalogue_id,max(mirror.verified_at) as newest
              from tcg.media_assets m join tcg.media_object_mirrors mirror
                on mirror.media_asset_id=m.id and mirror.source_url=m.public_source_url
              where m.catalogue_id is not null
                and m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')
                and m.side='FRONT' and m.media_kind='IMAGE'
                and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
                and m.rights_tier='STOREFRONT_ALLOWED' and m.source_status='ACTIVE'
                and m.revoked_at is null
              group by m.catalogue_id order by newest desc limit 10""")
            if not candidates:
                raise RuntimeError("NO_ELIGIBLE_MIRROR")
            keys=await connection.fetch(SOURCE_CTE+
                " select key from entries where catalogue_id=any($2::uuid[]) limit 20",
                access["owner_id"],[r["catalogue_id"] for r in candidates])
            if not keys:
                raise RuntimeError("MIRROR_NOT_IN_LIVE_CATALOGUE")
            query,params=product_query(owner_id=access["owner_id"],
                keys=[r["key"] for r in keys],limit=20)
            rows=await connection.fetch(query,*params)
            selected=next((dict(r) for r in rows if r.get("r2_object_key")),None)
            if selected is None:
                raise RuntimeError("APP_QUERY_DID_NOT_JOIN_APPROVED_MIRROR")
            receipt=await connection.fetchrow("""
                select content_sha256,size_bytes from tcg.media_object_mirrors
                where object_key=$1 limit 1""",selected["r2_object_key"])
            if not receipt or not 1<=receipt["size_bytes"]<=10_000_000:
                raise RuntimeError("MIRROR_RECEIPT_INVALID")
        # Signing and actual network delivery happen after the DB lease closes.
        item=with_artwork_path(with_signed_mirror(selected))
        url=item.get("r2_image_url")
        if (not url or "r2_object_key" in item or "r2_reference_object_key" in item
                or not (item.get("display_image_url") or item.get("fallback_image_url") or item.get("image_url"))):
            raise RuntimeError("APP_RESPONSE_DELIVERY_OR_FALLBACK_MISSING")
        digest=hashlib.sha256()
        size=0
        async with httpx.AsyncClient(follow_redirects=False) as client:
            async with asyncio.timeout(20):
                async with client.stream("GET",url,timeout=15) as response:
                    if response.status_code!=200 or response.headers.get("content-type","").split(";",1)[0]!="image/webp":
                        raise RuntimeError("SIGNED_GET_NOT_WEBP_200")
                    async for chunk in response.aiter_bytes():
                        size+=len(chunk)
                        if size>10_000_000:
                            raise RuntimeError("SIGNED_GET_TOO_LARGE")
                        digest.update(chunk)
        if digest.hexdigest()!=receipt["content_sha256"] or size!=receipt["size_bytes"]:
            raise RuntimeError("SIGNED_GET_HASH_MISMATCH")
        print("R2_LIVE_DELIVERY_PROOF "+json.dumps({
            "status":"VERIFIED","read_only":True,"writes":0,
            "approved_delivery_enabled":enabled,"catalogue_product_query_used":True,
            "live_catalogue_rows_checked":len(rows),"raw_object_keys_removed":True,
            "source_fallback_present":True,"signed_get_status":200,
            "content_type":"image/webp","size_bytes":size,"sha256_matches_receipt":True
        },sort_keys=True),flush=True)
    finally:
        await pool.close()

if __name__=="__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print("R2_LIVE_DELIVERY_PROOF "+json.dumps({
            "status":"UNVERIFIED","error_type":type(exc).__name__
        },sort_keys=True),flush=True)
        raise SystemExit(2)
