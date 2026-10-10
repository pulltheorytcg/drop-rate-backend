"""Seller inventory controls. Physical approval and storefront media stay gated."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .catalogue_artwork import reference_thumbnail
from .recognition_games import SYSTEM_BY_GAME
from .channel_sync_wakeup import request_shopify_sync
from .db import user_connection
from .inventory_sale_intent import change_inventory_sale_intent
from .recognition_images import _trusted_reference_url
from .schemas import InventorySaleIntentChange
from .settings import get_settings
from .seller_inventory_policy import sealed_seller_candidate

router = APIRouter(prefix="/api/v1/owner/inventory", tags=["owner-inventory"])
ACTIVE = {"DRAFT", "INSPECTION", "APPROVED"}
GAME_CASE = "case r.system_code " + " ".join(
    "when '" + system + "' then '" + game.replace("'", "''") + "'"
    for game, system in SYSTEM_BY_GAME.items()) + " else r.system_code end"

# A source must identify the exact printing, not merely share a card number or
# set. These images are private collection references, never publication media.
REFERENCE_ART_SQL = f"""
select p.id,array_agg(distinct art.url) filter(where nullif(btrim(art.url),'') is not null) as urls
from tcg.catalogue_products p
left join lateral (
 select r.image_url as url from tcg.reference_cards r
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 where p.product_type='CARD' and p.game=({GAME_CASE}) and r.language=p.language
   and p.variant=r.provider_id and p.name=r.name and p.set_name=s.name
   and p.card_number=r.card_number and p.rarity=coalesce(nullif(r.rarity,''),'Unknown')
 union
 select r.image_url from tcg.provider_catalogue_mappings m
 join tcg.reference_cards r on m.source_provider=r.provider and m.system_code=r.system_code
   and m.provider_language=r.language and m.provider_id=r.provider_id
 where m.catalogue_id=p.id and p.product_type='CARD' and p.game=({GAME_CASE}) and r.language=p.language
   and m.provider_entity_type='CARD_PRINTING' and m.provider_variant_key='' and m.match_status='VERIFIED'
 union
 select r.image_url from tcg.reference_sealed_products r
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 where p.product_type='SEALED' and p.game=({GAME_CASE}) and p.variant=r.provider_id and p.name=r.name and p.set_name=s.name
   and (p.language=r.language or r.language='Unknown') and p.rarity=r.product_type
 union
 select pr.attributes->>'inventory_reference_image_url' from tcg.catalogue_product_profiles pr
 where pr.catalogue_id=p.id and pr.identity_status='VERIFIED'
   and pr.attributes->'inventory_reference_identity'=jsonb_build_object(
     'name',p.name,'set_name',p.set_name,'variant',p.variant,'language',p.language,'product_type',p.product_type)
) art on true
where p.id=any($1::uuid[]) group by p.id
"""


async def add_reference_artwork(connection, items):
    ids = list({item["catalogue_id"] for item in items if item.get("catalogue_id")})
    if not ids:
        return items
    rows = await connection.fetch(REFERENCE_ART_SQL, ids)
    by_id = {row["id"]: row["urls"] or [] for row in rows}
    for item in items:
        urls = by_id.get(item["catalogue_id"], [])
        # Conflicting references remain unavailable; do not guess the picture.
        if len(urls) == 1 and _trusted_reference_url(urls[0]):
            item["reference_image_url"] = urls[0]
            item["reference_image_path"] = f"/api/v1/owner/inventory/{item['id']}/reference-image"
    return items


DETAIL_SQL = """
select i.id,i.inventory_code,i.catalogue_id,i.version,i.status,i.sale_intent,
 i.condition,i.seal_status,i.grading_company,i.grade,i.certificate_number,
 o.owner_type,p.language as catalogue_language,pr.identity_status as catalogue_identity_status,
 coalesce(i.language,p.language) as language,i.store_price_minor,i.market_value_minor,
 i.recommended_retail_minor,i.pricing_updated_at,p.product_type,p.game,p.name,p.set_name,
 p.card_number,p.variant,p.rarity,
 i.identity_confirmed as identity_ready,
 (i.acquisition_cost_minor is not null and i.storage_location_id is not null) as intake_ready,
 (select ps.evidence->>'method' from tcg.pricing_snapshots ps
   where ps.id=i.latest_pricing_snapshot_id and ps.owner_id=i.owner_id
     and ps.inventory_id=i.id and ps.catalogue_id=i.catalogue_id) as pricing_method,
 (select l.sync_state from tcg.shopify_inventory_links l
   where l.inventory_id=i.id and l.owner_id=i.owner_id and not l.test_mode
   order by l.last_synced_at desc limit 1) as shopify_state,
 (select coalesce(nullif(m.shopify_cdn_url,''),m.public_source_url) from tcg.media_assets m
   where ((m.scope='INVENTORY_ITEM' and m.inventory_id=i.id and m.owner_id=i.owner_id
           and m.rights_tier='FIRST_PARTY_CAPTURE')
       or (m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT') and m.inventory_id is null
           and m.catalogue_id=i.catalogue_id and m.rights_tier='STOREFRONT_ALLOWED'
           and lower(btrim(coalesce(m.media_language,'')))=lower(btrim(coalesce(i.language,p.language,'')))
           and lower(btrim(coalesce(m.media_variant,'')))=lower(btrim(coalesce(p.variant,'')))))
     and m.side='FRONT' and m.media_kind='IMAGE' and m.approval_status='APPROVED'
     and m.rights_status='VERIFIED' and m.source_status='ACTIVE' and m.revoked_at is null
   order by (m.inventory_id=i.id) desc,m.approved_at desc nulls last,m.id limit 1) as image_url
from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
join tcg.owners o on o.id=i.owner_id
left join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
where i.id=$1 and i.owner_id=$2
"""

COPIES_SQL = """
select c.id,c.inventory_code,c.status,c.version,c.sale_intent
from tcg.inventory_items i join tcg.inventory_items c
 on c.owner_id=i.owner_id and c.catalogue_id=i.catalogue_id
 and c.language is not distinct from i.language and c.condition is not distinct from i.condition
 and c.seal_status is not distinct from i.seal_status
 and c.grading_company is not distinct from i.grading_company and c.grade is not distinct from i.grade
 and (i.grading_company is null or c.id=i.id)
where i.id=$1 and i.owner_id=$2 and c.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
order by c.created_at,c.id
"""


def approval_blockers(item):
    missing = []
    if not item.get("identity_ready") and not sealed_seller_candidate(item):
        missing.append("Drop Rate identity verification")
    if not item.get("intake_ready") and not sealed_seller_candidate(item):
        missing.append("Drop Rate intake review")
    if not item.get("language"):
        missing.append("Product language")
    if not item.get("store_price_minor") or item["store_price_minor"] < 100:
        missing.append("A selling price of at least £1")
    if item["product_type"] == "CARD":
        if not ((item.get("grading_company") and item.get("grade")) or item.get("condition")):
            missing.append("Card condition or grade")
    elif not item.get("seal_status"):
        missing.append("Seal status")
    if not item.get("image_url"):
        missing.append("Catalogue image is being prepared" if sealed_seller_candidate(item) else "An approved listing photo")
    return missing


@router.get("/{inventory_id}")
async def details(inventory_id: UUID, request: Request,
                  user: Annotated[AuthenticatedUser, Depends(require_user)],
                  access: Annotated[dict, Depends(require_owner_portal_request)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        row = await connection.fetchrow(DETAIL_SQL, inventory_id, access["owner_id"])
        if row is None:
            raise HTTPException(404, "Inventory item not found")
        item = dict(row)
        await add_reference_artwork(connection, [item])
        copies = await connection.fetch(COPIES_SQL, inventory_id, access["owner_id"])
    item["approval_blockers"] = approval_blockers(item)
    item["seller_approval_available"] = sealed_seller_candidate(item)
    for key in ("owner_type", "catalogue_language", "catalogue_identity_status"):
        item.pop(key, None)
    item.pop("identity_ready", None)
    item.pop("intake_ready", None)
    settings = get_settings()
    item["shopify_sync_enabled"] = settings.shopify_seller_sync_enabled and settings.shopify_publish_enabled
    return jsonable_encoder({"item": item, "copies": [dict(row) for row in copies]})


@router.get("/{inventory_id}/reference-image")
async def reference_image(inventory_id: UUID, request: Request,
                          user: Annotated[AuthenticatedUser, Depends(require_user)],
                          access: Annotated[dict, Depends(require_owner_portal_request)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        row = await connection.fetchrow("select id,catalogue_id from tcg.inventory_items where id=$1 and owner_id=$2",
                                        inventory_id, access["owner_id"])
        if row is None:
            raise HTTPException(404, "Inventory item not found")
        item = dict(row)
        await add_reference_artwork(connection, [item])
    if not item.get("reference_image_url"):
        raise HTTPException(404, "No exact reference image is available")
    payload = await reference_thumbnail(item["reference_image_url"])
    if payload is None:
        raise HTTPException(502, "Reference image is temporarily unavailable")
    return Response(payload.data, media_type=payload.content_type,
                    headers={"Cache-Control": "private, no-store", "X-Drop-Rate-Image": "REFERENCE_ONLY"})


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, strict=True)


class SellingPrice(VersionRequest):
    store_price_minor: int = Field(ge=100, le=100_000_000, strict=True)


class AddCopy(VersionRequest):
    confirmed: Literal[True]


async def locked_item(connection, inventory_id, owner_id):
    row = await connection.fetchrow("select * from tcg.inventory_items where id=$1 and owner_id=$2 for update",
                                    inventory_id, owner_id)
    if row is None:
        raise HTTPException(404, "Inventory item not found")
    return dict(row)


def require_editable(item, version):
    if item["version"] != version:
        raise HTTPException(409, "This copy changed. Refresh its details and try again.")
    if item["status"] not in ACTIVE:
        raise HTTPException(409, "Sold, reserved or withdrawn copies cannot be changed here.")


async def save_selling_price(inventory_id, payload, request, user, access, *, approval_request):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await locked_item(connection, inventory_id, access["owner_id"])
        require_editable(item, payload.version)
        if approval_request:
            context = await connection.fetchrow(DETAIL_SQL, inventory_id, access["owner_id"])
            if context and sealed_seller_candidate(dict(context)):
                if not context["image_url"]:
                    raise HTTPException(422, "The exact catalogue image is being prepared. Your own photo is not required.")
                approval = {"owner_id": str(access["owner_id"]), "catalogue_id": str(item["catalogue_id"]),
                            "actor_user_id": str(user.user_id), "language": context["language"],
                            "name": context["name"], "set_name": context["set_name"], "variant": context["variant"]}
                row = await connection.fetchrow("""update tcg.inventory_items set
                    store_price_minor=$4,status='APPROVED',sale_intent='FOR_SALE',identity_confirmed=true,
                    source_record=coalesce(source_record,'{}'::jsonb) || jsonb_build_object('seller_held_approval',$5::jsonb),
                    version=version+1,updated_at=clock_timestamp()
                    where id=$1 and owner_id=$2 and version=$3
                    returning id,inventory_code,status,sale_intent,version,store_price_minor
                    """, inventory_id, access["owner_id"], payload.version,payload.store_price_minor,json.dumps(approval))
                if row is None:
                    raise HTTPException(409, "Inventory changed. Refresh and try again.")
                result = jsonable_encoder({"item": dict(row), "message": "Approved for Shopify using the catalogue image. Your stock stays with you; automatic sync is queued."})
            else:
                result = None
        else:
            result = None
        if result is None:
            result = await _save_review_price(connection, inventory_id, payload, item, access, approval_request)
    request_shopify_sync(request)
    return result


async def _save_review_price(connection, inventory_id, payload, item, access, approval_request):
    target = "INSPECTION" if approval_request and item["status"] == "DRAFT" else item["status"]
    row = await connection.fetchrow("""update tcg.inventory_items
        set store_price_minor=$4,status=$5,sale_intent=$6,version=version+1,updated_at=clock_timestamp()
        where id=$1 and owner_id=$2 and version=$3 returning id,inventory_code,status,sale_intent,version,store_price_minor
        """, inventory_id, access["owner_id"], payload.version, payload.store_price_minor, target,
        "FOR_SALE" if approval_request else item["sale_intent"])
    if row is None:
        raise HTTPException(409, "Inventory changed. Refresh and try again.")
    return jsonable_encoder({"item": dict(row), "message":
    "Your selling approval is saved. Drop Rate review is required before publication."
    if approval_request and target != "APPROVED" else "Selling price saved. Approved For Sale stock will sync automatically."})

@router.patch("/{inventory_id}/selling-price")
async def selling_price(inventory_id: UUID, payload: SellingPrice, request: Request,
                        user: Annotated[AuthenticatedUser, Depends(require_user)],
                        access: Annotated[dict, Depends(require_owner_portal_request)]):
    return await save_selling_price(inventory_id, payload, request, user, access, approval_request=False)


@router.post("/{inventory_id}/approval-request")
async def approval_request(inventory_id: UUID, payload: SellingPrice, request: Request,
                           user: Annotated[AuthenticatedUser, Depends(require_user)],
                           access: Annotated[dict, Depends(require_owner_portal_request)]):
    return await save_selling_price(inventory_id, payload, request, user, access, approval_request=True)


@router.post("/{inventory_id}/copies", status_code=201)
async def add_copy(inventory_id: UUID, payload: AddCopy, request: Request,
                   user: Annotated[AuthenticatedUser, Depends(require_user)],
                   access: Annotated[dict, Depends(require_owner_portal_request)],
                   idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")]):
    digest = hashlib.sha256(f"seller-copy:{inventory_id}:{payload.version}".encode()).hexdigest()
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        # Serialise retries before checking the shared receipt table.
        await connection.execute("select pg_advisory_xact_lock(hashtextextended($1,0))",
                                 f"seller-copy:{access['owner_id']}:{idempotency_key}")
        receipt = await connection.fetchrow("select payload_hash,response from tcg.request_receipts where owner_id=$1 and request_key=$2",
                                           access["owner_id"], idempotency_key)
        if receipt:
            if receipt["payload_hash"] != digest:
                raise HTTPException(409, "This addition was already used with different details")
            response = receipt["response"]
            return {**(json.loads(response) if isinstance(response, str) else response), "replayed": True}
        item = await locked_item(connection, inventory_id, access["owner_id"])
        require_editable(item, payload.version)
        if item.get("grading_company") or item.get("grade") or item.get("certificate_number"):
            raise HTTPException(422, "Add each graded slab through Scan with its own certificate.")
        new_id = uuid4()
        row = await connection.fetchrow("""insert into tcg.inventory_items(
             id,inventory_code,owner_id,catalogue_id,language,condition,seal_status,
             currency,status,sale_intent,identity_confirmed,intake_request_key,source_record)
             values($1,$2,$3,$4,$5,$6,$7,'GBP','DRAFT','PERSONAL_COLLECTION',false,$8,$9::jsonb)
             on conflict(intake_request_key) do nothing
             returning id,inventory_code,status,sale_intent,version
             """, new_id, f"INV-{new_id.hex.upper()}", access["owner_id"], item["catalogue_id"],
             item["language"], item["condition"], item["seal_status"], idempotency_key,
             json.dumps({"source": "SELLER_QUANTITY", "source_inventory_id": str(inventory_id), "seller_confirmed": True}))
        if row is None:
            raise HTTPException(409, "This addition key is already in use. Refresh before adding another copy.")
        result = jsonable_encoder({"item": dict(row), "replayed": False,
                                   "message": "One copy added. Review and approve it separately before selling."})
        await connection.execute("insert into tcg.request_receipts(owner_id,request_key,payload_hash,response) values($1,$2,$3,$4::jsonb)",
                                 access["owner_id"], idempotency_key, digest, json.dumps(result))
    return result


@router.post("/{inventory_id}/withdraw")
async def withdraw_copy(inventory_id: UUID, payload: VersionRequest, request: Request,
                        user: Annotated[AuthenticatedUser, Depends(require_user)],
                        access: Annotated[dict, Depends(require_owner_portal_request)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await locked_item(connection, inventory_id, access["owner_id"])
        if item["status"] == "WITHDRAWN":
            return {"message": "This copy is already withdrawn.", "replayed": True}
        require_editable(item, payload.version)
    # Existing fail-closed allocation and remote withdrawal rules apply before
    # lowering active stock. A failed remote withdrawal remains retryable.
    await change_inventory_sale_intent(inventory_id,
        InventorySaleIntentChange(version=payload.version, sale_intent="PERSONAL_COLLECTION"), request, user)
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await locked_item(connection, inventory_id, access["owner_id"])
        if item["status"] == "WITHDRAWN":
            return {"message": "This copy is already withdrawn.", "replayed": True}
        if item["status"] not in ACTIVE or item["sale_intent"] != "PERSONAL_COLLECTION":
            raise HTTPException(409, "This copy changed during withdrawal. Refresh its details.")
        await connection.execute("""update tcg.inventory_items set status='WITHDRAWN',version=version+1,updated_at=clock_timestamp()
                                  where id=$1 and owner_id=$2 and version=$3""", inventory_id, access["owner_id"], item["version"])
    return {"message": "Copy withdrawn. Its history is retained.", "replayed": False}
