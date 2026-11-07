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
PHOTO_PRODUCT_TYPES = {"CARD", "COMIC", "SEALED", "FIGURE", "COLLECTION"}
PHOTO_FILE_STATES = {"UPLOADED", "PROCESSING", "READY", "FAILED"}
PHOTO_PROCESSING_ERROR = "Image processing could not finish. The photo is saved; retry processing or contact Drop Rate."


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
                    or claims.get("identity_version", 1) not in (1, 2)
                    or not re.fullmatch(r"[a-f0-9]{64}", str(claims.get("content_sha256", "")))
                    or not re.fullmatch(r"[a-f0-9]{64}", str(claims.get("identity_sha256", "")))):
                raise ValueError("invalid upload receipt")
        return claims
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise HTTPException(422, "Photo upload expired or was altered. Choose the photo again.") from exc


async def _photo_item(connection, inventory_id: UUID, owner_id: UUID, *, lock: bool = False,
                      comic_only: bool = False, active_only: bool = True):
    row = await connection.fetchrow("""select i.id,i.version,i.status,i.catalogue_id,i.language,i.condition,i.grading_company,i.grade,
           i.seal_status,i.certificate_number,i.acquisition_cost_minor,i.source_record,
           p.name,p.variant,p.product_type,o.owner_type
        from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.owners o on o.id=i.owner_id
        where i.id=$1 and i.owner_id=$2""" + (" for update of i" if lock else ""),
        inventory_id, owner_id)
    if row is None or row["product_type"] not in ({"COMIC"} if comic_only else PHOTO_PRODUCT_TYPES):
        raise HTTPException(404, "Comic inventory item not found" if comic_only else "Inventory item not found")
    if active_only and row["status"] not in {"DRAFT", "INSPECTION", "APPROVED"}:
        raise HTTPException(409, "Sold, reserved or withdrawn items cannot receive photo changes")
    return dict(row)


async def _comic(connection, inventory_id: UUID, owner_id: UUID, *, lock: bool = False):
    return await _photo_item(connection, inventory_id, owner_id, lock=lock, comic_only=True)


async def _active_side(connection, owner_id: UUID, inventory_id: UUID, side: str):
    return await connection.fetchrow("""select id,provider_asset_id,version,approval_status,rights_status,shopify_file_status,shopify_cdn_url
        from tcg.media_assets where owner_id=$1 and inventory_id=$2 and scope='INVENTORY_ITEM'
          and side=$3 and approval_status<>'REJECTED' and shopify_file_status<>'FAILED'
          and source_status<>'REVOKED' order by created_at desc limit 1""",
        owner_id, inventory_id, side)


def _photo_identity(item: dict, identity_version: int = 1) -> str:
    # Version 1 remains readable for receipts issued by the legacy comic relay.
    keys = ["catalogue_id", "name", "variant", "language", "condition", "grading_company", "grade"]
    if identity_version == 2:
        # The seller may assess raw condition after scanning. That assessment
        # is reviewed separately and does not turn this into another copy.
        keys.remove("condition")
        keys += ["product_type", "seal_status", "certificate_number"]
    snapshot = {key: item.get(key) for key in keys}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


def _relay_receipt_id(owner_id, inventory_id, request_key) -> str:
    return hashlib.sha256(
        f"comic-photo-relay:v1:{owner_id}:{inventory_id}:{request_key}".encode()
    ).hexdigest()


def _relay_source_reference(claims: dict) -> str:
    reference = {"filename": claims["filename"], "identity_sha256": claims["identity_sha256"]}
    if claims.get("identity_version") == 2:
        reference["identity_version"] = 2
    return json.dumps(reference, sort_keys=True)


def _photo_preview_url(value: object) -> str | None:
    if not isinstance(value, str) or not 0 < len(value) <= 8192:
        return None
    try:
        url = urlsplit(value)
        if (url.scheme == "https" and url.hostname == "cdn.shopify.com"
                and url.username is None and url.password is None
                and url.port in (None, 443) and not url.fragment):
            return value
    except ValueError:
        pass
    return None


def _public_photo(row) -> dict:
    asset = {key: row.get(key) for key in (
        "id", "version", "side", "approval_status", "rights_status", "shopify_file_status"
    )}
    asset["photo_url"] = (_photo_preview_url(row.get("shopify_cdn_url"))
                          if row.get("shopify_file_status") == "READY" else None)
    return asset


def _receipt_identity_matches(row, item) -> bool:
    try:
        reference = json.loads(row["source_reference"])
        identity_version = reference.get("identity_version", 1)
        return (identity_version in (1, 2)
                and reference.get("identity_sha256") == _photo_identity(item, identity_version))
    except (ValueError, TypeError, AttributeError, KeyError):
        # Old staged tickets without an identity fingerprint need staff review;
        # never silently attach an unbound historic upload to the current copy.
        return False


async def _relay_receipt(connection, owner_id, inventory_id, claims):
    receipt_id = _relay_receipt_id(owner_id, inventory_id, claims["relay_request_key"])
    row = await connection.fetchrow("""select id,version,side,approval_status,rights_status,
        shopify_file_status,source_status,source_reference,content_sha256,shopify_cdn_url
        from tcg.media_assets where owner_id=$1 and inventory_id=$2
          and scope='INVENTORY_ITEM' and provider_asset_id=$3""",
        owner_id, inventory_id, receipt_id)
    if row is None:
        return None
    if (row["side"] != claims["side"] or row["content_sha256"] != claims["content_sha256"]
            or row["source_reference"] != _relay_source_reference(claims)):
        raise HTTPException(409, "This upload request belongs to a different photograph or item identity. Select the photo again.")
    if (row["approval_status"] == "REJECTED" or row["source_status"] == "REVOKED"
            or row["shopify_file_status"] == "FAILED"):
        raise HTTPException(409, "This photo needs a fresh submission. Select the photo again after reviewing the retake request.")
    asset = _public_photo(row)
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
    return await _upload_photo(inventory_id, request, user, access, side, version,
                               filename, rights_confirmed, request_key, comic_only=True)


@router.post("/{inventory_id}/photo/upload", status_code=201)
async def upload_inventory_photo(
    inventory_id: UUID, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
    side: Annotated[Literal["FRONT", "BACK"], Query()],
    version: Annotated[int, Query(ge=1)],
    filename: Annotated[str, Query(min_length=1, max_length=180)],
    rights_confirmed: Annotated[Literal["true"], Query()],
    request_key: Annotated[UUID, Query()],
):
    return await _upload_photo(inventory_id, request, user, access, side, version,
                               filename, rights_confirmed, request_key, comic_only=False)


async def _upload_photo(inventory_id, request, user, access, side, version,
                        filename, rights_confirmed, request_key, *, comic_only):
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
        await _photo_item(connection, inventory_id, access["owner_id"], comic_only=comic_only)
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
        item = await _photo_item(connection, inventory_id, access["owner_id"], comic_only=comic_only)
        if not comic_only:
            claims["identity_version"] = 2
        claims["identity_sha256"] = _photo_identity(item, claims.get("identity_version", 1))
        replay = await _relay_receipt(connection, access["owner_id"], inventory_id, claims)
        if replay:
            return {**replay, "inventory_version": item["version"]}
        if item["version"] != version:
            raise HTTPException(409, "Item details changed. Refresh before submitting this photograph.")
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
    return await _complete_photo(inventory_id,
        ComicPhotoComplete(ticket=_sign_ticket(claims), rights_confirmed=True), request, user, access,
        comic_only=comic_only)


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
    return await _complete_photo(inventory_id, payload, request, user, access, comic_only=True)


async def _complete_photo(inventory_id, payload, request, user, access, *, comic_only):
    claims = _verify_ticket(payload.ticket, owner_id=access["owner_id"], inventory_id=inventory_id)
    relayed = "relay_request_key" in claims
    ticket_digest = (_relay_receipt_id(access["owner_id"], inventory_id, claims["relay_request_key"])
                     if relayed else hashlib.sha256(payload.ticket.encode()).hexdigest())
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await _photo_item(connection, inventory_id, access["owner_id"], lock=True, comic_only=comic_only)
        if relayed:
            if _photo_identity(item, claims.get("identity_version", 1)) != claims["identity_sha256"]:
                raise HTTPException(409, "Item identity changed during upload. Refresh before submitting the photograph.")
            replay = await _relay_receipt(connection, access["owner_id"], inventory_id, claims)
            if replay:
                return {**replay, "inventory_version": item["version"]}
            if item["version"] != claims["version"]:
                raise HTTPException(409, "Item details changed during upload. Refresh before submitting the photograph.")
        current = await _active_side(connection, access["owner_id"], inventory_id, claims["side"])
        if current:
            if current["provider_asset_id"] == ticket_digest:
                return {"asset": jsonable_encoder(_public_photo(current)), "message": "Photo already received for staff review.",
                        "replayed": True, "inventory_version": item["version"]}
            raise HTTPException(409, "A photo is already awaiting review for this side")
        previous = await connection.fetchval("""select exists(select 1 from tcg.media_assets
            where owner_id=$1 and inventory_id=$2 and provider_asset_id=$3)""",
            access["owner_id"], inventory_id, ticket_digest)
        if previous:
            raise HTTPException(409, "This photo ticket was already used. Choose a fresh photo for the retake.")
        capture_context = ("SEALED_PRODUCT" if item["product_type"] in {"SEALED", "COLLECTION"} else
                           "GRADED_SLAB" if item["grading_company"] and item["grade"] else "RAW_UNSLEEVED")
        alt_text = payload.alt_text.strip() or f"{item['name']} {claims['side'].lower()} physical copy photograph"
        rights_basis = "Seller confirms they own or are authorised to submit this exact-copy photograph; staff verification pending"
        try:
            row = await connection.fetchrow("""insert into tcg.media_assets(
                owner_id,inventory_id,scope,side,source_type,rights_tier,source_provider,
                provider_asset_id,source_reference,public_source_url,media_language,media_variant,
                capture_context,rights_basis,alt_text,created_by_user_id,content_sha256)
                values($1,$2,'INVENTORY_ITEM',$3,$4,'FIRST_PARTY_CAPTURE','Drop Rate',
                  $5,$6,$7,$8,$9,$10,$11,$12,$13,$14) returning id,version,approval_status,
                  rights_status,shopify_file_status,side,shopify_cdn_url""",
                access["owner_id"], inventory_id, claims["side"],
                "CONSIGNOR_UPLOAD" if item["owner_type"] == "CONSIGNOR" else "FOUNDER_UPLOAD",
                ticket_digest, _relay_source_reference(claims) if relayed else claims["filename"],
                claims["resource_url"], item["language"], item["variant"], capture_context,
                rights_basis, alt_text, user.user_id, claims.get("content_sha256") if relayed else None)
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(409, "This photo side was submitted from another session. Refresh before retrying.") from exc

    # Commit the receipt before importing a Shopify File. A provider failure
    # cannot erase the submitted photo or cause another inventory intake.
    outcome = await _finish_photo_import(inventory_id, row["id"], request, user, access,
                                         legacy_claims=claims if not relayed else None)
    return jsonable_encoder({"asset": outcome.get("asset") or _public_photo(row),
                             "replayed": False, "message": outcome["message"],
                             "inventory_version": outcome.get("inventory_version", item["version"]),
                             "processing_status": outcome["status"]})


def _file_result(file_row, *, expected_id=None):
    if not isinstance(file_row, dict):
        raise ShopifyApiError("Shopify image processing returned an invalid response")
    file_id, status = file_row.get("id"), file_row.get("fileStatus")
    if (not isinstance(file_id, str) or not re.fullmatch(r"gid://shopify/MediaImage/[0-9]+", file_id)
            or not isinstance(status, str)
            or status not in PHOTO_FILE_STATES or (expected_id and file_id != expected_id)):
        raise ShopifyApiError("Shopify image processing returned an invalid file receipt")
    image = file_row.get("image") if isinstance(file_row.get("image"), dict) else {}
    return file_id, status, _photo_preview_url(image.get("url"))


async def _finish_photo_import(inventory_id, asset_id, request, user, access, *, legacy_claims=None,
                               expected_asset_version=None):
    """Serialize retries for one exact physical receipt, without approving it.

    The receipt has already committed. A bounded provider call inside this
    second transaction keeps concurrent refreshes from creating two Files and
    prevents withdrawal/identity edits while the image import is in flight.
    """
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await _photo_item(connection, inventory_id, access["owner_id"], lock=True, active_only=False)
        row = await connection.fetchrow("""select id,version,side,approval_status,rights_status,
            shopify_file_status,shopify_file_gid,shopify_cdn_url,source_status,source_type,
            rights_tier,source_provider,source_reference,public_source_url,alt_text
            from tcg.media_assets where id=$1 and owner_id=$2 and inventory_id=$3
              and scope='INVENTORY_ITEM' for update""", asset_id, access["owner_id"], inventory_id)
        if row is None:
            raise HTTPException(404, "Photo receipt not found")
        if expected_asset_version is not None and row["version"] != expected_asset_version:
            raise HTTPException(409, "Photo changed. Refresh the review queue.")
        outcome = {"asset": _public_photo(row), "asset_id": str(row["id"]), "side": row["side"],
                   "inventory_version": item["version"]}
        if item["status"] not in {"DRAFT", "INSPECTION", "APPROVED"}:
            return {**outcome, "status": "UNCHANGED", "message": "Photo received. This item is no longer available for photo changes."}
        if (row["approval_status"] != "PENDING" or row["rights_status"] not in {"PENDING", "VERIFIED"}
                or row["source_status"] != "ACTIVE" or row["rights_tier"] != "FIRST_PARTY_CAPTURE"
                or row["source_type"] not in {"CONSIGNOR_UPLOAD", "FOUNDER_UPLOAD"}
                or row["source_provider"] != "Drop Rate"):
            return {**outcome, "status": "UNCHANGED", "message": "Photo review status changed. Refresh the item to see its current review."}
        if not legacy_claims and not _receipt_identity_matches(row, item):
            return {**outcome, "status": "IDENTITY_CHANGED", "message": "Item identity changed after this photo was received. Drop Rate needs to check the photo before processing it."}
        if row["shopify_file_status"] == "FAILED":
            return {**outcome, "status": "RETAKE_REQUIRED", "message": "Image processing failed. Submit a new photo for this side."}
        if row["shopify_file_status"] == "READY" and outcome["asset"]["photo_url"]:
            return {**outcome, "status": "READY", "message": "Photo received and ready for Drop Rate review. It is not approved for publication."}
        # Only the temporary destination returned by Shopify during the trusted
        # relay is ever sent back for import. No caller URL or arbitrary DB URL.
        if row["shopify_file_status"] == "NOT_UPLOADED" and not _allowed_staged_url(row["public_source_url"]):
            return {**outcome, "status": "NEEDS_REVIEW", "message": "This saved photo needs staff attention before image processing can continue."}
        error = None
        try:
            # The normal pool expires idle transactions after 10s. This one
            # contains a strictly bounded external call and needs its row lock.
            await connection.execute("set local idle_in_transaction_session_timeout='55000'")
            async with asyncio.timeout(PHOTO_TRANSFER_SECONDS):
                client = _shopify()
                if row["shopify_file_status"] == "NOT_UPLOADED":
                    if "write_files" not in await client.access_scopes():
                        raise ShopifyApiError("Shopify Files permission is missing")
                    file_row = await client.create_file_from_url(source_url=row["public_source_url"], alt_text=row["alt_text"])
                    file_id, status, cdn_url = _file_result(file_row)
                else:
                    if not re.fullmatch(r"gid://shopify/MediaImage/[0-9]+", str(row["shopify_file_gid"] or "")):
                        raise ShopifyApiError("Saved Shopify image receipt is invalid")
                    file_row = await client.get_file(row["shopify_file_gid"])
                    file_id, status, cdn_url = _file_result(file_row, expected_id=row["shopify_file_gid"])
            error = ("Photo file processing failed" if status == "FAILED" else
                     "Image preview is not ready. Retry processing shortly." if status == "READY" and not cdn_url else None)
            updated = await connection.fetchrow("""update tcg.media_assets set
                shopify_file_gid=$3,shopify_file_status=$4,shopify_cdn_url=$5,shopify_error=$6,
                version=version+1,updated_at=clock_timestamp()
                where id=$1 and owner_id=$2 and version=$7
                returning id,version,side,approval_status,rights_status,shopify_file_status,shopify_cdn_url""",
                row["id"], access["owner_id"], file_id, status, cdn_url, error, row["version"])
        except (ShopifyApiError, HTTPException, TimeoutError):
            # Never persist provider messages, which may contain signed URLs or
            # credentials. An explicit local error replaces the previous NULL.
            error = PHOTO_PROCESSING_ERROR
            updated = await connection.fetchrow("""update tcg.media_assets set
                shopify_error=$3,version=version+1,updated_at=clock_timestamp()
                where id=$1 and owner_id=$2 and version=$4
                returning id,version,side,approval_status,rights_status,shopify_file_status,shopify_cdn_url""",
                row["id"], access["owner_id"], error, row["version"])
        if updated:
            outcome["asset"] = _public_photo(updated)
        state = outcome["asset"]["shopify_file_status"]
        if error or state in {"NOT_UPLOADED", "FAILED"}:
            return {**outcome, "status": "NEEDS_RETRY" if state != "FAILED" else "RETAKE_REQUIRED",
                    "message": "Physical photo received. Image processing needs staff attention or a retry; your photo remains saved and unapproved."}
        return {**outcome, "status": state,
                "message": "Physical photo received. Drop Rate must review it before the item can be listed."}


@router.get("/{inventory_id}/photos")
async def inventory_photos(
    inventory_id: UUID, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        item = await _photo_item(connection, inventory_id, access["owner_id"], active_only=False)
        rows = await connection.fetch("""select distinct on (side)
            id,version,side,approval_status,rights_status,shopify_file_status,shopify_cdn_url
            from tcg.media_assets where owner_id=$1 and inventory_id=$2
              and scope='INVENTORY_ITEM' and rights_tier='FIRST_PARTY_CAPTURE'
              and source_type in ('CONSIGNOR_UPLOAD','FOUNDER_UPLOAD') and source_status='ACTIVE'
            order by side,created_at desc,id desc limit 3""", access["owner_id"], inventory_id)
    return jsonable_encoder({"items": [_public_photo(row) for row in rows], "inventory_version": item["version"]})


@router.post("/{inventory_id}/photos/refresh")
async def refresh_inventory_photos(
    inventory_id: UUID, request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    access: Annotated[dict, Depends(require_owner_portal_request)],
):
    # No request payload is needed: neither asset IDs nor source URLs are
    # caller-controlled. The current owned item supplies at most three sides.
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        await _photo_item(connection, inventory_id, access["owner_id"])
        rows = await connection.fetch("""select distinct on (side) id,side
            from tcg.media_assets where owner_id=$1 and inventory_id=$2
              and scope='INVENTORY_ITEM' and rights_tier='FIRST_PARTY_CAPTURE'
              and source_type in ('CONSIGNOR_UPLOAD','FOUNDER_UPLOAD') and source_provider='Drop Rate'
              and source_status='ACTIVE' and approval_status='PENDING'
              and rights_status in ('PENDING','VERIFIED')
              and (shopify_file_status in ('NOT_UPLOADED','UPLOADED','PROCESSING')
                or (shopify_file_status='READY' and shopify_cdn_url is null))
            order by side,created_at desc,id desc limit 3""", access["owner_id"], inventory_id)
    outcomes = []
    for row in rows:
        outcomes.append(await _finish_photo_import(inventory_id, row["id"], request, user, access))
    result = await inventory_photos(inventory_id, request, user, access)
    partial = any(outcome["status"] not in {"READY", "UPLOADED", "PROCESSING"} for outcome in outcomes)
    result.update(results=[{key: value for key, value in outcome.items() if key in {"asset_id", "side", "status", "message"}}
                           for outcome in outcomes], partial=partial,
                  message=("Your photos are saved. Some still need processing or staff attention." if partial else
                           "Photo processing checked. Drop Rate review is still required before publication."))
    return result
