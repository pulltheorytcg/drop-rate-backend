"""Owner-scoped comic listing preparation and *unapproved* physical-photo intake.

This does not verify a printing, approve stock, or attach media to a product.
Only the existing reviewed Shopify publisher may publish an approved copy.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Annotated, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .settings import get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError


router = APIRouter(prefix="/api/v1/owner/inventory", tags=["comic-listing-preparation"])
MAX_PHOTO_BYTES = 12 * 1024 * 1024
PHOTO_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
PHOTO_TICKET_SECONDS = 15 * 60


class ComicPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, strict=True)
    holding: Literal["SELLER_HELD", "DROP_RATE_HELD"]
    dispatch_note: str = Field(default="", max_length=200)
    acquisition_cost_minor: int | None = Field(default=None, ge=0, le=100_000_000, strict=True)
    parcel_weight_grams: int | None = Field(default=None, ge=1, le=100_000, strict=True)
    parcel_length_mm: int | None = Field(default=None, ge=1, le=10_000, strict=True)
    parcel_width_mm: int | None = Field(default=None, ge=1, le=10_000, strict=True)
    parcel_height_mm: int | None = Field(default=None, ge=1, le=10_000, strict=True)


class ComicPhotoStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    side: Literal["FRONT", "BACK"]
    filename: str = Field(min_length=1, max_length=180)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    file_size: int = Field(ge=1, le=MAX_PHOTO_BYTES, strict=True)


class ComicPhotoComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(min_length=40, max_length=8192)
    rights_confirmed: Literal[True]
    alt_text: str = Field(default="", max_length=500)


def _shopify() -> ShopifyAdminClient:
    settings = get_settings()
    if not all((settings.shopify_shop_domain, settings.shopify_client_id, settings.shopify_client_secret)):
        raise HTTPException(409, "Shopify photo intake is not configured. Your listing is still saved.")
    return ShopifyAdminClient(shop_domain=settings.shopify_shop_domain,
                              client_id=settings.shopify_client_id,
                              client_secret=settings.shopify_client_secret,
                              api_version=settings.shopify_api_version)


def _ticket_key() -> bytes:
    # Domain separation: a leaked upload ticket cannot be used as an Admin API
    # credential or a token for any other application operation.
    secret = get_settings().shopify_client_secret
    if not secret:
        raise HTTPException(409, "Shopify photo intake is not configured")
    return hmac.new(secret.encode(), b"drop-rate-comic-photo-ticket-v1", hashlib.sha256).digest()


def _sign_ticket(claims: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(_ticket_key(), encoded, hashlib.sha256).digest()
    return encoded.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def _verify_ticket(ticket: str, *, owner_id: UUID, inventory_id: UUID) -> dict:
    try:
        payload, signature = ticket.split(".")
        encoded = payload.encode("ascii")
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        expected = hmac.new(_ticket_key(), encoded, hashlib.sha256).digest()
        if not hmac.compare_digest(actual, expected):
            raise ValueError("invalid signature")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not isinstance(claims, dict) or claims.get("owner") != str(owner_id) or claims.get("inventory") != str(inventory_id):
            raise ValueError("wrong owner or inventory")
        if claims.get("side") not in {"FRONT", "BACK"} or claims.get("mime") not in PHOTO_MIME_TYPES:
            raise ValueError("invalid file specification")
        if not isinstance(claims.get("size"), int) or not 0 < claims["size"] <= MAX_PHOTO_BYTES:
            raise ValueError("invalid file size")
        expiry = claims.get("exp")
        if not isinstance(expiry, int) or not time.time() <= expiry <= time.time() + PHOTO_TICKET_SECONDS:
            raise ValueError("expired upload ticket")
        if not isinstance(claims.get("resource_url"), str) or not claims["resource_url"].startswith("https://"):
            raise ValueError("invalid resource URL")
        if not isinstance(claims.get("filename"), str) or not 0 < len(claims["filename"]) <= 180:
            raise ValueError("invalid filename")
        return claims
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise HTTPException(422, "Photo upload expired or was altered. Choose the photo again.") from exc


async def _comic(connection, inventory_id: UUID, owner_id: UUID, *, lock: bool = False):
    row = await connection.fetchrow("""select i.id,i.version,i.status,i.language,i.grading_company,i.grade,
           i.acquisition_cost_minor,i.source_record,p.name,p.variant,p.product_type,o.owner_type
        from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.owners o on o.id=i.owner_id
        where i.id=$1 and i.owner_id=$2""" + (" for update of i" if lock else ""),
        inventory_id, owner_id)
    if row is None or row["product_type"] != "COMIC":
        raise HTTPException(404, "Comic inventory item not found")
    if row["status"] not in {"DRAFT", "INSPECTION", "APPROVED"}:
        raise HTTPException(409, "Sold, reserved or withdrawn comics cannot be prepared")
    return dict(row)


async def _active_side(connection, owner_id: UUID, inventory_id: UUID, side: str):
    return await connection.fetchrow("""select id,provider_asset_id,version,approval_status,shopify_file_status
        from tcg.media_assets where owner_id=$1 and inventory_id=$2 and scope='INVENTORY_ITEM'
          and side=$3 and approval_status<>'REJECTED' and shopify_file_status<>'FAILED'
          and source_status<>'REVOKED' order by created_at desc limit 1""",
        owner_id, inventory_id, side)


@router.patch("/{inventory_id}/comic-preparation")
async def save_comic_preparation(
    inventory_id: UUID, payload: ComicPreparation, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
):
    preparation = payload.model_dump(exclude={"version", "acquisition_cost_minor"})
    preparation["submitted_by"] = str(user.user_id)
    # These measurements are suggestions. They NEVER configure or select an
    # active Shopify shipping profile or assert actual physical possession.
    preparation["staff_verified"] = False
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await _comic(connection, inventory_id, access["owner_id"], lock=True)
        if item["version"] != payload.version:
            raise HTTPException(409, "Comic details changed. Refresh before saving preparation.")
        row = await connection.fetchrow("""update tcg.inventory_items set
            acquisition_cost_minor=coalesce($4::integer,acquisition_cost_minor),
            source_record=jsonb_set(coalesce(source_record,'{}'::jsonb),
              '{comic_listing_preparation}',$5::jsonb,true),
            version=version+1,updated_at=clock_timestamp()
            where id=$1 and owner_id=$2 and version=$3
            returning id,version,acquisition_cost_minor,source_record->'comic_listing_preparation' as preparation""",
            inventory_id, access["owner_id"], payload.version,
            payload.acquisition_cost_minor, json.dumps(preparation))
        if row is None:
            raise HTTPException(409, "Comic details changed. Refresh before saving preparation.")
    return jsonable_encoder({"item": dict(row), "message":
        "Preparation saved for Drop Rate review. Holding and parcel details are not shipping approval."})


@router.post("/{inventory_id}/comic-photo/upload-target")
async def comic_photo_upload_target(
    inventory_id: UUID, payload: ComicPhotoStage, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
):
    filename = payload.filename.strip()
    if not filename or any(char in filename for char in ("/", "\\", "\x00", "\r", "\n")):
        raise HTTPException(422, "Choose a photo with a plain file name")
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _comic(connection, inventory_id, access["owner_id"])
        if await _active_side(connection, access["owner_id"], inventory_id, payload.side):
            raise HTTPException(409, "This side is already submitted. Wait for review or a photo retake request.")
    client = _shopify()
    if "write_files" not in await client.access_scopes():
        raise HTTPException(409, "Shopify photo intake is unavailable; please try again after staff reconnect the app")
    target = await client.create_staged_image_upload(filename=filename, mime_type=payload.mime_type,
                                                     file_size=payload.file_size)
    ticket = _sign_ticket({"owner": str(access["owner_id"]), "inventory": str(inventory_id),
                          "side": payload.side, "filename": filename, "mime": payload.mime_type,
                          "size": payload.file_size, "resource_url": target["resourceUrl"],
                          "nonce": uuid4().hex, "exp": int(time.time()) + PHOTO_TICKET_SECONDS})
    return {"target": {"url": target["url"], "parameters": target["parameters"]},
            "ticket": ticket, "expires_in_seconds": PHOTO_TICKET_SECONDS}


@router.post("/{inventory_id}/comic-photo/complete", status_code=201)
async def complete_comic_photo(
    inventory_id: UUID, payload: ComicPhotoComplete, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
):
    claims = _verify_ticket(payload.ticket, owner_id=access["owner_id"], inventory_id=inventory_id)
    ticket_digest = hashlib.sha256(payload.ticket.encode()).hexdigest()
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await _comic(connection, inventory_id, access["owner_id"], lock=True)
        current = await _active_side(connection, access["owner_id"], inventory_id, claims["side"])
        if current:
            if current["provider_asset_id"] == ticket_digest:
                return {"asset": jsonable_encoder(dict(current)), "message": "Photo already received for staff review.", "replayed": True}
            raise HTTPException(409, "A photo is already awaiting review for this side")
        previous = await connection.fetchval("""select exists(select 1 from tcg.media_assets
            where owner_id=$1 and inventory_id=$2 and provider_asset_id=$3)""",
            access["owner_id"], inventory_id, ticket_digest)
        if previous:
            raise HTTPException(409, "This photo ticket was already used. Choose a fresh photo for the retake.")
        capture_context = "GRADED_SLAB" if item["grading_company"] and item["grade"] else "RAW_UNSLEEVED"
        alt_text = payload.alt_text.strip() or f"{item['name']} {claims['side'].lower()} physical copy photograph"
        rights_basis = "Seller confirms they own or are authorised to submit this exact-copy photograph; staff verification pending"
        try:
            row = await connection.fetchrow("""insert into tcg.media_assets(
                owner_id,inventory_id,scope,side,source_type,rights_tier,source_provider,
                provider_asset_id,source_reference,public_source_url,media_language,media_variant,
                capture_context,rights_basis,alt_text,created_by_user_id)
                values($1,$2,'INVENTORY_ITEM',$3,$4,'FIRST_PARTY_CAPTURE','Drop Rate',
                  $5,$6,$7,$8,$9,$10,$11,$12,$13) returning id,version,approval_status,
                  rights_status,shopify_file_status,side""",
                access["owner_id"], inventory_id, claims["side"],
                "CONSIGNOR_UPLOAD" if item["owner_type"] == "CONSIGNOR" else "FOUNDER_UPLOAD",
                ticket_digest, claims["filename"], claims["resource_url"], item["language"],
                item["variant"], capture_context, rights_basis, alt_text, user.user_id)
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(409, "This photo side was submitted from another session. Refresh before retrying.") from exc

    # Shopify Files are *not* Shopify products. Importing a photo for human
    # inspection cannot satisfy rights approval or publish the comic.
    try:
        file_row = await _shopify().create_file_from_url(source_url=claims["resource_url"], alt_text=alt_text)
        file_id = str(file_row.get("id") or "")
        file_status = str(file_row.get("fileStatus") or "").upper()
        image = file_row.get("image") if isinstance(file_row.get("image"), dict) else {}
        cdn_url = str(image.get("url") or "")
        if file_id and file_status in {"UPLOADED", "PROCESSING", "READY", "FAILED"}:
            async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
                updated = await connection.fetchrow("""update tcg.media_assets set
                    shopify_file_gid=$3,shopify_file_status=$4,
                    shopify_cdn_url=nullif($5,''),shopify_error=case when $4='FAILED'
                      then 'Photo file processing failed' else null end,
                    version=version+1,updated_at=clock_timestamp()
                    where id=$1 and owner_id=$2 and shopify_file_status='NOT_UPLOADED'
                    returning id,version,side,approval_status,rights_status,shopify_file_status""",
                    row["id"], access["owner_id"], file_id, file_status, cdn_url)
                if updated:
                    row = updated
    except (ShopifyApiError, HTTPException):
        # Keep the unapproved receipt. Staff can inspect the failed transfer;
        # the seller must never be told that a Shopify product is live.
        pass
    return jsonable_encoder({"asset": dict(row), "replayed": False,
        "message": "Physical photo received. Drop Rate must review it before the comic can be listed."})
