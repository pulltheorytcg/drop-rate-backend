"""Owner-scoped, authorised Shopify graded-slab media safety audit.

A Shopify DB publication link is NOT proof that a specific physical slab's
front/back images are ready for commercial storefront use. Only verified,
owner/item-scoped FIRST_PARTY_CAPTURE media can close this requirement.

We never use general raw card images or PSA/ACE certificate images that are
licensed as INTERNAL_REFERENCE_ONLY. This emits owner-visible Action Required
items without unpublishing live products or altering founder review overrides.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from .access_control import require_platform_admin
from .action_required import upsert_action_required, resolve_action_required

LIMIT = 100
ACTION_CODE = "SHOPIFY_PUBLISHED_GRADED_PHOTOS_MISSING"
ACTION_CATEGORY = "MEDIA"

# The owner must be active, and the exact physical inventory item must still
# be APPROVED + FOR_SALE + actually recorded PUBLISHED with a non-test Shopify
# link. A generic reference, provider cert, or another owner's photo NEVER
# satisfies the requirements.
PUBLISHED_GRADED_AUDIT_SQL = """
select i.id, i.owner_id, i.version, i.grading_company, i.grade,
       l.shopify_product_gid, l.shopify_variant_gid,
       exists (
         select 1 from tcg.media_assets m
         where m.inventory_id=i.id and m.owner_id=i.owner_id
           and m.scope='INVENTORY_ITEM' and m.capture_context='GRADED_SLAB'
           and m.side='FRONT' and m.media_kind='IMAGE'
           and m.rights_tier='FIRST_PARTY_CAPTURE'
           and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
           and m.source_status='ACTIVE' and m.revoked_at is null
           and m.shopify_file_status='READY' and m.shopify_file_gid is not null
       ) as front_ready,
       exists (
         select 1 from tcg.media_assets m
         where m.inventory_id=i.id and m.owner_id=i.owner_id
           and m.scope='INVENTORY_ITEM' and m.capture_context='GRADED_SLAB'
           and m.side='BACK' and m.media_kind='IMAGE'
           and m.rights_tier='FIRST_PARTY_CAPTURE'
           and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
           and m.source_status='ACTIVE' and m.revoked_at is null
           and m.shopify_file_status='READY' and m.shopify_file_gid is not null
       ) as back_ready
from tcg.inventory_items i
join tcg.owners o on o.id=i.owner_id and o.active
join tcg.shopify_inventory_links l
  on l.inventory_id=i.id and l.owner_id=i.owner_id
 and l.sync_state='PUBLISHED' and l.test_mode=false
where i.status='APPROVED' and i.sale_intent='FOR_SALE'
  and nullif(btrim(i.grading_company),'') is not null
  and nullif(btrim(i.grade),'') is not null
order by i.id limit $1
"""


def dedupe_for(inventory_id: UUID) -> str:
    return f"inventory:{inventory_id}:shopify-published-graded-media-v1"


async def audit_published_graded_media(connection, *, actor_user_id: UUID,
                                        limit: int = LIMIT) -> dict[str, Any]:
    """Audit the source of truth without changing a single Shopify listing.

    Called by the existing hourly authorised Shopify maintenance pass. An
    incomplete inventory receives an idempotent owner-scoped exception; an
    existing exception is resolved only after both exact-copy image proofs are
    present. Pre-existing founder overrides are NEVER edited.
    """
    if type(actor_user_id) is not UUID or type(limit) is not int or not 1<=limit<=LIMIT:
        raise ValueError("A verified actor and bounded graded-photo audit are required")
    await require_platform_admin(connection)
    rows = [dict(row) for row in await connection.fetch(PUBLISHED_GRADED_AUDIT_SQL,limit+1)]
    if len(rows)>limit:
        raise ValueError("Graded-photo audit limit exceeded; no partial owner decisions")
    report = {"owner_scope":"CURRENT_MAINTENANCE_ACTOR_RLS_ONLY",
              "graded_published_checked":len(rows), "ready":0, "missing":0,
              "new_or_reopened":0, "existing_open":0, "resolved":0,
              "shopify_publications_changed":0, "ownership_changed":0}
    for item in rows:
        inv, owner=UUID(str(item["id"])),UUID(str(item["owner_id"]))
        if (not str(item["shopify_product_gid"]).startswith("gid://shopify/Product/")
                or not str(item["shopify_variant_gid"]).startswith("gid://shopify/ProductVariant/")):
            raise ValueError("Published graded-item link has no verified Shopify IDs")
        key=dedupe_for(inv)
        found=await connection.fetchrow(
            "select status from tcg.action_required_items where owner_id=$1 and dedupe_key=$2",
            owner,key,
        )
        previous=found["status"] if found else None
        front=bool(item["front_ready"]);back=bool(item["back_ready"])
        if front and back:
            report["ready"]+=1
            if previous=="OPEN":
                await resolve_action_required(
                    connection,owner_id=owner,dedupe_key=key,
                    actor_user_id=actor_user_id,status="RESOLVED",
                )
                report["resolved"]+=1
            continue
        report["missing"]+=1
        if previous=="OPEN":
            report["existing_open"]+=1
            continue
        missing_sides=[side for side,ok in (("FRONT",front),("BACK",back)) if not ok]
        await upsert_action_required(
            connection,owner_id=owner,category=ACTION_CATEGORY,code=ACTION_CODE,
            severity="HIGH",entity_type="INVENTORY_ITEM",entity_id=inv,
            dedupe_key=key,
            title="Published graded slab needs approved physical photographs",
            detail=(
                "This inventory item has a published Shopify link but is missing "
                "Shopify-ready, rights-verified first-party photography of the "
                "exact graded slab. Official PSA/ACE certification photos held "
                "for internal reference and raw-card artwork are not substitute "
                "storefront evidence."
            ),
            recommended_action=(
                "Photograph the physical slab front and back, upload both against "
                "this Inventory ID, confirm first-party rights and have the exact "
                "physical-item photos approved before relying on listing artwork."
            ),
            metadata={
                "audit_contract":"DR100_PUBLISHED_GRADED_MEDIA_V1",
                "inventory_version":int(item["version"]),
                "grading_company":str(item["grading_company"]),
                "grade":str(item["grade"]),
                "missing_sides":missing_sides,
                "shopify_product_gid":str(item["shopify_product_gid"]),
                "shopify_variant_gid":str(item["shopify_variant_gid"]),
                "no_automatic_delisting":True,
                "original_founder_reviews_untouched":True,
            },
        )
        report["new_or_reopened"]+=1
    return report
