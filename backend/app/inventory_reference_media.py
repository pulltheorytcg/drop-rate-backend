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
select i.id as inventory_id,ma.id,ma.scope,ma.approval_status,ma.source_provider,
 ma.shopify_cdn_url,ma.public_source_url,ma.created_at
from tcg.inventory_items i
join tcg.catalogue_products p on p.id=i.catalogue_id
join tcg.media_assets ma on (
 (ma.scope='INVENTORY_ITEM' and ma.inventory_id=i.id and ma.owner_id=i.owner_id)
 or (ma.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT') and ma.inventory_id is null
   and ma.catalogue_id=i.catalogue_id and ma.approval_status='APPROVED'
   and ma.rights_tier='STOREFRONT_ALLOWED'
   and lower(btrim(coalesce(ma.media_language,'')))=lower(btrim(coalesce(i.language,p.language,'')))
   and lower(btrim(coalesce(ma.media_variant,'')))=lower(btrim(coalesce(p.variant,''))))
)
where i.id=any($1::uuid[]) and ma.side='FRONT' and ma.media_kind='IMAGE'
 and ma.source_status='ACTIVE' and ma.rights_status='VERIFIED'
 and ma.approval_status in ('PENDING','APPROVED') and ma.revoked_at is null
 and coalesce(nullif(btrim(ma.shopify_cdn_url),''),nullif(btrim(ma.public_source_url),'')) is not null
order by i.id,case when ma.scope='INVENTORY_ITEM' then 0 else 1 end,
 case when ma.approval_status='APPROVED' then 0 else 1 end,
 case when nullif(btrim(ma.shopify_cdn_url),'') is not null then 0 else 1 end,
 ma.created_at desc,ma.id
"""


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
    best = {}
    for row in await shared_media_assets(connection, [item['id'] for item in items if item.get('id')]):
        best.setdefault(str(row['inventory_id']), dict(row))
    for item in items:
        asset = best.get(str(item.get('id')))
        url = (asset.get('shopify_cdn_url') or asset.get('public_source_url')) if asset else None
        # Never leave the older endpoint's broader/pending image selection in
        # the response when this shared resolver deliberately rejects it.
        item['image_url'] = url
        item['card_image_url'] = url or item.get('reference_image_url')
        item['card_image_direct_url'] = direct_image_url(url) or direct_image_url(item.get('reference_image_url'))
        item['card_image_cdn_url'] = item['card_image_direct_url']
        item['card_image_approval_status'] = asset.get('approval_status') if asset else None
        item['card_image_scope'] = asset.get('scope') if asset else None
        item['card_image_source_provider'] = asset.get('source_provider') if asset else None
        item['reference_image_status'] = ('COPY_PHOTO' if asset and asset['scope']=='INVENTORY_ITEM'
            else 'AVAILABLE' if asset or item.get('reference_image_url') else 'UNAVAILABLE')
    return items
