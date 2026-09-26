from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Any
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ebay_sell_client import EbaySellApiError, EbaySellClient
from .ownership import current_owner as _owner
from .settings import Settings, get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ebay", tags=["ebay-sales"])

EBAY_GB_CCG_SINGLE_CATEGORY_ID = "183454"
MAX_NOTIFICATION_BYTES = 512 * 1024
EBAY_INVENTORY_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.inventory"
EBAY_FULFILLMENT_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.fulfillment"
EBAY_NOTIFICATION_SCOPE = "https://api.ebay.com/oauth/api_scope/commerce.notification.subscription"

_GRADER_IDS = {
    "PSA": "275010",
    "PROFESSIONAL SPORTS AUTHENTICATOR": "275010",
    "BCCG": "275011",
    "BVG": "275012",
    "BGS": "275013",
    "BECKETT": "275013",
    "CGC": "275015",
    "SGC": "275016",
    "ACE": "2750119",
    "ACE GRADING": "2750119",
}
_GRADE_IDS = {
    "10": "275020", "9.5": "275021", "9": "275022", "8.5": "275023",
    "8": "275024", "7.5": "275025", "7": "275026", "6.5": "275027",
    "6": "275028", "5.5": "275029", "5": "2750210", "4.5": "2750211",
    "4": "2750212", "3.5": "2750213", "3": "2750214", "2.5": "2750215",
    "2": "2750216", "1.5": "2750217", "1": "2750218",
    "AUTHENTIC": "2750219", "AUTHENTIC ALTERED": "2750220",
    "AUTHENTIC - TRIMMED": "2750221", "AUTHENTIC - COLOURED": "2750222",
}


class EbayListRequest(BaseModel):
    version: int = Field(ge=1)


class EbayChannelConflict(RuntimeError):
    def __init__(self, link_id: UUID, status: str) -> None:
        super().__init__(f"Physical inventory is {status}; manual resolution is required")
        self.link_id = link_id
        self.status = status


def _seller_config_missing(settings: Settings, *, include_publish_gate: bool) -> list[str]:
    required = {
        "TCG_EBAY_CLIENT_ID": settings.ebay_client_id,
        "TCG_EBAY_CLIENT_SECRET": settings.ebay_client_secret,
        "TCG_EBAY_USER_REFRESH_TOKEN": settings.ebay_user_refresh_token,
        "TCG_EBAY_PAYMENT_POLICY_ID": settings.ebay_payment_policy_id,
        "TCG_EBAY_FULFILLMENT_POLICY_ID": settings.ebay_fulfillment_policy_id,
        "TCG_EBAY_RETURN_POLICY_ID": settings.ebay_return_policy_id,
        "TCG_EBAY_MERCHANT_LOCATION_KEY": settings.ebay_merchant_location_key,
    }
    missing = [name for name, value in required.items() if not value]
    if include_publish_gate and not settings.ebay_publish_enabled:
        missing.append("TCG_EBAY_PUBLISH_ENABLED")
    return missing


def _client(settings: Settings) -> EbaySellClient:
    missing = _seller_config_missing(settings, include_publish_gate=False)
    if missing:
        raise RuntimeError("eBay seller connection is incomplete")
    return EbaySellClient(
        client_id=settings.ebay_client_id or "",
        client_secret=settings.ebay_client_secret or "",
        refresh_token=settings.ebay_user_refresh_token or "",
        marketplace_id=settings.ebay_marketplace_id,
    )


def _shopify_client(settings: Settings) -> ShopifyAdminClient | None:
    if not (
        settings.shopify_shop_domain
        and settings.shopify_client_id
        and settings.shopify_client_secret
    ):
        return None
    return ShopifyAdminClient(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        api_version=settings.shopify_api_version,
    )


def _channel_price(store_price_minor: int, markup_bps: int) -> int:
    if store_price_minor < 100:
        raise ValueError("Store Price must be at least £1")
    return max(100, (store_price_minor * (10_000 + markup_bps) + 5_000) // 10_000)


def _money_value(minor: int) -> str:
    return f"{Decimal(minor) / Decimal(100):.2f}"


def _parse_money_minor(value: object, currency: object) -> int:
    if str(currency or "").upper() != "GBP":
        raise ValueError("Only GBP eBay orders are supported")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid eBay monetary amount") from exc
    if amount < 0:
        raise ValueError("eBay monetary amount cannot be negative")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _grade_key(value: object) -> str:
    raw = str(value or "").strip().upper()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw


def _condition_payload(item: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    grader = str(item.get("grading_company") or "").strip()
    grade = _grade_key(item.get("grade"))
    if grader or grade:
        grader_id = _GRADER_IDS.get(grader.upper())
        grade_id = _GRADE_IDS.get(grade)
        if not grader_id or not grade_id:
            raise HTTPException(
                status_code=409,
                detail="This graded card needs a supported eBay grader/grade mapping before listing",
            )
        descriptors: list[dict[str, Any]] = [
            {"name": "27501", "values": [grader_id]},
            {"name": "27502", "values": [grade_id]},
        ]
        certificate = str(item.get("certificate_number") or "").strip()
        if certificate:
            descriptors.append({"name": "27503", "additionalInfo": certificate[:30]})
        return "LIKE_NEW", descriptors

    if item.get("condition") != "Near Mint":
        raise HTTPException(
            status_code=409,
            detail="eBay v1 only publishes raw cards verified as Near Mint",
        )
    return "USED_VERY_GOOD", [{"name": "40001", "values": ["400010"]}]


def _ebay_title(item: dict[str, Any]) -> str:
    language = str(item.get("language") or "").strip()
    grade = str(item.get("grade") or "").strip()
    grader = str(item.get("grading_company") or "").strip()
    condition = f"{grader} {grade}".strip() if grade else "Near Mint"
    parts = [
        str(item.get("name") or "").strip(),
        str(item.get("card_number") or "").strip(),
        str(item.get("set_name") or "").strip(),
        language,
        condition,
    ]
    title = " | ".join(part for part in parts if part)
    return title[:80].rstrip(" |")


def _ebay_description(item: dict[str, Any]) -> str:
    facts = [
        f"Card: {item.get('name') or ''}",
        f"Set: {item.get('set_name') or ''}",
        f"Card number: {item.get('card_number') or ''}",
        f"Language: {item.get('language') or ''}",
        f"Inventory ID: {item.get('inventory_code') or ''}",
    ]
    if item.get("grade"):
        facts.extend([
            f"Grader: {item.get('grading_company') or ''}",
            f"Grade: {item.get('grade') or ''}",
            f"Certification: {item.get('certificate_number') or 'Not recorded'}",
        ])
    else:
        facts.append(f"Condition: {item.get('condition') or ''}")
    return "\n".join(facts)


def _ebay_aspects(item: dict[str, Any]) -> dict[str, list[str]]:
    rows = {
        "Game": item.get("game"),
        "Card Name": item.get("name"),
        "Set": item.get("set_name"),
        "Card Number": item.get("card_number"),
        "Language": item.get("language"),
        "Rarity": item.get("rarity"),
    }
    return {
        key: [str(value).strip()]
        for key, value in rows.items()
        if value is not None and str(value).strip()
    }


def _inventory_payload(
    item: dict[str, Any],
    *,
    image_urls: list[str],
) -> dict[str, Any]:
    condition, descriptors = _condition_payload(item)
    return {
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
        "condition": condition,
        "conditionDescriptors": descriptors,
        "product": {
            "title": _ebay_title(item),
            "description": _ebay_description(item),
            "aspects": _ebay_aspects(item),
            "imageUrls": image_urls,
        },
    }


def _offer_payload(
    *,
    sku: str,
    price_minor: int,
    settings: Settings,
) -> dict[str, Any]:
    return {
        "sku": sku,
        "marketplaceId": settings.ebay_marketplace_id,
        "format": "FIXED_PRICE",
        "availableQuantity": 1,
        "categoryId": EBAY_GB_CCG_SINGLE_CATEGORY_ID,
        "merchantLocationKey": settings.ebay_merchant_location_key,
        "listingPolicies": {
            "paymentPolicyId": settings.ebay_payment_policy_id,
            "fulfillmentPolicyId": settings.ebay_fulfillment_policy_id,
            "returnPolicyId": settings.ebay_return_policy_id,
        },
        "pricingSummary": {
            "price": {"currency": "GBP", "value": _money_value(price_minor)}
        },
        "listingDuration": "GTC",
    }


def _offer_listing_id(offer: dict[str, Any]) -> str | None:
    listing = offer.get("listing")
    if isinstance(listing, dict):
        value = str(listing.get("listingId") or "").strip()
        if value:
            return value
    value = str(offer.get("listingId") or "").strip()
    return value or None


async def _validate_seller_prerequisites(client: EbaySellClient, settings: Settings) -> None:
    location, payment, fulfillment, returns = await asyncio.gather(
        client.get_inventory_location(settings.ebay_merchant_location_key or ""),
        client.get_payment_policy(settings.ebay_payment_policy_id or ""),
        client.get_fulfillment_policy(settings.ebay_fulfillment_policy_id or ""),
        client.get_return_policy(settings.ebay_return_policy_id or ""),
    )
    if str(location.get("locationStatus") or "ENABLED").upper() == "DISABLED":
        raise EbaySellApiError("Configured eBay inventory location is disabled")
    if payment.get("marketplaceId") not in {None, settings.ebay_marketplace_id}:
        raise EbaySellApiError("Configured eBay payment policy belongs to another marketplace")
    if fulfillment.get("marketplaceId") not in {None, settings.ebay_marketplace_id}:
        raise EbaySellApiError("Configured eBay fulfillment policy belongs to another marketplace")
    if returns.get("marketplaceId") not in {None, settings.ebay_marketplace_id}:
        raise EbaySellApiError("Configured eBay return policy belongs to another marketplace")
    if payment.get("immediatePay") is not True:
        raise EbaySellApiError(
            "Drop Rate requires an eBay payment policy with immediate payment enabled"
        )


async def _load_listing_plan(
    request: Request,
    user: AuthenticatedUser,
    inventory_id: UUID,
    expected_version: int,
    settings: Settings,
) -> dict[str, Any]:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        item = await connection.fetchrow(
            """
            select i.id, i.inventory_code, i.owner_id, i.acquisition_cost_minor,
                   i.currency, i.condition, i.grading_company, i.grade,
                   i.certificate_number, i.language, i.storage_location_id,
                   i.store_price_minor, i.identity_confirmed, i.status, i.version,
                   i.condition_review_status,
                   p.product_type, p.game, p.name, p.set_name, p.card_number,
                   p.variant, p.rarity
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id = i.catalogue_id
            where i.id = $1 and i.owner_id = $2
            for update of i
            """,
            inventory_id,
            owner["id"],
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        row = dict(item)
        if row["version"] != expected_version:
            raise HTTPException(status_code=409, detail="Inventory changed; refresh and try again")
        blockers: list[str] = []
        if row["product_type"] != "CARD":
            blockers.append("eBay v1 supports individual cards only")
        if row["status"] != "APPROVED":
            blockers.append("inventory must be APPROVED")
        if not row["identity_confirmed"]:
            blockers.append("identity must be confirmed")
        if not row["language"]:
            blockers.append("language is required")
        if row["acquisition_cost_minor"] is None:
            blockers.append("acquisition cost is required")
        if row["store_price_minor"] is None:
            blockers.append("Store Price is required")
        if row["storage_location_id"] is None:
            blockers.append("registered storage location is required")
        graded = bool(row["grade"] or row["grading_company"])
        required_condition = "VERIFIED_GRADED" if graded else "VERIFIED_NEAR_MINT"
        if row["condition_review_status"] != required_condition:
            blockers.append("photo-backed condition verification is required")
        if not graded and row["condition"] != "Near Mint":
            blockers.append("raw-card eBay v1 requires Near Mint")
        profile_key = "GRADED_CARD" if graded else "RAW_CARD"
        shipping_ready = await connection.fetchval(
            """
            select exists(
              select 1 from tcg.shopify_shipping_profiles
              where owner_id=$1 and profile_key=$2 and active
            )
            """,
            owner["id"],
            profile_key,
        )
        if not shipping_ready:
            blockers.append(f"{profile_key} shipping profile is required")

        media_rows = await connection.fetch(
            """
            select side, shopify_cdn_url
            from tcg.media_assets
            where owner_id=$1
              and inventory_id=$2
              and scope='INVENTORY_ITEM'
              and media_kind='IMAGE'
              and side in ('FRONT','BACK')
              and rights_status='VERIFIED'
              and approval_status='APPROVED'
              and shopify_file_status='READY'
              and shopify_cdn_url is not null
            order by case side when 'FRONT' then 1 when 'BACK' then 2 else 3 end
            """,
            owner["id"],
            inventory_id,
        )
        media = {str(media["side"]): str(media["shopify_cdn_url"]) for media in media_rows}
        if "FRONT" not in media or "BACK" not in media:
            blockers.append("approved FRONT + BACK physical photos are required")
        if blockers:
            raise HTTPException(status_code=409, detail={"blockers": blockers})

        price_minor = _channel_price(int(row["store_price_minor"]), settings.ebay_price_markup_bps)
        existing = await connection.fetchrow(
            "select * from tcg.ebay_inventory_links where inventory_id=$1 for update",
            inventory_id,
        )
        if existing and existing["state"] == "SOLD":
            raise HTTPException(status_code=409, detail="eBay link is already sold")
        if existing and existing["state"] == "LIVE":
            return {
                "already_live": True,
                "link": dict(existing),
                "owner_id": owner["id"],
                "item": row,
            }

        link = await connection.fetchrow(
            """
            insert into tcg.ebay_inventory_links(
                inventory_id, owner_id, created_by_user_id, sku, marketplace_id,
                category_id, state, listed_price_minor, currency, markup_bps,
                inventory_version_snapshot, last_error_code
            ) values ($1,$2,$3,$4,$5,$6,'PUBLISHING',$7,'GBP',$8,$9,null)
            on conflict (inventory_id) do update
            set state='PUBLISHING',
                listed_price_minor=excluded.listed_price_minor,
                markup_bps=excluded.markup_bps,
                inventory_version_snapshot=excluded.inventory_version_snapshot,
                last_error_code=null,
                version=tcg.ebay_inventory_links.version+1,
                updated_at=clock_timestamp()
            returning *
            """,
            inventory_id, owner["id"], user.user_id, row["inventory_code"],
            settings.ebay_marketplace_id, EBAY_GB_CCG_SINGLE_CATEGORY_ID,
            price_minor, settings.ebay_price_markup_bps, row["version"],
        )
        await connection.execute(
            """
            insert into tcg.marketplace_audit_events(
              owner_id, actor_user_id, action, entity_type, entity_id, new_values, notes
            ) values ($1,$2,'EBAY_PUBLISH_STARTED','EBAY_INVENTORY_LINK',$3,$4::jsonb,$5)
            """,
            owner["id"], user.user_id, link["id"],
            json.dumps({"inventory_id": str(inventory_id), "price_minor": price_minor}),
            "Single-item eBay publish requested from Founder HQ",
        )
        return {
            "already_live": False,
            "link": dict(link),
            "owner_id": owner["id"],
            "item": row,
            "image_urls": [media["FRONT"], media["BACK"]],
            "price_minor": price_minor,
        }


async def _mark_link_error(pool: Any, link_id: UUID, code: str) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            """
            update tcg.ebay_inventory_links
            set state='ERROR', last_error_code=$2, version=version+1,
                updated_at=clock_timestamp()
            where id=$1
            """,
            link_id, code[:120],
        )


@router.get("/seller-status")
async def seller_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    settings = get_settings()
    missing = _seller_config_missing(settings, include_publish_gate=True)
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        await _owner(connection)
    result: dict[str, Any] = {
        "marketplace_id": settings.ebay_marketplace_id,
        "configured": not missing,
        "missing": missing,
        "publish_enabled": settings.ebay_publish_enabled,
        "price_markup_bps": settings.ebay_price_markup_bps,
        "category_id": EBAY_GB_CCG_SINGLE_CATEGORY_ID,
        "scope": "individual CCG cards only",
        "live_verified": False,
    }
    if missing:
        return result
    try:
        client = _client(settings)
        await _validate_seller_prerequisites(client, settings)
        await client.user_access_token()
        scopes = client.granted_scopes
        result["granted_scopes"] = sorted(scopes)
        result["live_verified"] = (
            EBAY_INVENTORY_SCOPE in scopes
            and EBAY_FULFILLMENT_SCOPE in scopes
        )
        if not result["live_verified"]:
            result["warning"] = "Seller token is missing required Inventory/Fulfillment scopes"
    except (EbaySellApiError, RuntimeError, ValueError) as exc:
        result["warning"] = getattr(exc, "detail", str(exc))
    return result


@router.post("/listings/{inventory_id}")
async def publish_inventory_to_ebay(
    inventory_id: UUID,
    payload: EbayListRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    settings = get_settings()
    missing = _seller_config_missing(settings, include_publish_gate=True)
    if missing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "eBay seller connection is not ready",
                "missing": missing,
            },
        )

    plan = await _load_listing_plan(request, user, inventory_id, payload.version, settings)
    if plan["already_live"]:
        return jsonable_encoder({"status": "LIVE", **plan["link"], "idempotent": True})

    link_id = plan["link"]["id"]
    item = plan["item"]
    client = _client(settings)
    try:
        await _validate_seller_prerequisites(client, settings)
        await client.put_inventory_item(
            item["inventory_code"],
            _inventory_payload(item, image_urls=plan["image_urls"]),
        )
        offer_payload = _offer_payload(
            sku=item["inventory_code"],
            price_minor=plan["price_minor"],
            settings=settings,
        )
        offer_id = str(plan["link"].get("offer_id") or "").strip()
        if not offer_id:
            offers = await client.get_offers(sku=item["inventory_code"])
            matching = [
                offer for offer in offers
                if str(offer.get("marketplaceId") or "") == settings.ebay_marketplace_id
            ]
            if len(matching) > 1:
                raise EbaySellApiError("Multiple eBay offers already exist for this Drop Rate SKU")
            if matching:
                offer_id = str(matching[0].get("offerId") or "").strip()
            if not offer_id:
                offer_id = await client.create_offer(offer_payload)
            else:
                await client.update_offer(offer_id, offer_payload)
        else:
            await client.update_offer(offer_id, offer_payload)

        offer = await client.get_offer(offer_id)
        listing_id = _offer_listing_id(offer)
        if not listing_id:
            listing_id = await client.publish_offer(offer_id)
        verified_offer = await client.get_offer(offer_id)
        verified_listing_id = _offer_listing_id(verified_offer)
        if not verified_listing_id or verified_listing_id != listing_id:
            raise EbaySellApiError("eBay listing publication could not be verified")
    except (EbaySellApiError, ValueError) as exc:
        await _mark_link_error(
            request.app.state.db_pool,
            link_id,
            f"PUBLISH:{getattr(exc, 'status_code', None) or 'FAILED'}",
        )
        raise HTTPException(
            status_code=502 if getattr(exc, "retryable", False) else 409,
            detail=getattr(exc, "detail", str(exc)),
        ) from exc

    stale = False
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        current = await connection.fetchrow(
            "select status, version from tcg.inventory_items where id=$1 and owner_id=$2 for update",
            inventory_id, owner["id"],
        )
        link = await connection.fetchrow(
            "select * from tcg.ebay_inventory_links where id=$1 and owner_id=$2 for update",
            link_id, owner["id"],
        )
        if current is None or link is None:
            stale = True
        elif (
            current["status"] != "APPROVED"
            or current["version"] != plan["link"]["inventory_version_snapshot"]
        ):
            stale = True
            await connection.execute(
                """
                update tcg.ebay_inventory_links
                set state='ERROR', offer_id=$2, listing_id=$3,
                    last_error_code='INVENTORY_CHANGED_DURING_PUBLISH',
                    version=version+1, updated_at=clock_timestamp()
                where id=$1
                """,
                link_id, offer_id, listing_id,
            )
        else:
            link = await connection.fetchrow(
                """
                update tcg.ebay_inventory_links
                set state='LIVE', offer_id=$2, listing_id=$3,
                    published_at=coalesce(published_at,clock_timestamp()),
                    last_verified_at=clock_timestamp(), last_error_code=null,
                    withdrawal_reason=null, version=version+1,
                    updated_at=clock_timestamp()
                where id=$1
                returning *
                """,
                link_id, offer_id, listing_id,
            )
            await connection.execute(
                """
                insert into tcg.marketplace_audit_events(
                  owner_id, actor_user_id, action, entity_type, entity_id, new_values, notes
                ) values ($1,$2,'EBAY_PUBLISHED','EBAY_INVENTORY_LINK',$3,$4::jsonb,$5)
                """,
                owner["id"], user.user_id, link_id,
                json.dumps({"offer_id": offer_id, "listing_id": listing_id}),
                "eBay publication verified after remote read-back",
            )
    if stale:
        try:
            await client.withdraw_offer(offer_id)
        except EbaySellApiError:
            logger.exception("Failed to withdraw stale eBay publication for link %s", link_id)
        raise HTTPException(
            status_code=409,
            detail="Inventory changed while eBay was publishing; listing was withdrawn or flagged for review",
        )
    return jsonable_encoder({"status": "LIVE", **dict(link), "idempotent": False})


async def _links_for_inventory(pool: Any, inventory_ids: list[str]) -> list[dict[str, Any]]:
    if not inventory_ids:
        return []
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            select * from tcg.ebay_inventory_links
            where inventory_id = any($1::uuid[])
              and state in ('LIVE','WITHDRAWN','ERROR')
            order by created_at
            """,
            inventory_ids,
        )
    return [dict(row) for row in rows]


async def withdraw_ebay_for_inventory(
    pool: Any,
    inventory_ids: list[str],
    *,
    reason: str,
) -> None:
    links = await _links_for_inventory(pool, inventory_ids)
    live = [link for link in links if link["state"] == "LIVE"]
    if not live:
        return
    settings = get_settings()
    if _seller_config_missing(settings, include_publish_gate=False):
        for link in live:
            await _mark_link_error(pool, link["id"], "CROSS_CHANNEL_EBAY_AUTH_MISSING")
        raise EbaySellApiError("Cannot withdraw live eBay listing: seller authorisation is missing")
    client = _client(settings)
    for link in live:
        try:
            await client.withdraw_offer(str(link["offer_id"]))
            offer = await client.get_offer(str(link["offer_id"]))
            if _offer_listing_id(offer):
                raise EbaySellApiError("eBay offer still appears published after withdrawal")
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    update tcg.ebay_inventory_links
                    set state='WITHDRAWN', withdrawal_reason=$2,
                        withdrawn_at=clock_timestamp(), last_verified_at=clock_timestamp(),
                        last_error_code=null, version=version+1,
                        updated_at=clock_timestamp()
                    where id=$1
                    """,
                    link["id"], reason,
                )
        except EbaySellApiError as exc:
            await _mark_link_error(pool, link["id"], f"CROSS_CHANNEL:{reason}")
            raise exc


async def restore_ebay_after_shopify_release(pool: Any, inventory_ids: list[str]) -> None:
    links = await _links_for_inventory(pool, inventory_ids)
    candidates = [
        link for link in links
        if link["state"] == "WITHDRAWN" and link.get("withdrawal_reason") == "SHOPIFY_RESERVED"
    ]
    if not candidates:
        return
    settings = get_settings()
    if _seller_config_missing(settings, include_publish_gate=False):
        for link in candidates:
            await _mark_link_error(pool, link["id"], "RESTORE_EBAY_AUTH_MISSING")
        raise EbaySellApiError("Cannot restore eBay listing: seller authorisation is missing")
    client = _client(settings)
    for link in candidates:
        async with pool.acquire() as connection:
            item_status = await connection.fetchval(
                "select status from tcg.inventory_items where id=$1",
                link["inventory_id"],
            )
        if item_status != "APPROVED":
            continue
        try:
            listing_id = await client.publish_offer(str(link["offer_id"]))
            offer = await client.get_offer(str(link["offer_id"]))
            verified = _offer_listing_id(offer)
            if not verified or verified != listing_id:
                raise EbaySellApiError("Restored eBay offer could not be verified")
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    update tcg.ebay_inventory_links
                    set state='LIVE', listing_id=$2, withdrawal_reason=null,
                        withdrawn_at=null, last_verified_at=clock_timestamp(),
                        last_error_code=null, version=version+1,
                        updated_at=clock_timestamp()
                    where id=$1
                    """,
                    link["id"], verified,
                )
        except EbaySellApiError as exc:
            await _mark_link_error(pool, link["id"], "RESTORE_AFTER_SHOPIFY_RELEASE")
            raise exc


async def sync_ebay_after_shopify_result(pool: Any, result: dict[str, Any]) -> None:
    action = str(result.get("action") or "")
    items = result.get("items") or []
    inventory_ids = [
        str(item.get("inventory_id"))
        for item in items
        if isinstance(item, dict) and item.get("inventory_id")
    ]
    if not inventory_ids:
        return
    if action in {
        "PENDING_ORDER_RESERVED",
        "PENDING_ORDER_ALREADY_RESERVED",
    }:
        await withdraw_ebay_for_inventory(pool, inventory_ids, reason="SHOPIFY_RESERVED")
    elif action in {"PAID_ORDER_RECORDED", "ORDER_ALREADY_RECORDED", "ORDER_ALREADY_FINALIZED"}:
        await withdraw_ebay_for_inventory(pool, inventory_ids, reason="SHOPIFY_SOLD")
    elif action == "PENDING_ORDER_RELEASED":
        await restore_ebay_after_shopify_release(pool, inventory_ids)


def _decode_signature_header(value: str) -> tuple[str, bytes]:
    try:
        decoded = base64.b64decode(value.strip(), validate=True)
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid eBay signature header") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid eBay signature header")
    kid = str(payload.get("kid") or "").strip()
    signature_text = str(payload.get("signature") or "").strip()
    if not kid or not signature_text:
        raise ValueError("Incomplete eBay signature header")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid eBay signature bytes") from exc
    return kid, signature


def _hash_algorithm(name: object) -> hashes.HashAlgorithm:
    value = str(name or "").replace("-", "").upper()
    mapping: dict[str, hashes.HashAlgorithm] = {
        "SHA1": hashes.SHA1(),
        "SHA256": hashes.SHA256(),
        "SHA384": hashes.SHA384(),
        "SHA512": hashes.SHA512(),
    }
    if value not in mapping:
        raise ValueError("Unsupported eBay notification digest")
    return mapping[value]


def verify_ebay_notification_signature(
    payload: dict[str, Any],
    signature_header: str,
    public_key_payload: dict[str, Any],
) -> bool:
    kid, signature = _decode_signature_header(signature_header)
    returned_kid = str(
        public_key_payload.get("keyId")
        or public_key_payload.get("kid")
        or kid
    ).strip()
    if returned_kid != kid:
        return False
    key_text = str(public_key_payload.get("key") or "").strip()
    if not key_text:
        return False
    try:
        if "BEGIN PUBLIC KEY" in key_text:
            public_key = serialization.load_pem_public_key(key_text.encode("ascii"))
        else:
            public_key = serialization.load_der_public_key(base64.b64decode(key_text))
    except (ValueError, TypeError):
        return False

    message = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    try:
        digest = _hash_algorithm(public_key_payload.get("digest"))
    except ValueError:
        return False
    algorithm = str(public_key_payload.get("algorithm") or "").upper()
    try:
        if isinstance(public_key, ec.EllipticCurvePublicKey) or "EC" in algorithm:
            public_key.verify(signature, message, ec.ECDSA(digest))
        elif isinstance(public_key, rsa.RSAPublicKey) or "RSA" in algorithm:
            public_key.verify(signature, message, padding.PKCS1v15(), digest)
        else:
            return False
    except Exception:
        return False
    return True


def _notification_identity(payload: dict[str, Any]) -> tuple[str, str]:
    metadata = payload.get("metadata")
    notification = payload.get("notification")
    if not isinstance(metadata, dict) or not isinstance(notification, dict):
        raise HTTPException(status_code=400, detail="Invalid eBay notification envelope")
    topic = str(metadata.get("topic") or "").strip()
    notification_id = str(notification.get("notificationId") or "").strip()
    if topic != "ORDER_CONFIRMATION" or not notification_id:
        raise HTTPException(status_code=400, detail="Unsupported eBay notification")
    return notification_id, topic


def _notification_order_id(payload: dict[str, Any]) -> str:
    notification = payload.get("notification")
    data = notification.get("data") if isinstance(notification, dict) else None
    order = data.get("order") if isinstance(data, dict) else None
    order_id = str(order.get("orderId") or "").strip() if isinstance(order, dict) else ""
    if not order_id:
        raise HTTPException(status_code=400, detail="eBay notification is missing orderId")
    return order_id


def _order_line_rows(order: dict[str, Any]) -> list[dict[str, Any]]:
    lines = order.get("lineItems")
    if not isinstance(lines, list) or not lines:
        raise ValueError("eBay order has no line items")
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            raise ValueError("eBay order line is invalid")
        listing_id = str(
            line.get("legacyItemId")
            or line.get("listingId")
            or ""
        ).strip()
        line_item_id = str(line.get("lineItemId") or "").strip()
        quantity = int(line.get("quantity") or 0)
        money = line.get("lineItemCost")
        if not listing_id or not line_item_id or quantity != 1 or not isinstance(money, dict):
            raise ValueError("eBay v1 requires one physical unit per order line")
        rows.append({
            "listing_id": listing_id,
            "line_item_id": line_item_id,
            "quantity": quantity,
            "sale_price_minor": _parse_money_minor(money.get("value"), money.get("currency")),
        })
    return rows


def _allocate_minor(total: int, weights: list[int]) -> list[int]:
    if not weights:
        return []
    if total == 0:
        return [0] * len(weights)
    weight_total = sum(weights)
    if weight_total <= 0:
        base, remainder = divmod(total, len(weights))
        return [base + (1 if index < remainder else 0) for index in range(len(weights))]
    raw = [total * weight // weight_total for weight in weights]
    remainder = total - sum(raw)
    for index in range(remainder):
        raw[index % len(raw)] += 1
    return raw


async def _record_ebay_order(pool: Any, order: dict[str, Any]) -> dict[str, Any]:
    order_id = str(order.get("orderId") or "").strip()
    if not order_id:
        raise ValueError("eBay order response is missing orderId")
    if str(order.get("paymentMethod") or "").upper() != "EBAY":
        raise ValueError(
            "eBay v1 only records orders paid through eBay managed payments"
        )
    lines = _order_line_rows(order)
    pricing = order.get("pricingSummary")
    delivery = pricing.get("deliveryCost") if isinstance(pricing, dict) else None
    shipping_total = (
        _parse_money_minor(delivery.get("value"), delivery.get("currency"))
        if isinstance(delivery, dict) else 0
    )
    shipping_allocations = _allocate_minor(
        shipping_total, [line["sale_price_minor"] for line in lines]
    )
    created_at = str(order.get("creationDate") or "").strip()
    try:
        placed_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        placed_at = datetime.now(timezone.utc)

    async with pool.acquire() as connection:
        async with connection.transaction():
            existing = await connection.fetchrow(
                "select id from tcg.orders where source='EBAY' and source_reference=$1",
                order_id,
            )
            if existing:
                rows = await connection.fetch(
                    """
                    select oi.inventory_id
                    from tcg.order_items oi
                    where oi.order_id=$1
                    order by oi.created_at
                    """,
                    existing["id"],
                )
                return {
                    "action": "ORDER_ALREADY_RECORDED",
                    "order_id": str(existing["id"]),
                    "inventory_ids": [str(row["inventory_id"]) for row in rows],
                }

            listing_ids = [line["listing_id"] for line in lines]
            links = await connection.fetch(
                """
                select eil.*, i.status as inventory_status, i.acquisition_cost_minor,
                       i.version as inventory_version
                from tcg.ebay_inventory_links eil
                join tcg.inventory_items i on i.id=eil.inventory_id
                where eil.listing_id = any($1::text[])
                for update of eil, i
                """,
                listing_ids,
            )
            by_listing = {str(link["listing_id"]): link for link in links}
            if len(by_listing) != len(set(listing_ids)):
                raise ValueError("eBay order contains a listing not managed by Drop Rate")

            owner_ids = {link["owner_id"] for link in links}
            if len(owner_ids) != 1:
                raise ValueError("eBay v1 order spans multiple owners")
            owner_id = next(iter(owner_ids))
            actor_user_id = links[0]["created_by_user_id"]
            await connection.execute(
                "select set_config('tcg.user_id',$1,true)",
                str(actor_user_id),
            )
            await connection.execute(
                "select set_config('tcg.request_id',$1,true)",
                f"ebay:{order_id}",
            )

            for line in lines:
                link = by_listing[line["listing_id"]]
                status = str(link["inventory_status"])
                if status != "APPROVED":
                    raise EbayChannelConflict(link["id"], status)

            internal_order = await connection.fetchrow(
                """
                insert into tcg.orders(
                  source,source_reference,order_number,currency,status,placed_at
                ) values ('EBAY',$1,$2,'GBP','PAID',$3)
                returning id
                """,
                order_id, order_id, placed_at,
            )
            inventory_ids: list[str] = []
            for index, line in enumerate(lines):
                link = by_listing[line["listing_id"]]
                item = await connection.fetchrow(
                    """
                    update tcg.inventory_items
                    set status='SOLD', version=version+1, updated_at=clock_timestamp()
                    where id=$1 and status='APPROVED'
                    returning id, acquisition_cost_minor
                    """,
                    link["inventory_id"],
                )
                if item is None:
                    raise EbayChannelConflict(link["id"], "CONCURRENT_CHANGE")
                order_item = await connection.fetchrow(
                    """
                    insert into tcg.order_items(
                      order_id,inventory_id,owner_id,sale_price_minor,discount_minor,
                      cost_basis_minor,sold_at
                    ) values ($1,$2,$3,$4,0,$5,$6)
                    returning id
                    """,
                    internal_order["id"], link["inventory_id"], owner_id,
                    line["sale_price_minor"], item["acquisition_cost_minor"], placed_at,
                )
                await connection.execute(
                    """
                    insert into tcg.ebay_order_item_links(
                      order_id,order_item_id,inventory_id,owner_id,created_by_user_id,
                      ebay_order_id,ebay_line_item_id,ebay_listing_id
                    ) values ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    internal_order["id"], order_item["id"], link["inventory_id"], owner_id,
                    actor_user_id, order_id, line["line_item_id"], line["listing_id"],
                )
                await connection.execute(
                    """
                    insert into tcg.financial_ledger_entries(
                      owner_id,order_id,order_item_id,entry_type,amount_minor,currency,
                      funds_status,source_key
                    ) values ($1,$2,$3,'SALE_REVENUE',$4,'GBP','PENDING',$5)
                    """,
                    owner_id, internal_order["id"], order_item["id"],
                    line["sale_price_minor"],
                    f"ebay:{order_id}:{line['line_item_id']}:sale",
                )
                shipping_share = shipping_allocations[index]
                if shipping_share:
                    await connection.execute(
                        """
                        insert into tcg.financial_ledger_entries(
                          owner_id,order_id,order_item_id,entry_type,amount_minor,currency,
                          funds_status,source_key
                        ) values ($1,$2,$3,'SHIPPING_REVENUE',$4,'GBP','PENDING',$5)
                        """,
                        owner_id, internal_order["id"], order_item["id"], shipping_share,
                        f"ebay:{order_id}:{line['line_item_id']}:shipping",
                    )
                await connection.execute(
                    """
                    update tcg.ebay_inventory_links
                    set state='SOLD', sold_at=clock_timestamp(),
                        last_verified_at=clock_timestamp(), last_error_code=null,
                        version=version+1, updated_at=clock_timestamp()
                    where id=$1
                    """,
                    link["id"],
                )
                await connection.execute(
                    """
                    update tcg.shopify_inventory_links
                    set sync_state='SOLD', sold_at=coalesce(sold_at,clock_timestamp()),
                        version=version+1, last_synced_at=clock_timestamp()
                    where inventory_id=$1 and sync_state in ('DRAFT','PUBLISHED','ERROR')
                    """,
                    link["inventory_id"],
                )
                inventory_ids.append(str(link["inventory_id"]))
            return {
                "action": "EBAY_ORDER_RECORDED",
                "order_id": str(internal_order["id"]),
                "inventory_ids": inventory_ids,
            }


async def _zero_shopify_for_ebay_sale(pool: Any, inventory_ids: list[str]) -> None:
    if not inventory_ids:
        return
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            select inventory_id, shopify_product_gid, shopify_inventory_item_gid,
                   shopify_location_gid
            from tcg.shopify_inventory_links
            where inventory_id=any($1::uuid[])
              and shopify_product_gid is not null
              and shopify_inventory_item_gid is not null
              and shopify_location_gid is not null
            """,
            inventory_ids,
        )
    if not rows:
        return
    settings = get_settings()
    client = _shopify_client(settings)
    if client is None:
        raise ShopifyApiError("Shopify connection is missing while eBay stock is live")
    for row in rows:
        key = f"ebay-sale-{str(row['inventory_id'])}"
        await client.set_inventory_quantity(
            inventory_item_id=str(row["shopify_inventory_item_gid"]),
            location_id=str(row["shopify_location_gid"]),
            quantity=0,
            idempotency_key=key,
        )
        await client.set_product_status(
            product_id=str(row["shopify_product_gid"]),
            status="DRAFT",
        )
        snapshot = await client.get_product_snapshot(str(row["shopify_product_gid"]))
        variants = snapshot.get("variants", {}).get("nodes", [])
        quantity = variants[0].get("inventoryQuantity") if len(variants) == 1 else None
        if snapshot.get("status") != "DRAFT" or quantity != 0:
            raise ShopifyApiError("Shopify cross-channel stock removal could not be verified")


@router.post("/order-notifications", status_code=204)
async def ebay_order_notification(
    request: Request,
    x_ebay_signature: str | None = Header(default=None, alias="X-EBAY-SIGNATURE"),
) -> Response:
    settings = get_settings()
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        raise HTTPException(status_code=503, detail="eBay application credentials are missing")
    body = await request.body()
    if not body or len(body) > MAX_NOTIFICATION_BYTES:
        raise HTTPException(status_code=413, detail="Invalid eBay notification size")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid eBay notification JSON") from exc
    if not isinstance(payload, dict) or not x_ebay_signature:
        raise HTTPException(status_code=401, detail="Missing eBay notification signature")
    notification_id, topic = _notification_identity(payload)
    order_id = _notification_order_id(payload)

    if not settings.ebay_user_refresh_token:
        raise HTTPException(status_code=503, detail="eBay seller authorisation is missing")
    client = _client(settings)
    try:
        kid, _ = _decode_signature_header(x_ebay_signature)
        key = await client.get_public_key(kid)
    except (ValueError, EbaySellApiError) as exc:
        raise HTTPException(status_code=401, detail="eBay notification signature cannot be verified") from exc
    if not verify_ebay_notification_signature(payload, x_ebay_signature, key):
        raise HTTPException(status_code=401, detail="Invalid eBay notification signature")

    payload_hash = hashlib.sha256(body).hexdigest()
    async with request.app.state.db_pool.acquire() as connection:
        existing = await connection.fetchrow(
            "select payload_sha256,status from tcg.ebay_webhook_events where notification_id=$1",
            notification_id,
        )
        if existing:
            if existing["payload_sha256"] != payload_hash:
                raise HTTPException(status_code=409, detail="eBay notification ID payload mismatch")
            if existing["status"] == "PROCESSED":
                return Response(status_code=204)
            await connection.execute(
                """
                update tcg.ebay_webhook_events
                set status='RECEIVED', last_error_code=null, received_at=clock_timestamp()
                where notification_id=$1
                """,
                notification_id,
            )
        else:
            await connection.execute(
                """
                insert into tcg.ebay_webhook_events(
                  notification_id,topic,order_id,payload_sha256,status
                ) values ($1,$2,$3,$4,'RECEIVED')
                """,
                notification_id, topic, order_id, payload_hash,
            )

    try:
        order = await client.get_order(order_id)
        result = await _record_ebay_order(request.app.state.db_pool, order)
        await _zero_shopify_for_ebay_sale(
            request.app.state.db_pool, result["inventory_ids"]
        )
    except EbayChannelConflict as exc:
        async with request.app.state.db_pool.acquire() as connection:
            await connection.execute(
                """
                update tcg.ebay_inventory_links
                set state='ERROR', last_error_code=$2,
                    version=version+1, updated_at=clock_timestamp()
                where id=$1
                """,
                exc.link_id, f"CHANNEL_CONFLICT_{exc.status}"[:120],
            )
            await connection.execute(
                """
                update tcg.ebay_webhook_events
                set status='FAILED', last_error_code='CHANNEL_CONFLICT',
                    processed_at=clock_timestamp()
                where notification_id=$1
                """,
                notification_id,
            )
        raise HTTPException(
            status_code=409,
            detail="eBay order conflicts with an already reserved or sold physical item; Action Required",
        ) from exc
    except (EbaySellApiError, ShopifyApiError, ValueError) as exc:
        async with request.app.state.db_pool.acquire() as connection:
            await connection.execute(
                """
                update tcg.ebay_webhook_events
                set status='FAILED', last_error_code=$2, processed_at=clock_timestamp()
                where notification_id=$1
                """,
                notification_id, exc.__class__.__name__[:120],
            )
        raise HTTPException(
            status_code=502 if getattr(exc, "retryable", False) else 409,
            detail=str(getattr(exc, "detail", str(exc))),
        ) from exc

    async with request.app.state.db_pool.acquire() as connection:
        await connection.execute(
            """
            update tcg.ebay_webhook_events
            set status='PROCESSED', processed_at=clock_timestamp(), last_error_code=null
            where notification_id=$1
            """,
            notification_id,
        )
    return Response(status_code=204)
