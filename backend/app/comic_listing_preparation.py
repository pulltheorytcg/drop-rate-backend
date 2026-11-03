"""Owner-scoped comic listing preparation and *unapproved* physical-photo intake.

This does not verify a printing, approve stock, or attach media to a product.
Only the existing reviewed Shopify publisher may publish an approved copy.
"""
from __future__ import annotations

import base64
import asyncio
import binascii
import hashlib
import hmac
import json
import io
import re
import time
import warnings
from typing import Annotated, Literal
from uuid import UUID, uuid4
from urllib.parse import urlsplit

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image, UnidentifiedImageError

from .access_control import require_owner_portal_request
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .settings import get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError


router = APIRouter(prefix="/api/v1/owner/inventory", tags=["comic-listing-preparation"])
MAX_PHOTO_BYTES = 12 * 1024 * 1024
PHOTO_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
PHOTO_TICKET_SECONDS = 15 * 60
MAX_PHOTO_PIXELS = 40_000_000
PHOTO_TRANSFER_SECONDS = 45


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
        if "relay_request_key" in claims:
            if not isinstance(claims["relay_request_key"], str):
                raise ValueError("invalid upload receipt key")
            UUID(claims["relay_request_key"])
            if (type(claims.get("version")) is not int or claims["version"] < 1
                    or not re.fullmatch(r"[a-f0-9]{64}", str(claims.get("content_sha256", "")))
                    or not re.fullmatch(r"[a-f0-9]{64}", str(claims.get("identity_sha256", "")))):
                raise ValueError("invalid upload receipt")
        return claims
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise HTTPException(422, "Photo upload expired or was altered. Choose the photo again.") from exc


async def _comic(connection, inventory_id: UUID, owner_id: UUID, *, lock: bool = False):
    row = await connection.fetchrow("""select i.id,i.version,i.status,i.catalogue_id,i.language,i.condition,i.grading_company,i.grade,
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


def _photo_identity(item: dict) -> str:
    snapshot = {key: item.get(key) for key in (
        "catalogue_id", "name", "variant", "language", "condition", "grading_company", "grade"
    )}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


def _relay_receipt_id(owner_id, inventory_id, request_key) -> str:
    return hashlib.sha256(
        f"comic-photo-relay:v1:{owner_id}:{inventory_id}:{request_key}".encode()
    ).hexdigest()


def _relay_source_reference(claims: dict) -> str:
    return json.dumps({"filename": claims["filename"],
                       "identity_sha256": claims["identity_sha256"]}, sort_keys=True)


async def _relay_receipt(connection, owner_id, inventory_id, claims):
    receipt_id = _relay_receipt_id(owner_id, inventory_id, claims["relay_request_key"])
    row = await connection.fetchrow("""select id,version,side,approval_status,rights_status,
        shopify_file_status,source_status,source_reference,content_sha256
        from tcg.media_assets where owner_id=$1 and inventory_id=$2
          and scope='INVENTORY_ITEM' and provider_asset_id=$3""",
        owner_id, inventory_id, receipt_id)
    if row is None:
        return None
    if (row["side"] != claims["side"] or row["content_sha256"] != claims["content_sha256"]
            or row["source_reference"] != _relay_source_reference(claims)):
        raise HTTPException(409, "This upload request belongs to a different photograph or comic identity. Select the photo again.")
    if (row["approval_status"] == "REJECTED" or row["source_status"] == "REVOKED"
            or row["shopify_file_status"] == "FAILED"):
        raise HTTPException(409, "This photo needs a fresh submission. Select the photo again after reviewing the retake request.")
    asset = {key: row[key] for key in (
        "id", "version", "side", "approval_status", "rights_status", "shopify_file_status"
    )}
    message = ("Photo already received. Image processing needs staff attention; the photo remains unapproved."
               if row["shopify_file_status"] == "NOT_UPLOADED" else
               "Photo already received. Drop Rate review is still required before publication.")
    return jsonable_encoder({"asset": asset, "replayed": True, "message": message})


def _validate_photo_bytes(body: bytes, mime_type: str) -> None:
    expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime_type]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body), formats=[expected]) as image:
                if (image.format != expected or getattr(image, "n_frames", 1) != 1
                        or min(image.size) < 200 or image.width * image.height > MAX_PHOTO_PIXELS):
                    raise ValueError("Unsupported photograph dimensions or animation")
                image.verify()
            with Image.open(io.BytesIO(body), formats=[expected]) as image:
                image.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "Choose a valid, still JPG, PNG or WebP photograph between 200 pixels and 40 megapixels.") from None


def _allowed_staged_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 8192:
        return False
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or url.username is not None or url.password is not None
                or url.port not in (None, 443) or url.fragment):
            return False
        host = url.hostname or ""
        return (host in {"shopify-staged-uploads.storage.googleapis.com",
                         "shopify.s3.amazonaws.com", "staged-uploads.shopify.com"}
                or bool(re.fullmatch(r"shopify-staged-uploads\.s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com", host))
                or (host == "storage.googleapis.com" and url.path.startswith("/shopify-staged-uploads/"))
                or (host.endswith(".myshopify.com")
                    and host == str(getattr(get_settings(), "shopify_shop_domain", "")).strip().lower()
                    and url.path == "/admin/tmp/files"))
    except ValueError:
        return False


async def _transfer_photo(target: dict, body: bytes, filename: str, mime_type: str) -> None:
    # Only a Shopify Admin API response reaches this function. Never accept an
    # upload URL, multipart policy or redirect destination from the caller.
    if not _allowed_staged_url(target.get("url")) or not _allowed_staged_url(target.get("resourceUrl")):
        raise HTTPException(502, "Shopify returned an unsupported photo destination. Nothing was published.")
    parameters = target.get("parameters")
    if not isinstance(parameters, list) or not 1 <= len(parameters) <= 32:
        raise HTTPException(502, "Shopify returned invalid photo upload parameters.")
    parts = []
    for part in parameters:
        if not isinstance(part, dict):
            raise HTTPException(502, "Shopify returned invalid photo upload parameters.")
        name, value = part.get("name"), part.get("value")
        if (not isinstance(name, str) or not 0 < len(name) <= 100 or name.lower() == "file"
                or any(char in name for char in ("\r", "\n", "\x00"))
                or not isinstance(value, str) or len(value) > 16_384):
            raise HTTPException(502, "Shopify returned invalid photo upload parameters.")
        parts.append((name, (None, value)))
    parts.append(("file", (filename, body, mime_type)))
    try:
        async with asyncio.timeout(PHOTO_TRANSFER_SECONDS):
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=False) as client:
                async with client.stream("POST", target["url"], files=parts) as response:
                    if not 200 <= response.status_code < 300:
                        raise HTTPException(502, "Photo transfer did not finish. Retry the same photo; nothing was published.")
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(502, "Photo transfer was interrupted. Retry the same photo; nothing was published.") from None


@router.post("/{inventory_id}/comic-photo/upload", status_code=201)
async def upload_comic_photo(
    inventory_id: UUID, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    side: Annotated[Literal["FRONT", "BACK"], Query()],
    version: Annotated[int, Query(ge=1)],
    filename: Annotated[str, Query(min_length=1, max_length=180)],
    rights_confirmed: Annotated[Literal["true"], Query()],
    request_key: Annotated[UUID, Query()],
):
    """Same-origin photo transfer; never a rights, stock or publish approval."""
    filename = filename.strip()
    if not filename or any(char in filename for char in ("/", "\\", "\x00", "\r", "\n")):
        raise HTTPException(422, "Choose a photo with a plain file name")
    mime_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime_type not in PHOTO_MIME_TYPES or rights_confirmed != "true":
        raise HTTPException(422, "Choose a JPG, PNG or WebP photograph and confirm your permission to use it.")
    declared = request.headers.get("content-length")
    try:
        if declared is not None and not 0 < int(declared) <= MAX_PHOTO_BYTES:
            raise ValueError()
    except ValueError:
        raise HTTPException(413, "Choose one photograph up to 12 MB.") from None
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _comic(connection, inventory_id, access["owner_id"])
    body = bytearray()
    try:
        async with asyncio.timeout(PHOTO_TRANSFER_SECONDS):
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_PHOTO_BYTES:
                    raise HTTPException(413, "Choose one photograph up to 12 MB.")
                body.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "Photo upload timed out. Retry the same photo.") from None
    if not body or (declared is not None and len(body) != int(declared)):
        raise HTTPException(422, "The full photograph was not received. Retry the same photo.")
    image_bytes = bytes(body)
    await asyncio.to_thread(_validate_photo_bytes, image_bytes, mime_type)
    claims = {"owner": str(access["owner_id"]), "inventory": str(inventory_id),
              "side": side, "filename": filename, "mime": mime_type, "size": len(image_bytes),
              "relay_request_key": str(request_key), "content_sha256": hashlib.sha256(image_bytes).hexdigest(),
              "version": version}
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await _comic(connection, inventory_id, access["owner_id"])
        claims["identity_sha256"] = _photo_identity(item)
        replay = await _relay_receipt(connection, access["owner_id"], inventory_id, claims)
        if replay:
            return replay  # A lost response may be retried after the item version changes.
        if item["version"] != version:
            raise HTTPException(409, "Comic details changed. Refresh before submitting this photograph.")
        if await _active_side(connection, access["owner_id"], inventory_id, side):
            raise HTTPException(409, "This side is already submitted. Wait for review or a photo retake request.")
    client = _shopify()
    try:
        if "write_files" not in await client.access_scopes():
            raise HTTPException(409, "Shopify photo intake is unavailable; staff need to reconnect the app.")
        target = await client.create_staged_image_upload(filename=filename, mime_type=mime_type,
                                                         file_size=len(image_bytes))
        await _transfer_photo(target, image_bytes, filename, mime_type)
    except ShopifyApiError:
        raise HTTPException(502, "Photo intake is temporarily unavailable. Retry the same photo; nothing was published.") from None
    claims.update(resource_url=target["resourceUrl"], nonce=str(request_key),
                  exp=int(time.time()) + PHOTO_TICKET_SECONDS)
    return await complete_comic_photo(inventory_id,
        ComicPhotoComplete(ticket=_sign_ticket(claims), rights_confirmed=True), request, user, access)


@router.patch("/{inventory_id}/comic-preparation")
async def save_comic_preparation(
    inventory_id: UUID, payload: ComicPreparation, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
):
    preparation = payload.model_dump(exclude={"version"})
    preparation["submitted_by"] = str(user.user_id)
    # Seller-reported purchase cost, physical holding and measurements are
    # evidence, not authoritative finance/intake records. They NEVER configure
    # a shipping profile, set verified acquisition cost or assert possession.
    preparation["staff_verified"] = False
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await _comic(connection, inventory_id, access["owner_id"], lock=True)
        if item["version"] != payload.version:
            raise HTTPException(409, "Comic details changed. Refresh before saving preparation.")
        row = await connection.fetchrow("""update tcg.inventory_items set
            source_record=jsonb_set(coalesce(source_record,'{}'::jsonb),
              '{comic_listing_preparation}',$4::jsonb,true),
            version=version+1,updated_at=clock_timestamp()
            where id=$1 and owner_id=$2 and version=$3
            returning id,version,acquisition_cost_minor,source_record->'comic_listing_preparation' as preparation""",
            inventory_id, access["owner_id"], payload.version,
            json.dumps(preparation))
        if row is None:
            raise HTTPException(409, "Comic details changed. Refresh before saving preparation.")
    return jsonable_encoder({"item": dict(row), "message":
        "Preparation saved for Drop Rate review. Purchase cost, holding and parcel details are not verified intake or shipping approval."})


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
    relayed = "relay_request_key" in claims
    ticket_digest = (_relay_receipt_id(access["owner_id"], inventory_id, claims["relay_request_key"])
                     if relayed else hashlib.sha256(payload.ticket.encode()).hexdigest())
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await _comic(connection, inventory_id, access["owner_id"], lock=True)
        if relayed:
            if _photo_identity(item) != claims["identity_sha256"]:
                raise HTTPException(409, "Comic identity changed during upload. Refresh before submitting the photograph.")
            replay = await _relay_receipt(connection, access["owner_id"], inventory_id, claims)
            if replay:
                return replay
            if item["version"] != claims["version"]:
                raise HTTPException(409, "Comic details changed during upload. Refresh before submitting the photograph.")
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
                capture_context,rights_basis,alt_text,created_by_user_id,content_sha256)
                values($1,$2,'INVENTORY_ITEM',$3,$4,'FIRST_PARTY_CAPTURE','Drop Rate',
                  $5,$6,$7,$8,$9,$10,$11,$12,$13,$14) returning id,version,approval_status,
                  rights_status,shopify_file_status,side""",
                access["owner_id"], inventory_id, claims["side"],
                "CONSIGNOR_UPLOAD" if item["owner_type"] == "CONSIGNOR" else "FOUNDER_UPLOAD",
                ticket_digest, _relay_source_reference(claims) if relayed else claims["filename"],
                claims["resource_url"], item["language"], item["variant"], capture_context,
                rights_basis, alt_text, user.user_id, claims.get("content_sha256") if relayed else None)
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
    message = ("Physical photo received. Shopify image processing needs staff attention; the photo remains unapproved."
               if row["shopify_file_status"] in {"NOT_UPLOADED", "FAILED"} else
               "Physical photo received. Drop Rate must review it before the comic can be listed.")
    return jsonable_encoder({"asset": dict(row), "replayed": False, "message": message})
