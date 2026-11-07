"""Owner-scoped inventory photo *migration* action queue.

The existing R2 canonical catalogue mirror is NOT a photograph of the actual
physical inventory copy. This read-only endpoint identifies each non-sold
owner-held stock item missing first-party capture, media approval or its own
R2-mirror metadata. It deliberately cannot assert actual R2 byte integrity
from SQL: that requires separate private byte-readback before storefront use.

Never select another owner's images, never substitute raw artwork for slabs,
never publish, mutate, settle, import or expose public object keys.
"""
from __future__ import annotations

from uuid import UUID

SQL = """
WITH held AS (
 SELECT i.id, i.inventory_code, i.version, i.status,
        i.updated_at,
        (nullif(btrim(i.grading_company),'') IS NOT NULL OR
         nullif(btrim(i.grade),'') IS NOT NULL OR
         nullif(btrim(i.certificate_number),'') IS NOT NULL) AS graded,
        (i.seal_status='SEALED') AS sealed
 FROM tcg.inventory_items i
 WHERE i.owner_id=$1
   AND i.status IN ('DRAFT','INSPECTION','APPROVED','RESERVED')
),
evidence AS (
 SELECT h.*,
   EXISTS (
     SELECT 1 FROM tcg.media_assets m
     WHERE m.inventory_id=h.id AND m.owner_id=$1
       AND m.scope='INVENTORY_ITEM' AND m.media_kind='IMAGE' AND m.side='FRONT'
       AND m.source_type IN ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD')
       AND m.rights_tier='FIRST_PARTY_CAPTURE' AND m.revoked_at IS NULL
       AND (NOT h.graded OR m.capture_context='GRADED_SLAB')
   ) AS has_capture,
   EXISTS (
     SELECT 1 FROM tcg.media_assets m
     WHERE m.inventory_id=h.id AND m.owner_id=$1
       AND m.scope='INVENTORY_ITEM' AND m.media_kind='IMAGE' AND m.side='FRONT'
       AND m.source_type IN ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD')
       AND m.rights_tier='FIRST_PARTY_CAPTURE'
       AND m.approval_status='APPROVED' AND m.rights_status='VERIFIED'
       AND m.source_status='ACTIVE' AND m.revoked_at IS NULL
       AND (NOT h.graded OR m.capture_context='GRADED_SLAB')
   ) AS has_approved_capture,
   EXISTS (
     SELECT 1 FROM tcg.media_assets m
     JOIN tcg.media_object_mirrors mm ON mm.media_asset_id=m.id
     WHERE m.inventory_id=h.id AND m.owner_id=$1
       AND m.scope='INVENTORY_ITEM' AND m.media_kind='IMAGE' AND m.side='FRONT'
       AND m.source_type IN ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD')
       AND m.rights_tier='FIRST_PARTY_CAPTURE'
       AND m.approval_status='APPROVED' AND m.rights_status='VERIFIED'
       AND m.source_status='ACTIVE' AND m.revoked_at IS NULL
       AND (NOT h.graded OR m.capture_context='GRADED_SLAB')
       AND mm.content_sha256 ~ '^[0-9a-f]{64}$'
       AND mm.object_key = concat('drop-rate/private-media/',mm.content_sha256,'.webp')
       AND mm.size_bytes BETWEEN 1 AND 10000000
       AND (m.content_sha256 IS NULL OR m.content_sha256=mm.content_sha256)
   ) AS has_r2_mirror_index
 FROM held h
),
actioned AS (
 SELECT e.*,
 CASE WHEN NOT has_capture AND graded THEN 'CAPTURE_GRADED_SLAB'
      WHEN NOT has_capture AND sealed THEN 'CAPTURE_SEALED_COPY'
      WHEN NOT has_capture THEN 'CAPTURE_PHYSICAL_COPY'
      WHEN NOT has_approved_capture THEN 'REVIEW_CAPTURE'
      WHEN NOT has_r2_mirror_index THEN 'MIRROR_FIRST_PARTY_TO_R2'
      ELSE 'VERIFY_R2_COPY_BYTES'
 END AS action_required
 FROM evidence e
)
SELECT id, inventory_code, version, status, graded, sealed,
       has_capture, has_approved_capture, has_r2_mirror_index, action_required,
       count(*) OVER ()::int AS owner_held_total,
       count(*) FILTER (WHERE graded) OVER ()::int AS owner_graded_total,
       count(*) FILTER (WHERE NOT has_capture) OVER ()::int AS missing_first_party_total,
       count(*) FILTER (WHERE has_capture AND NOT has_r2_mirror_index) OVER ()::int
         AS captured_not_r2_total
FROM actioned
ORDER BY CASE action_required
   WHEN 'CAPTURE_GRADED_SLAB' THEN 0
   WHEN 'REVIEW_CAPTURE' THEN 1
   WHEN 'CAPTURE_SEALED_COPY' THEN 2
   WHEN 'CAPTURE_PHYSICAL_COPY' THEN 3
   WHEN 'MIRROR_FIRST_PARTY_TO_R2' THEN 4
   ELSE 5 END,
   updated_at DESC, id
LIMIT $2 OFFSET $3
"""


async def photo_action_queue(connection, owner_id:UUID, *,limit:int=50,offset:int=0) -> dict:
    """Read only within caller-established RLS transaction and owner grant."""
    if (not isinstance(owner_id,UUID) or type(limit) is not int
            or not 1<=limit<=100 or type(offset) is not int or offset<0):
        raise ValueError("Invalid owner-scoped photo queue request")
    rows=await connection.fetch(SQL,owner_id,limit,offset)
    first=dict(rows[0]) if rows else None
    items=[]
    for row in rows:
        obj=dict(row)
        items.append({k:obj[k] for k in (
            "id","inventory_code","version","status","graded","sealed",
            "has_capture","has_approved_capture","has_r2_mirror_index",
            "action_required"
        )})
    return {
        "status":"PRIVATE_OWNER_PHOTO_REVIEW_ONLY",
        "owner_held_total":int(first["owner_held_total"]) if first else 0,
        "owner_graded_total":int(first["owner_graded_total"]) if first else 0,
        "missing_first_party_total":int(first["missing_first_party_total"]) if first else 0,
        "captured_not_r2_total":int(first["captured_not_r2_total"]) if first else 0,
        "items":items,
        "limit":limit,"offset":offset,
        "actual_r2_bytes_verified_by_this_endpoint":False,
        "published_to_shopify":False,
        "source_table_writes":0,
    }
