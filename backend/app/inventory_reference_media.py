"""One approved-media selector for both inventory screens and their image route.

Canonical artwork belongs to exact catalogue identity. Ownership is consulted
only for a photograph of the actual physical copy, never for standard artwork.
Pending catalogue images remain in the review tools, not an owner-only default.
"""
from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

# Input IDs come from already-authorized inventory responses. RLS is retained.
# A failed CDN can fall back to the same eligible asset's original URL. Reference
# library artwork is a separate non-publication fallback in the shared route.
MEDIA_SQL = """
select i.id as inventory_id,ma.id,ma.scope,ma.capture_context,ma.approval_status,ma.source_provider,
 ma.source_type,ma.rights_tier,ma.shopify_cdn_url,ma.public_source_url,ma.created_at
from tcg.inventory_items i
join tcg.catalogue_products p on p.id=i.catalogue_id
join tcg.media_assets ma on (
 (ma.scope='INVENTORY_ITEM' and ma.inventory_id=i.id and ma.owner_id=i.owner_id
   and ma.approval_status='APPROVED' and (
     (ma.rights_tier='FIRST_PARTY_CAPTURE'
       and ma.source_type in ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD'))
     -- Private, authenticated owner collection display; never a Shopify/eBay licence.
     or (ma.rights_tier='INTERNAL_REFERENCE_ONLY'
       and ma.source_type='OFFICIAL_PROVIDER'
       and ma.capture_context='GRADED_SLAB'
       and upper(btrim(ma.source_provider))=upper(btrim(i.grading_company))
       and upper(btrim(i.grading_company)) in ('PSA','ACE','BGS','CGC')
       and length(btrim(i.certificate_number))>=6
       and position(btrim(i.certificate_number) in ma.source_reference)>0
       and position(btrim(i.certificate_number) in ma.provider_asset_id)>0)
   ))
 or (ma.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT') and ma.inventory_id is null
   and ma.catalogue_id=i.catalogue_id and ma.approval_status='APPROVED'
   and ma.rights_tier='STOREFRONT_ALLOWED'
   and lower(btrim(coalesce(ma.media_language,'')))=lower(btrim(coalesce(i.language,p.language,'')))
   and lower(btrim(coalesce(ma.media_variant,'')))=lower(btrim(coalesce(p.variant,''))))
)
where i.id=any($1::uuid[]) and ma.side='FRONT' and ma.media_kind='IMAGE'
 and (coalesce(nullif(btrim(i.grading_company),''),nullif(btrim(i.grade),''),nullif(btrim(i.certificate_number),'')) is null
   or (ma.scope='INVENTORY_ITEM' and ma.inventory_id=i.id and ma.owner_id=i.owner_id
       and ma.capture_context='GRADED_SLAB'))
 and ma.source_status='ACTIVE' and ma.rights_status='VERIFIED'
 and ma.approval_status='APPROVED' and ma.revoked_at is null
 and coalesce(nullif(btrim(ma.shopify_cdn_url),''),nullif(btrim(ma.public_source_url),'')) is not null
order by i.id,case when ma.scope='INVENTORY_ITEM' and ma.rights_tier='FIRST_PARTY_CAPTURE' then 0
 when ma.scope='INVENTORY_ITEM' and ma.rights_tier='INTERNAL_REFERENCE_ONLY' then 1 else 2 end,
 case when ma.approval_status='APPROVED' then 0 else 1 end,
 case when nullif(btrim(ma.shopify_cdn_url),'') is not null then 0 else 1 end,
 ma.created_at desc,ma.id
"""


def is_graded_item(item):
    """Incomplete grading details still cannot authorize raw artwork."""
    return any(str(item.get(key) or '').strip() for key in ('grading_company', 'grade', 'certificate_number'))


def direct_image_url(value):
    try:
        url = urlsplit(str(value or ""))
        host = (url.hostname or "").lower()
        if (url.scheme == 'https' and not url.username and not url.password and not url.fragment
                and url.port in (None,443) and (host in {'cdn.shopify.com','assets.tcgdex.net'}
                 or host.endswith('.shopifycdn.com') or host.endswith('.shopifycdn.net'))):
            return str(value).replace("/high.webp", "/low.webp") if host == "assets.tcgdex.net" else str(value)
    except ValueError:
        pass
    return None


async def shared_media_assets(connection, inventory_ids):
    if not inventory_ids:
        return []
    return await connection.fetch(MEDIA_SQL, [UUID(str(value)) for value in inventory_ids])


async def add_shared_inventory_media(connection, items):
    # Owner/certificate eligibility is established in MEDIA_SQL under RLS.
    by_item = {str(item['id']): item for item in items if item.get('id')}
    best = {}
    for row in await shared_media_assets(connection, [item['id'] for item in items if item.get('id')]):
        asset = dict(row)
        identity = str(row['inventory_id'])
        item = by_item.get(identity)
        if item is None:
            continue
        physical = (asset.get('scope') == 'INVENTORY_ITEM'
            and asset.get('rights_tier') == 'FIRST_PARTY_CAPTURE'
            and asset.get('source_type') in ('FOUNDER_UPLOAD', 'CONSIGNOR_UPLOAD')
            and asset.get('approval_status') == 'APPROVED')
        certificate = (is_graded_item(item)
            and asset.get('scope') == 'INVENTORY_ITEM'
            and asset.get('capture_context') == 'GRADED_SLAB'
            and asset.get('rights_tier') == 'INTERNAL_REFERENCE_ONLY'
            and asset.get('source_type') == 'OFFICIAL_PROVIDER'
            and asset.get('approval_status') == 'APPROVED'
            and str(asset.get('source_provider') or '').strip().upper()
                == str(item.get('grading_company') or '').strip().upper()
            and str(item.get('grading_company') or '').strip().upper()
                in {'PSA', 'ACE', 'BGS', 'CGC'})
        if asset.get('scope') == 'INVENTORY_ITEM' and not (physical or certificate):
            continue
        existing = best.get(identity)
        if existing is None or (physical and existing.get('rights_tier') != 'FIRST_PARTY_CAPTURE'):
            best[identity] = asset
    for item in items:
        asset = best.get(str(item.get('id')))
        graded = is_graded_item(item)
        if graded:
            item.pop('reference_image_url', None)
            item.pop('reference_image_path', None)
            if asset and (asset.get('scope') != 'INVENTORY_ITEM' or asset.get('capture_context') != 'GRADED_SLAB'):
                asset = None
        url = (asset.get('shopify_cdn_url') or asset.get('public_source_url')) if asset else None
        item['image_url'] = url
        item['card_image_url'] = url or item.get('reference_image_url')
        item['card_image_direct_url'] = direct_image_url(url) or direct_image_url(item.get('reference_image_url'))
        item['card_image_cdn_url'] = item['card_image_direct_url']
        item['card_image_approval_status'] = asset.get('approval_status') if asset else None
        item['card_image_scope'] = asset.get('scope') if asset else None
        item['card_image_capture_context'] = asset.get('capture_context') if asset else None
        item['card_image_source_provider'] = asset.get('source_provider') if asset else None
        item['card_image_source_type'] = asset.get('source_type') if asset else None
        item['card_image_rights_tier'] = asset.get('rights_tier') if asset else None
        item['reference_image_status'] = (
            'GRADER_CERTIFICATE_REFERENCE' if graded and asset and asset.get('rights_tier') == 'INTERNAL_REFERENCE_ONLY'
            else 'COPY_PHOTO' if asset and asset['scope'] == 'INVENTORY_ITEM'
            else 'AVAILABLE' if asset or item.get('reference_image_url')
            else 'SLAB_PHOTO_REQUIRED' if graded else 'UNAVAILABLE')
    return items
