"""Bounded, READ-ONLY actual R2-byte audit for Tier 1 Shopify/approved items.

Runs on the existing Railway/R2 credentials only after manual approval. No
Shopify API, provider fetch, SQL mutation, S3 PUT/DELETE, or D1 access.
The output has counts + at most 20 inventory codes, never R2 keys or secrets.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
from collections import Counter
from datetime import datetime, timezone

import asyncpg
from PIL import Image, UnidentifiedImageError

from app.object_storage import ObjectStorageConfig, S3ObjectStorage

MAX_ITEMS = 505
MIN_DIMENSION = 350

# Data authority is always PostgreSQL. Read-only transaction ends before R2
# byte verification (no DB locks across network I/O).
TIER1_SQL = """
select i.inventory_code,p.game,p.product_type,p.language,p.variant,
 i.grading_company,selected.asset_id,selected.media_language,
 selected.media_variant,selected.rights_status,selected.approval_status,
 selected.object_key,selected.content_sha256,selected.size_bytes
from tcg.inventory_items i
join tcg.catalogue_products p on p.id=i.catalogue_id
left join lateral (
 select a.id asset_id,a.media_language,a.media_variant,a.rights_status,
  a.approval_status,mm.object_key,mm.content_sha256,mm.size_bytes
 from tcg.media_assets a
 left join lateral (
  select object_key,content_sha256,size_bytes
  from tcg.media_object_mirrors mm
  where mm.media_asset_id=a.id
  order by mm.verified_at desc nulls last,mm.id desc limit 1
 ) mm on true
 where a.approval_status='APPROVED'
 and (
  (i.grading_company is not null and a.inventory_id=i.id and a.scope='INVENTORY_ITEM')
  or
  (i.grading_company is null and (
    (a.inventory_id=i.id and a.scope='INVENTORY_ITEM')
    or
    (a.catalogue_id=i.catalogue_id and a.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT'))
  ))
 )
 order by (a.inventory_id=i.id) desc, (mm.object_key is not null) desc, a.created_at desc
 limit 1
) selected on true
where p.product_type in ('CARD','SEALED')
and (i.status='APPROVED' or exists (
 select 1 from tcg.shopify_inventory_links l where l.inventory_id=i.id and l.sync_state='PUBLISHED'
))
and i.inventory_code>$1
order by i.inventory_code
limit $2
"""


def pixel_dimensions(data: bytes) -> tuple[int, int]:
    if not data:
        raise ValueError("Empty R2 image bytes")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "WEBP" or getattr(image, "is_animated", False):
                raise ValueError("R2 image is not static WebP")
            width, height = image.size
            if width * height > 20_000_000:
                raise ValueError("R2 image exceeds bounded pixel budget")
            image.load()
            return width, height
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("R2 image failed decoding") from exc


def classify_image(row: dict, storage: S3ObjectStorage) -> str:
    """Do not accept raw reference artwork as a graded physical slab image."""
    if not row.get("asset_id"):
        return "NO_APPROVED_SLAB_ASSET" if row.get("grading_company") else "NO_APPROVED_MEDIA_ASSET"
    if row.get("rights_status") != "VERIFIED":
        return "MEDIA_RIGHTS_NOT_VERIFIED"
    media_language = (row.get("media_language") or "").strip().casefold()
    if media_language and media_language not in {"unknown", "not applicable"}:
        if media_language != (row.get("language") or "").strip().casefold():
            return "MEDIA_LANGUAGE_MISMATCH"
    media_variant = (row.get("media_variant") or "").strip().casefold()
    if media_variant and media_variant not in {"unknown", "not applicable"}:
        if media_variant != (row.get("variant") or "").strip().casefold():
            return "MEDIA_VARIANT_MISMATCH"
    if not row.get("object_key"):
        return "NO_R2_MIRROR_RECORD"
    if not row.get("content_sha256") or not isinstance(row.get("size_bytes"), int) or row["size_bytes"] <= 0:
        return "INVALID_R2_MIRROR_METADATA"
    try:
        # Enforces stable private-media key, full SHA-256 and exact remote bytes.
        data = storage.read_verified_media(
            row["object_key"],
            expected_sha256=row["content_sha256"],
            expected_size=row["size_bytes"],
        )
    except Exception:
        # Separate missing and byte-corruption requires a read-only S3 HEAD on
        # the bounded key. We do not expose provider bodies or credentials.
        try:
            response = storage.client.head_object(
                Bucket=storage.config.bucket, Key=row["object_key"],
            )
        except Exception:
            return "R2_MISSING_OR_HEAD_FAILED"
        if response.get("ContentLength") != row["size_bytes"]:
            return "R2_SIZE_MISMATCH"
        return "R2_SHA_OR_WEBP_VERIFICATION_FAILED"
    try:
        w, h = pixel_dimensions(data)
    except ValueError:
        return "R2_IMAGE_DECODE_FAILED"
    if min(w, h) < MIN_DIMENSION:
        return "R2_IMAGE_LOW_RESOLUTION"
    # Byte/pixel checks cannot prove visual variant or that an image is not an
    # original-looking placeholder; those remain explicit manual-review gates.
    return "R2_BYTES_AND_DIMENSIONS_VERIFIED_VISUAL_UNREVIEWED"


def summarise(rows: list[dict], storage: S3ObjectStorage) -> dict:
    counts = Counter()
    groups: dict[str, Counter] = {}
    examples = []
    used_keys: dict[str, set[str]] = {}
    for row in rows:
        status = classify_image(row, storage)
        game = str(row["game"])
        counts[status] += 1
        groups.setdefault(game, Counter())[status] += 1
        if row.get("object_key"):
            used_keys.setdefault(row["object_key"], set()).add(str(row.get("inventory_code")))
        if status != "R2_BYTES_AND_DIMENSIONS_VERIFIED_VISUAL_UNREVIEWED" and len(examples) < 20:
            examples.append({"inventory_code": row.get("inventory_code"), "game": game, "reason": status})
    return {
        "scope": "TIER1_CARD_AND_SEALED_READ_ONLY",
        "examined": len(rows),
        "status_counts": dict(sorted(counts.items())),
        "by_game": {game: dict(sorted(count.items())) for game, count in sorted(groups.items())},
        "physical_items_sharing_a_mirror_key": sum(len(ids) for ids in used_keys.values() if len(ids)>1),
        "unique_db_mirror_keys_examined": len(used_keys),
        "sample_failures": examples,
        "full_visual_identity_verified": False,
        "no_sql_or_r2_writes": True,
    }


async def load_rows(dsn: str, *, after: str, limit: int) -> list[dict]:
    conn = await asyncpg.connect(dsn=dsn, timeout=10)
    try:
        async with conn.transaction(readonly=True, isolation="repeatable_read"):
            return [dict(row) for row in await conn.fetch(TIER1_SQL, after, limit, timeout=30)]
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--after-inventory-code", default="")
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_ITEMS:
        parser.error("limit must be between 1 and 505")
    if len(args.after_inventory_code) > 100 or any(ch in args.after_inventory_code for ch in "\r\n\0"):
        parser.error("invalid continuation cursor")
    dsn = os.getenv("TCG_DATABASE_URL")
    if not dsn:
        parser.error("existing PostgreSQL connection is not configured")
    cfg = ObjectStorageConfig.from_env()
    if cfg is None:
        parser.error("existing R2 read configuration is not enabled")
    rows = asyncio.run(load_rows(dsn, after=args.after_inventory_code, limit=args.limit))
    result = summarise(rows, S3ObjectStorage(cfg))
    result.update(
        completed_at=datetime.now(timezone.utc).isoformat(),
        next_cursor=rows[-1]["inventory_code"] if len(rows)==args.limit else None,
        more_available=len(rows)==args.limit,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if not result["more_available"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
