from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Any, Mapping
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .brands import brand_for_game
from .db import user_connection
from .finance import allocate_minor
from .ownership import current_owner as _owner
from .settings import get_settings
from .shopify_completeness import (
    build_shopify_product_plan,
    media_completeness,
    product_completeness,
    product_create_input,
    product_title,
    verify_remote_product,
)
from .shopify_client import ShopifyAdminClient, ShopifyApiError


router = APIRouter(prefix="/api/v1/shopify", tags=["shopify"])


class ShopifyProcessingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TestSyncRequest(BaseModel):
    version: int = Field(ge=1)


class MediaAssetCreate(BaseModel):
    catalogue_id: UUID | None = None
    inventory_id: UUID | None = None
    side: str = Field(pattern="^(FRONT|BACK|OTHER)$")
    source_type: str = Field(
        pattern="^(FOUNDER_UPLOAD|CONSIGNOR_UPLOAD|LICENSED_PROVIDER|OFFICIAL_PROVIDER)$"
    )
    source_reference: str = Field(min_length=1, max_length=1000)
    public_source_url: str | None = Field(default=None, max_length=4000)
    rights_basis: str | None = Field(default=None, max_length=1000)
    alt_text: str = Field(default="", max_length=500)


class MediaAssetApprove(BaseModel):
    version: int = Field(ge=1)
    rights_basis: str = Field(min_length=1, max_length=1000)
    alt_text: str = Field(min_length=1, max_length=500)


class MediaAssetSync(BaseModel):
    version: int = Field(ge=1)


def _client() -> ShopifyAdminClient:
    settings = get_settings()
    if (
        not settings.shopify_shop_domain
        or not settings.shopify_client_id
        or not settings.shopify_client_secret
    ):
        raise HTTPException(status_code=409, detail="Shopify is not configured")
    return ShopifyAdminClient(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        api_version=settings.shopify_api_version,
    )


def _money(minor: int) -> str:
    return f"{Decimal(minor) / Decimal(100):.2f}"


def _minor(value: object, *, field: str) -> int:
    try:
        amount = Decimal(str(value or "0"))
    except InvalidOperation as exc:
        raise ShopifyProcessingError("INVALID_MONEY", f"Invalid Shopify {field}") from exc
    if amount < 0:
        raise ShopifyProcessingError("INVALID_MONEY", f"Negative Shopify {field}")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _refund_shipping_minor(payload: dict[str, Any]) -> int:
    lines = payload.get("refund_shipping_lines")
    if lines is None:
        return 0
    if not isinstance(lines, list):
        raise ShopifyProcessingError(
            "INVALID_REFUND_SHIPPING",
            "Shopify refund shipping lines are invalid",
        )

    total = 0
    for line in lines:
        if not isinstance(line, dict):
            raise ShopifyProcessingError(
                "INVALID_REFUND_SHIPPING",
                "Shopify refund shipping line is invalid",
            )
        amount_set = line.get("subtotal_amount_set")
        if not isinstance(amount_set, dict):
            raise ShopifyProcessingError(
                "INVALID_REFUND_SHIPPING",
                "Shopify refund shipping amount is missing",
            )
        shop_money = amount_set.get("shop_money")
        if not isinstance(shop_money, dict):
            raise ShopifyProcessingError(
                "INVALID_REFUND_SHIPPING",
                "Shopify refund shipping shop money is missing",
            )
        currency = str(shop_money.get("currency_code") or "").upper()
        if currency != "GBP":
            raise ShopifyProcessingError(
                "SHIPPING_REFUND_CURRENCY_MISMATCH",
                "Shopify shipping refund currency is not GBP",
            )
        total += _minor(shop_money.get("amount"), field="shipping refund")
    return total


def _parse_time(value: object) -> datetime:
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _variant_gid(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ShopifyProcessingError("MISSING_VARIANT", "Shopify line item has no variant ID")
    if text.startswith("gid://shopify/ProductVariant/"):
        return text
    if not text.isdigit():
        raise ShopifyProcessingError("INVALID_VARIANT", "Shopify variant ID is invalid")
    return f"gid://shopify/ProductVariant/{text}"


def _product_gid_matches(gid: str, value: object) -> bool:
    text = str(value or "").strip()
    return bool(text) and gid.rsplit("/", 1)[-1] == text


def _title(item: asyncpg.Record) -> str:
    return product_title(item)


def _handle(inventory_code: str) -> str:
    return f"drop-rate-{inventory_code.casefold().replace('_', '-').replace(' ', '-')}"


def _test_sync_missing(item: Any) -> list[str]:
    missing: list[str] = []
    if item["status"] != "APPROVED":
        missing.append("APPROVED status")
    if not item["identity_confirmed"]:
        missing.append("identity confirmation")
    if item["acquisition_cost_minor"] is None:
        missing.append("acquisition cost")

    if item["product_type"] == "CARD":
        is_graded = bool(
            str(item["grading_company"] or "").strip()
            and str(item["grade"] or "").strip()
        )
        if not is_graded and not str(item["condition"] or "").strip():
            missing.append("raw card condition")
        if not (item["language"] or item["catalogue_language"]):
            missing.append("card language")
    elif item["seal_status"] is None:
        missing.append("seal status")

    if item["store_price_minor"] is None:
        missing.append("store price")
    if item["storage_location_id"] is None:
        missing.append("registered storage location")
    elif (
        item["registered_location_id"] is None
        or not item["registered_location_active"]
    ):
        missing.append("active storage location")
    return missing


def _media_assets_for_item(
    item: Mapping[str, Any],
    assets: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    inventory_id = str(item.get("id") or "")
    catalogue_id = str(item.get("catalogue_id") or "")
    selected: list[Mapping[str, Any]] = []
    for asset in assets:
        scope = str(asset.get("scope") or "")
        if scope == "INVENTORY_ITEM" and str(asset.get("inventory_id") or "") == inventory_id:
            selected.append(asset)
        elif scope == "CANONICAL_CARD" and str(asset.get("catalogue_id") or "") == catalogue_id:
            selected.append(asset)
    return selected


def _launch_completeness(
    item: Any,
    *,
    collection_titles: set[str],
    publication_configured: bool,
    location_configured: bool,
    media_assets: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = build_shopify_product_plan(item)
    media = media_completeness(plan["mediaPolicy"], media_assets)
    completeness = product_completeness(
        plan,
        store_price_minor=item["store_price_minor"],
        inventory_code=item["inventory_code"],
        approved_media_count=media["approvedMediaCount"],
        existing_collection_titles=collection_titles,
        publication_configured=publication_configured,
        location_configured=location_configured,
        media_blockers=media["blockers"],
    )
    completeness["mediaReadiness"] = media
    return plan, completeness


async def _founder(connection: asyncpg.Connection) -> asyncpg.Record:
    owner = await _owner(connection)
    if owner["role"] != "FOUNDER":
        raise HTTPException(status_code=403, detail="Only a founder can run Shopify test sync")
    return owner


@router.get("/product-preview/{inventory_id}")
async def shopify_product_preview(
    inventory_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    client = _client()
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _founder(connection)
        item = await connection.fetchrow(
            """
            select
                i.*, p.product_type, p.game, p.name, p.set_name, p.card_number,
                p.variant, p.rarity, p.language as catalogue_language,
                sl.id as registered_location_id,
                sl.active as registered_location_active
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join tcg.storage_locations sl on sl.id=i.storage_location_id
            where i.id=$1 and i.owner_id=$2
            """,
            inventory_id, owner["id"],
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        try:
            collection_titles = await client.list_collection_titles()
        except ShopifyApiError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Could not verify Shopify collections",
                    "retryable": exc.retryable,
                },
            ) from exc

        plan, completeness = _launch_completeness(
            item,
            collection_titles=collection_titles,
            publication_configured=bool(settings.shopify_publication_gid),
            location_configured=bool(settings.shopify_location_gid),
        )
        operational_missing = _test_sync_missing(item)
        return jsonable_encoder({
            "inventory": {
                "id": item["id"],
                "inventory_code": item["inventory_code"],
                "version": item["version"],
                "status": item["status"],
                "name": item["name"],
                "store_price_minor": item["store_price_minor"],
            },
            "operationalReady": not operational_missing,
            "operationalBlockers": operational_missing,
            "launchReady": not operational_missing and completeness["complete"],
            "productPlan": plan,
            "productCompleteness": completeness,
            "shopifyCollections": sorted(collection_titles),
        })


@router.get("/test-sync")
async def test_sync_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    client = _client()
    try:
        collection_titles = await client.list_collection_titles()
    except ShopifyApiError:
        collection_titles = set()
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _founder(connection)
        pool = await connection.fetch(
            """
            select
                i.id, i.inventory_code, i.version, i.status,
                i.identity_confirmed, i.acquisition_cost_minor,
                i.store_price_minor, i.storage_location_id, i.language,
                i.condition, i.seal_status, i.grading_company, i.grade,
                p.product_type, p.game, p.name, p.set_name, p.card_number,
                p.variant, p.rarity, p.language as catalogue_language,
                sl.id as registered_location_id,
                sl.active as registered_location_active
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join tcg.storage_locations sl on sl.id=i.storage_location_id
            left join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
            left join tcg.listing_inventory_members lim
              on lim.inventory_id=i.id and lim.state <> 'REMOVED'
            where i.owner_id=$1
              and i.status in ('DRAFT','INSPECTION','APPROVED')
              and sil.id is null
              and lim.id is null
            order by i.updated_at, i.inventory_code
            """,
            owner["id"],
        )
        candidates: list[dict[str, Any]] = []
        blocked_items: list[dict[str, Any]] = []
        blocker_counts: dict[str, int] = {}
        eligible_count = 0
        launch_ready_count = 0
        launch_blocker_counts: dict[str, int] = {}
        for row in pool:
            missing = _test_sync_missing(row)
            _, launch = _launch_completeness(
                row,
                collection_titles=collection_titles,
                publication_configured=bool(settings.shopify_publication_gid),
                location_configured=bool(settings.shopify_location_gid),
            )
            if not missing:
                eligible_count += 1
                if launch["complete"]:
                    launch_ready_count += 1
                for blocker in launch["blockers"]:
                    launch_blocker_counts[blocker] = (
                        launch_blocker_counts.get(blocker, 0) + 1
                    )
                if len(candidates) < 25:
                    candidate = dict(row)
                    candidate["launch_ready"] = launch["complete"]
                    candidate["launch_blockers"] = launch["blockers"]
                    candidates.append(candidate)
                continue
            for blocker in missing:
                blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
            blocked_items.append({
                "id": row["id"],
                "inventory_code": row["inventory_code"],
                "name": row["name"],
                "card_number": row["card_number"],
                "variant": row["variant"],
                "status": row["status"],
                "missing": missing,
            })
        blocked_items.sort(
            key=lambda item: (len(item["missing"]), item["inventory_code"])
        )
        counts = await connection.fetchrow(
            """
            select
              count(*) filter(where test_mode and sync_state='PUBLISHED')::int as published_test,
              count(*) filter(where test_mode and sync_state='SOLD')::int as sold_test,
              count(*) filter(where test_mode and sync_state='ERROR')::int as error_test
            from tcg.shopify_inventory_links
            where owner_id=$1
            """,
            owner["id"],
        )
        return jsonable_encoder({
            "test_publish_enabled": settings.shopify_test_publish_enabled,
            "bulk_publish_enabled": settings.shopify_publish_enabled,
            "location_configured": bool(settings.shopify_location_gid),
            "publication_configured": bool(settings.shopify_publication_gid),
            "candidates": candidates,
            "readiness": {
                "considered": len(pool),
                "eligible": eligible_count,
                "blocked": len(pool) - eligible_count,
                "blockers": blocker_counts,
                "next_items": blocked_items[:10],
            },
            "launch_readiness": {
                "ready": launch_ready_count,
                "blocked": len(pool) - launch_ready_count,
                "blockers": launch_blocker_counts,
                "verified_collections": sorted(collection_titles),
                "media_registry_status": "NOT_BUILT_FAIL_CLOSED",
            },
            "counts": dict(counts),
        })


@router.post("/test-sync/{inventory_id}")
async def sync_one_test_item(
    inventory_id: UUID,
    payload: TestSyncRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    if not settings.shopify_test_publish_enabled:
        raise HTTPException(status_code=409, detail="Shopify single-item test publishing is locked off")
    if settings.shopify_publish_enabled:
        raise HTTPException(status_code=409, detail="Bulk Shopify publishing must remain disabled during test mode")
    if not settings.shopify_location_gid or not settings.shopify_publication_gid:
        raise HTTPException(status_code=409, detail="Shopify test location/publication is not configured")

    client = _client()
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _founder(connection)
        async with connection.transaction():
            item = await connection.fetchrow(
                """
                select
                    i.*, p.product_type, p.game, p.name, p.set_name, p.card_number,
                    p.variant, p.rarity, p.language as catalogue_language,
                    sl.id as registered_location_id, sl.active as registered_location_active
                from tcg.inventory_items i
                join tcg.catalogue_products p on p.id=i.catalogue_id
                left join tcg.storage_locations sl on sl.id=i.storage_location_id
                where i.id=$1 and i.owner_id=$2
                for update of i
                """,
                inventory_id, owner["id"],
            )
            if item is None:
                raise HTTPException(status_code=404, detail="Inventory item not found")
            if item["version"] != payload.version:
                raise HTTPException(status_code=409, detail={
                    "message": "Inventory item changed",
                    "current_version": item["version"],
                })
            existing = await connection.fetchrow(
                "select * from tcg.shopify_inventory_links where inventory_id=$1",
                inventory_id,
            )
            if existing is not None:
                return jsonable_encoder({
                    "status": "ALREADY_LINKED",
                    "link": dict(existing),
                })
            pooled_membership = await connection.fetchrow(
                """
                select id,listing_id,state
                from tcg.listing_inventory_members
                where inventory_id=$1 and state <> 'REMOVED'
                """,
                inventory_id,
            )
            if pooled_membership is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Inventory belongs to the marketplace listing/reservation system and cannot use the legacy single-item Shopify test path",
                )
            missing = _test_sync_missing(item)
            if missing:
                raise HTTPException(status_code=422, detail={
                    "message": "Inventory is not eligible for Shopify test sync",
                    "missing": missing,
                })

            try:
                collection_titles = await client.list_collection_titles()
            except ShopifyApiError as exc:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": "Could not verify Shopify collections",
                        "retryable": exc.retryable,
                    },
                ) from exc
            plan, launch = _launch_completeness(
                item,
                collection_titles=collection_titles,
                publication_configured=bool(settings.shopify_publication_gid),
                location_configured=bool(settings.shopify_location_gid),
            )
            if not launch["complete"]:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": (
                            "Shopify product is not launch-complete. "
                            "No remote product was created or published."
                        ),
                        "blockers": launch["blockers"],
                        "product_plan": plan,
                    },
                )

            handle = _handle(item["inventory_code"])
            listing_key = f"test:{inventory_id}"
            remote = await client.find_product_by_handle(handle)
            if remote is not None:
                metafield = remote.get("metafield")
                remote_inventory_id = (
                    metafield.get("value") if isinstance(metafield, dict) else None
                )
                if remote_inventory_id != str(inventory_id):
                    raise HTTPException(
                        status_code=409,
                        detail="The deterministic Shopify handle belongs to a different inventory item",
                    )
                product = remote
            else:
                product = await client.create_product(
                    product_create_input(plan, handle=handle)
                )

            variants = product.get("variants")
            nodes = variants.get("nodes") if isinstance(variants, dict) else None
            if not isinstance(nodes, list) or len(nodes) != 1 or not isinstance(nodes[0], dict):
                raise HTTPException(status_code=502, detail="Shopify test product must have exactly one variant")
            variant = nodes[0]
            variant_id = str(variant.get("id") or "")
            if not variant_id:
                raise HTTPException(status_code=502, detail="Shopify variant ID is missing")

            updated_variant = await client.update_variant(
                product_id=str(product["id"]),
                variant_id=variant_id,
                price=_money(int(item["store_price_minor"])),
                sku=item["inventory_code"],
                cost=_money(int(item["acquisition_cost_minor"])),
            )
            inventory_item = updated_variant.get("inventoryItem")
            if not isinstance(inventory_item, dict) or not inventory_item.get("id"):
                raise HTTPException(status_code=502, detail="Shopify inventory item ID is missing")
            inventory_item_id = str(inventory_item["id"])

            await client.activate_inventory(
                inventory_item_id=inventory_item_id,
                location_id=settings.shopify_location_gid,
                idempotency_key=f"activate-{inventory_id}",
            )
            await client.set_inventory_quantity(
                inventory_item_id=inventory_item_id,
                location_id=settings.shopify_location_gid,
                quantity=1,
                idempotency_key=f"quantity-{inventory_id}-{item['version']}",
            )

            link = await connection.fetchrow(
                """
                insert into tcg.shopify_inventory_links(
                    inventory_id, owner_id, created_by_user_id, listing_key,
                    allocation_priority, shop_domain, shopify_product_gid,
                    shopify_variant_gid, shopify_inventory_item_gid,
                    shopify_location_gid, shopify_publication_gid, sku,
                    sync_state, test_mode, synced_price_minor
                ) values(
                    $1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,'DRAFT',true,$12
                )
                returning *
                """,
                inventory_id, owner["id"], user.user_id, listing_key,
                settings.shopify_shop_domain, str(product["id"]), variant_id,
                inventory_item_id, settings.shopify_location_gid,
                settings.shopify_publication_gid, item["inventory_code"],
                int(item["store_price_minor"]),
            )

            await client.set_product_status(product_id=str(product["id"]), status="ACTIVE")
            await client.publish_product(
                product_id=str(product["id"]),
                publication_id=settings.shopify_publication_gid,
            )
            link = await connection.fetchrow(
                """
                update tcg.shopify_inventory_links
                set sync_state='PUBLISHED', last_synced_at=clock_timestamp(),
                    version=version+1
                where id=$1
                returning *
                """,
                link["id"],
            )
            return jsonable_encoder({
                "status": "PUBLISHED_TEST_ITEM",
                "inventory": {
                    "id": item["id"],
                    "inventory_code": item["inventory_code"],
                    "name": item["name"],
                    "store_price_minor": item["store_price_minor"],
                },
                "link": dict(link),
                "product_plan": plan,
                "product_completeness": launch,
            })


def _parse_order_lines(
    payload: dict[str, Any],
    *,
    event_label: str,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    order_reference = str(payload.get("id") or "").strip()
    if not order_reference:
        raise ShopifyProcessingError("MISSING_ORDER_ID", f"Shopify {event_label} has no ID")
    if str(payload.get("currency") or "").upper() != "GBP":
        raise ShopifyProcessingError("CURRENCY_MISMATCH", "Only GBP Shopify orders are supported")

    line_items = payload.get("line_items")
    if not isinstance(line_items, list) or not line_items:
        raise ShopifyProcessingError(
            "MISSING_LINE_ITEMS",
            f"Shopify {event_label} has no line items",
        )

    line_specs: list[dict[str, Any]] = []
    variant_gids: list[str] = []
    for line in line_items:
        if not isinstance(line, dict):
            raise ShopifyProcessingError("INVALID_LINE_ITEM", "Shopify line item is invalid")
        line_reference = str(line.get("id") or "").strip()
        if not line_reference:
            raise ShopifyProcessingError("MISSING_LINE_ID", "Shopify line item has no ID")
        quantity = int(line.get("quantity") or 0)
        if quantity <= 0:
            raise ShopifyProcessingError("INVALID_QUANTITY", "Shopify line item quantity is invalid")
        variant_gid = _variant_gid(line.get("variant_id"))
        variant_gids.append(variant_gid)
        line_specs.append({
            "line": line,
            "line_reference": line_reference,
            "quantity": quantity,
            "variant_gid": variant_gid,
            "unit_price_minor": _minor(line.get("price"), field="line item price"),
            "discount_minor": _minor(line.get("total_discount"), field="line item discount"),
        })
    return order_reference, line_specs, variant_gids


async def _resolve_order_owner_scope(
    connection: asyncpg.Connection,
    *,
    variant_gids: list[str],
) -> tuple[Any, Any]:
    bootstrap = await connection.fetch(
        """
        select distinct owner_id, created_by_user_id
        from tcg.shopify_inventory_links
        where shopify_variant_gid=any($1::text[])
          and sync_state in ('PUBLISHED','SOLD')
        """,
        variant_gids,
    )
    if len(bootstrap) != 1:
        raise ShopifyProcessingError(
            "OWNER_SCOPE_UNRESOLVED",
            "Shopify order does not resolve to exactly one Drop Rate owner scope",
        )
    return bootstrap[0]["owner_id"], bootstrap[0]["created_by_user_id"]


async def _select_order_units(
    connection: asyncpg.Connection,
    *,
    owner_id: Any,
    order_reference: str,
    line_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_units: list[dict[str, Any]] = []
    for spec in line_specs:
        line = spec["line"]
        links = await connection.fetch(
            """
            select
                sil.*, i.inventory_code, i.status as inventory_status,
                i.acquisition_cost_minor, i.store_price_minor, i.version as inventory_version
            from tcg.shopify_inventory_links sil
            join tcg.inventory_items i on i.id=sil.inventory_id
            where sil.owner_id=$1
              and sil.shopify_variant_gid=$2
              and sil.sync_state='PUBLISHED'
            order by sil.allocation_priority, sil.linked_at, sil.inventory_id
            for update of sil, i
            """,
            owner_id, spec["variant_gid"],
        )
        eligible = [
            link
            for link in links
            if link["inventory_status"] == "APPROVED"
            or (
                link["inventory_status"] == "RESERVED"
                and link["reserved_order_reference"] == order_reference
                and link["reserved_line_reference"] == spec["line_reference"]
            )
        ]
        if len(eligible) < spec["quantity"]:
            if any(link["inventory_status"] == "RESERVED" for link in links):
                raise ShopifyProcessingError(
                    "INVENTORY_RESERVED_OTHER_ORDER",
                    "Linked inventory is reserved for a different Shopify order",
                )
            raise ShopifyProcessingError(
                "INSUFFICIENT_LINKED_STOCK",
                "Shopify order exceeds Drop Rate linked stock",
            )
        for allocation_index, link in enumerate(eligible[:spec["quantity"]], start=1):
            if link["acquisition_cost_minor"] is None:
                raise ShopifyProcessingError("MISSING_COST", "Linked inventory has no acquisition cost")
            if spec["unit_price_minor"] != int(link["synced_price_minor"]):
                raise ShopifyProcessingError(
                    "PRICE_DRIFT",
                    "Shopify order price does not match the last synced Drop Rate price",
                )
            sku = str(line.get("sku") or "").strip()
            if sku and sku != link["sku"]:
                raise ShopifyProcessingError("SKU_MISMATCH", "Shopify order SKU does not match Drop Rate")
            product_id = line.get("product_id")
            if product_id and not _product_gid_matches(link["shopify_product_gid"], product_id):
                raise ShopifyProcessingError("PRODUCT_MISMATCH", "Shopify product ID does not match Drop Rate")
            selected_units.append({
                "link": link,
                "line": line,
                "line_reference": spec["line_reference"],
                "allocation_index": allocation_index,
                "sale_price_minor": spec["unit_price_minor"],
                "line_discount_total": spec["discount_minor"],
                "line_quantity": spec["quantity"],
            })
    return selected_units


async def process_shopify_webhook(
    connection: asyncpg.Connection,
    *,
    topic: str,
    payload: dict[str, Any],
    webhook_id: str,
) -> dict[str, Any]:
    if topic == "orders/create":
        return await _process_created_order(connection, payload=payload)
    if topic == "orders/paid":
        return await _process_paid_order(connection, payload=payload, webhook_id=webhook_id)
    if topic == "refunds/create":
        return await _process_refund(connection, payload=payload, webhook_id=webhook_id)
    if topic == "orders/cancelled":
        return await _process_cancelled_order(connection, payload=payload)
    if topic == "app/uninstalled":
        return {"status": "PROCESSED", "action": "APP_UNINSTALLED_RECORDED"}
    return {"status": "IGNORED", "action": "UNSUPPORTED_TOPIC"}


async def _process_created_order(
    connection: asyncpg.Connection,
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    order_reference, line_specs, variant_gids = _parse_order_lines(
        payload,
        event_label="created order",
    )

    cancellation_seen = await connection.fetchval(
        """
        select exists(
          select 1
          from tcg.shopify_webhook_events
          where topic='orders/cancelled'
            and resource_id=$1
            and status in ('RECEIVED','PROCESSED','FAILED')
        )
        """,
        order_reference,
    )
    if cancellation_seen:
        return {
            "status": "PROCESSED",
            "action": "ORDER_ALREADY_CANCELLED",
            "order_reference": order_reference,
        }

    owner_id, user_id = await _resolve_order_owner_scope(
        connection,
        variant_gids=variant_gids,
    )
    await connection.execute("select set_config('tcg.user_id',$1,true)", str(user_id))

    existing = await connection.fetchrow(
        "select id,status from tcg.orders where source='SHOPIFY' and source_reference=$1",
        order_reference,
    )
    if existing is not None:
        return {
            "status": "PROCESSED",
            "action": "ORDER_ALREADY_FINALIZED",
            "order_id": str(existing["id"]),
        }

    reservations = await connection.fetch(
        """
        select
          sil.reserved_line_reference,
          i.status as inventory_status
        from tcg.shopify_inventory_links sil
        join tcg.inventory_items i on i.id=sil.inventory_id
        where sil.owner_id=$1
          and sil.reserved_order_reference=$2
        order by sil.allocation_priority,sil.inventory_id
        for update of sil,i
        """,
        owner_id, order_reference,
    )
    if reservations:
        expected_count = sum(spec["quantity"] for spec in line_specs)
        if len(reservations) != expected_count:
            raise ShopifyProcessingError(
                "PENDING_RESERVATION_MISMATCH",
                "Pending Shopify reservation count does not match the order",
            )
        expected_lines: dict[str, int] = {}
        for spec in line_specs:
            expected_lines[spec["line_reference"]] = (
                expected_lines.get(spec["line_reference"], 0) + spec["quantity"]
            )
        actual_lines: dict[str, int] = {}
        for reservation in reservations:
            if reservation["inventory_status"] != "RESERVED":
                raise ShopifyProcessingError(
                    "RESERVATION_STATE_MISMATCH",
                    "Shopify reservation is not backed by RESERVED inventory",
                )
            line_reference = str(reservation["reserved_line_reference"] or "")
            actual_lines[line_reference] = actual_lines.get(line_reference, 0) + 1
        if actual_lines != expected_lines:
            raise ShopifyProcessingError(
                "PENDING_RESERVATION_MISMATCH",
                "Pending Shopify reservation lines do not match the order",
            )
        return {
            "status": "PROCESSED",
            "action": "PENDING_ORDER_ALREADY_RESERVED",
            "order_reference": order_reference,
        }

    selected_units = await _select_order_units(
        connection,
        owner_id=owner_id,
        order_reference=order_reference,
        line_specs=line_specs,
    )

    reserved: list[dict[str, str]] = []
    for unit in selected_units:
        link = unit["link"]
        if link["inventory_status"] != "APPROVED":
            raise ShopifyProcessingError(
                "RESERVATION_STATE_MISMATCH",
                "New Shopify order can only reserve APPROVED inventory",
            )
        inventory = await connection.fetchrow(
            """
            update tcg.inventory_items
            set status='RESERVED',version=version+1,updated_at=now()
            where id=$1 and owner_id=$2 and status='APPROVED'
            returning id,inventory_code
            """,
            link["inventory_id"], owner_id,
        )
        if inventory is None:
            raise ShopifyProcessingError(
                "INVENTORY_CHANGED",
                "Inventory changed while reserving Shopify order",
            )
        linked = await connection.fetchrow(
            """
            update tcg.shopify_inventory_links
            set reserved_order_reference=$2,
                reserved_line_reference=$3,
                reserved_at=clock_timestamp(),
                version=version+1
            where id=$1 and reserved_order_reference is null
            returning id
            """,
            link["id"], order_reference, unit["line_reference"],
        )
        if linked is None:
            raise ShopifyProcessingError(
                "RESERVATION_LINK_CHANGED",
                "Shopify inventory link changed while reserving order",
            )
        reserved.append({
            "inventory_id": str(link["inventory_id"]),
            "inventory_code": str(inventory["inventory_code"]),
        })

    return {
        "status": "PROCESSED",
        "action": "PENDING_ORDER_RESERVED",
        "order_reference": order_reference,
        "items": reserved,
    }


async def _process_paid_order(
    connection: asyncpg.Connection,
    *,
    payload: dict[str, Any],
    webhook_id: str,
) -> dict[str, Any]:
    order_reference, line_specs, variant_gids = _parse_order_lines(
        payload,
        event_label="paid order",
    )

    owner_id, user_id = await _resolve_order_owner_scope(
        connection,
        variant_gids=variant_gids,
    )
    await connection.execute("select set_config('tcg.user_id',$1,true)", str(user_id))

    existing = await connection.fetchrow(
        "select id,status from tcg.orders where source='SHOPIFY' and source_reference=$1",
        order_reference,
    )
    if existing is not None:
        return {
            "status": "PROCESSED",
            "action": "ORDER_ALREADY_RECORDED",
            "order_id": str(existing["id"]),
        }

    selected_units = await _select_order_units(
        connection,
        owner_id=owner_id,
        order_reference=order_reference,
        line_specs=line_specs,
    )

    order_id = uuid4()
    placed_at = _parse_time(payload.get("processed_at") or payload.get("created_at"))
    order_number = str(payload.get("name") or payload.get("order_number") or "").strip() or None
    await connection.execute(
        """
        insert into tcg.orders(id,source,source_reference,order_number,currency,status,placed_at)
        values($1,'SHOPIFY',$2,$3,'GBP','PAID',$4)
        """,
        order_id, order_reference, order_number, placed_at,
    )

    discount_offsets: dict[str, list[int]] = {}
    for spec in line_specs:
        discount_offsets[spec["line_reference"]] = allocate_minor(
            spec["discount_minor"],
            [1] * spec["quantity"],
        )

    unit_weights: list[int] = []
    for unit in selected_units:
        discount = discount_offsets[unit["line_reference"]].pop(0)
        unit["discount_minor"] = discount
        unit_weights.append(max(unit["sale_price_minor"] - discount, 0))

    shipping_set = payload.get("total_shipping_price_set")
    shipping_minor = 0
    if isinstance(shipping_set, dict):
        shop_money = shipping_set.get("shop_money")
        if isinstance(shop_money, dict):
            if str(shop_money.get("currency_code") or "").upper() not in {"", "GBP"}:
                raise ShopifyProcessingError(
                    "SHIPPING_CURRENCY_MISMATCH",
                    "Shopify shipping currency is not GBP",
                )
            shipping_minor = _minor(shop_money.get("amount"), field="shipping")
    shipping_allocations = allocate_minor(shipping_minor, unit_weights)

    created = []
    for index, unit in enumerate(selected_units):
        link = unit["link"]
        order_item_id = uuid4()
        await connection.execute(
            """
            insert into tcg.order_items(
              id,order_id,inventory_id,owner_id,sale_price_minor,
              discount_minor,cost_basis_minor,sold_at
            ) values($1,$2,$3,$4,$5,$6,$7,$8)
            """,
            order_item_id, order_id, link["inventory_id"], owner_id,
            unit["sale_price_minor"], unit["discount_minor"],
            link["acquisition_cost_minor"], placed_at,
        )
        net_sale = unit["sale_price_minor"] - unit["discount_minor"]
        if net_sale:
            await connection.execute(
                """
                insert into tcg.financial_ledger_entries(
                  owner_id,order_id,order_item_id,entry_type,amount_minor,
                  currency,funds_status,source_key,occurred_at,notes
                ) values($1,$2,$3,'SALE_REVENUE',$4,'GBP','PENDING',$5,$6,$7)
                """,
                owner_id, order_id, order_item_id, net_sale,
                f"shopify:{order_reference}:{unit['line_reference']}:{unit['allocation_index']}:sale",
                placed_at,
                "Shopify gross line revenue; platform/payment fees are not yet settled.",
            )
        if shipping_allocations[index]:
            await connection.execute(
                """
                insert into tcg.financial_ledger_entries(
                  owner_id,order_id,order_item_id,entry_type,amount_minor,
                  currency,funds_status,source_key,occurred_at,notes
                ) values($1,$2,$3,'SHIPPING_REVENUE',$4,'GBP','PENDING',$5,$6,$7)
                """,
                owner_id, order_id, order_item_id, shipping_allocations[index],
                f"shopify:{order_reference}:{unit['line_reference']}:{unit['allocation_index']}:shipping",
                placed_at,
                "Shopify shipping revenue allocated deterministically by net line value.",
            )
        expected_status = link["inventory_status"]
        sold = await connection.fetchrow(
            """
            update tcg.inventory_items
            set status='SOLD',version=version+1,updated_at=now()
            where id=$1 and owner_id=$2 and status=$3
            returning id,inventory_code,status,version
            """,
            link["inventory_id"], owner_id, expected_status,
        )
        if sold is None:
            raise ShopifyProcessingError(
                "INVENTORY_CHANGED",
                "Inventory changed while recording Shopify sale",
            )
        await connection.execute(
            """
            update tcg.shopify_inventory_links
            set sync_state='SOLD',
                sold_at=$2,
                reserved_order_reference=null,
                reserved_line_reference=null,
                reserved_at=null,
                last_synced_at=clock_timestamp(),
                version=version+1
            where id=$1
            """,
            link["id"], placed_at,
        )
        await connection.execute(
            """
            insert into tcg.shopify_order_item_links(
              order_item_id,owner_id,created_by_user_id,shopify_order_id,
              shopify_line_item_id,shopify_variant_gid,allocation_index
            ) values($1,$2,$3,$4,$5,$6,$7)
            """,
            order_item_id, owner_id, user_id, order_reference,
            unit["line_reference"], link["shopify_variant_gid"],
            unit["allocation_index"],
        )
        created.append({
            "order_item_id": str(order_item_id),
            "inventory_id": str(link["inventory_id"]),
            "inventory_code": link["inventory_code"],
        })
    return {
        "status": "PROCESSED",
        "action": "PAID_ORDER_RECORDED",
        "order_id": str(order_id),
        "items": created,
    }


async def _process_cancelled_order(
    connection: asyncpg.Connection,
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    order_reference = str(payload.get("id") or "").strip()
    if not order_reference:
        raise ShopifyProcessingError("MISSING_ORDER_ID", "Shopify cancellation has no order ID")

    reservations = await connection.fetch(
        """
        select sil.*,i.status as inventory_status,i.inventory_code
        from tcg.shopify_inventory_links sil
        join tcg.inventory_items i on i.id=sil.inventory_id
        where sil.reserved_order_reference=$1
        order by sil.allocation_priority,sil.inventory_id
        for update of sil,i
        """,
        order_reference,
    )
    if reservations:
        scopes = {
            (row["owner_id"], row["created_by_user_id"])
            for row in reservations
        }
        if len(scopes) != 1:
            raise ShopifyProcessingError(
                "RESERVATION_OWNER_MISMATCH",
                "Reserved Shopify order spans multiple owner contexts",
            )
        owner_id, user_id = next(iter(scopes))
        await connection.execute("select set_config('tcg.user_id',$1,true)", str(user_id))
        for reservation in reservations:
            if reservation["inventory_status"] != "RESERVED":
                raise ShopifyProcessingError(
                    "RESERVATION_STATE_MISMATCH",
                    "Reserved Shopify link is not backed by RESERVED inventory",
                )
            released = await connection.fetchrow(
                """
                update tcg.inventory_items
                set status='APPROVED',version=version+1,updated_at=now()
                where id=$1 and owner_id=$2 and status='RESERVED'
                returning id
                """,
                reservation["inventory_id"], owner_id,
            )
            if released is None:
                raise ShopifyProcessingError(
                    "INVENTORY_CHANGED",
                    "Inventory changed while releasing Shopify reservation",
                )
            await connection.execute(
                """
                update tcg.shopify_inventory_links
                set reserved_order_reference=null,
                    reserved_line_reference=null,
                    reserved_at=null,
                    version=version+1
                where id=$1 and reserved_order_reference=$2
                """,
                reservation["id"], order_reference,
            )
        return {
            "status": "PROCESSED",
            "action": "PENDING_ORDER_RELEASED",
            "order_reference": order_reference,
        }

    sold_bootstrap = await connection.fetchrow(
        """
        select owner_id,created_by_user_id
        from tcg.shopify_order_item_links
        where shopify_order_id=$1
        order by created_at
        limit 1
        """,
        order_reference,
    )
    if sold_bootstrap is not None:
        await connection.execute(
            "select set_config('tcg.user_id',$1,true)",
            str(sold_bootstrap["created_by_user_id"]),
        )
        row = await connection.fetchrow(
            """
            update tcg.orders set status='CANCELLED',updated_at=now()
            where source='SHOPIFY' and source_reference=$1
            returning id
            """,
            order_reference,
        )
        return {
            "status": "PROCESSED",
            "action": "ORDER_MARKED_CANCELLED" if row else "ORDER_NOT_FOUND",
            "order_id": str(row["id"]) if row else None,
        }

    line_items = payload.get("line_items")
    variant_gids: list[str] = []
    if isinstance(line_items, list):
        for line in line_items:
            if not isinstance(line, dict):
                continue
            try:
                variant_gids.append(_variant_gid(line.get("variant_id")))
            except ShopifyProcessingError:
                continue

    if variant_gids:
        managed = await connection.fetchval(
            """
            select exists(
              select 1
              from tcg.shopify_inventory_links
              where shopify_variant_gid=any($1::text[])
                and sync_state in ('PUBLISHED','SOLD')
            )
            """,
            variant_gids,
        )
        if managed:
            return {
                "status": "PROCESSED",
                "action": "MANAGED_ORDER_CANCELLED_WITHOUT_RESERVATION",
                "order_reference": order_reference,
            }

    return {"status": "PROCESSED", "action": "UNMANAGED_ORDER_CANCELLATION"}


async def _process_refund(
    connection: asyncpg.Connection,
    *,
    payload: dict[str, Any],
    webhook_id: str,
) -> dict[str, Any]:
    refund_id = str(payload.get("id") or "").strip()
    order_reference = str(payload.get("order_id") or "").strip()
    if not refund_id or not order_reference:
        raise ShopifyProcessingError("INVALID_REFUND", "Shopify refund is missing an ID or order ID")
    refund_lines = payload.get("refund_line_items")
    if not isinstance(refund_lines, list):
        raise ShopifyProcessingError("INVALID_REFUND", "Shopify refund line items are invalid")
    shipping_refund_minor = _refund_shipping_minor(payload)

    bootstrap = await connection.fetchrow(
        """
        select owner_id,created_by_user_id
        from tcg.shopify_order_item_links
        where shopify_order_id=$1
        order by created_at
        limit 1
        """,
        order_reference,
    )
    if bootstrap is None:
        return {"status": "PROCESSED", "action": "UNMANAGED_ORDER_REFUND"}
    owner_id = bootstrap["owner_id"]
    user_id = bootstrap["created_by_user_id"]
    await connection.execute("select set_config('tcg.user_id',$1,true)", str(user_id))

    order = await connection.fetchrow(
        """
        select id,status
        from tcg.orders
        where source='SHOPIFY' and source_reference=$1
        for update
        """,
        order_reference,
    )
    if order is None:
        raise ShopifyProcessingError(
            "ORDER_NOT_FOUND",
            "Managed Shopify refund has no matching Drop Rate order",
        )

    await connection.execute(
        """
        update tcg.order_item_reconciliations
        set fees_reconciled_at=null,
            fees_source=null,
            updated_at=clock_timestamp(),
            version=version+1
        where order_id=$1
          and fees_reconciled_at is not null
        """,
        order["id"],
    )

    occurred_at = _parse_time(payload.get("processed_at") or payload.get("created_at"))
    note = str(payload.get("note") or "").strip()
    created = []
    client: ShopifyAdminClient | None = None
    for refund_line in refund_lines:
        if not isinstance(refund_line, dict):
            raise ShopifyProcessingError("INVALID_REFUND_LINE", "Shopify refund line is invalid")
        line_item_id = str(refund_line.get("line_item_id") or "").strip()
        quantity = int(refund_line.get("quantity") or 0)
        if not line_item_id or quantity <= 0:
            raise ShopifyProcessingError("INVALID_REFUND_LINE", "Shopify refund line is incomplete")
        subtotal_minor = _minor(refund_line.get("subtotal"), field="refund subtotal")
        allocations = await connection.fetch(
            """
            select soil.*,oi.inventory_id,oi.net_sale_minor,oi.order_id,
                   i.status as inventory_status,
                   sil.id as inventory_link_id,sil.shopify_inventory_item_gid,
                   sil.shopify_location_gid
            from tcg.shopify_order_item_links soil
            join tcg.order_items oi on oi.id=soil.order_item_id
            join tcg.inventory_items i on i.id=oi.inventory_id
            join tcg.shopify_inventory_links sil on sil.inventory_id=oi.inventory_id
            where soil.shopify_order_id=$1 and soil.shopify_line_item_id=$2
            order by soil.allocation_index
            for update of i,sil
            """,
            order_reference, line_item_id,
        )
        if len(allocations) < quantity:
            raise ShopifyProcessingError(
                "REFUND_ALLOCATION_MISMATCH",
                "Refund quantity exceeds Drop Rate allocation",
            )
        amounts = allocate_minor(subtotal_minor, [1] * quantity)
        for idx, allocation in enumerate(allocations[:quantity]):
            source_reference = (
                f"shopify:{refund_id}:{line_item_id}:{allocation['allocation_index']}"
            )
            duplicate = await connection.fetchval(
                """
                select exists(
                  select 1 from tcg.refund_events
                  where order_item_id=$1 and source_reference=$2
                )
                """,
                allocation["order_item_id"], source_reference,
            )
            if duplicate:
                continue
            restock_type = str(
                refund_line.get("restock_type") or "no_restock"
            ).casefold()
            return_to_stock = restock_type in {
                "return",
                "cancel",
                "legacy_restock",
            }
            amount_minor = amounts[idx]
            if return_to_stock and amount_minor < int(allocation["net_sale_minor"]):
                raise ShopifyProcessingError(
                    "PARTIAL_RESTOCK_REFUND",
                    "Restocking requires the full item sale value to be refunded",
                )
            await connection.execute(
                """
                insert into tcg.refund_events(
                  owner_id,order_id,order_item_id,inventory_id,source_reference,
                  amount_minor,currency,return_to_stock,reason,occurred_at
                ) values($1,$2,$3,$4,$5,$6,'GBP',$7,$8,$9)
                """,
                owner_id, allocation["order_id"], allocation["order_item_id"],
                allocation["inventory_id"], source_reference, amount_minor,
                return_to_stock, note, occurred_at,
            )
            if amount_minor:
                await connection.execute(
                    """
                    insert into tcg.financial_ledger_entries(
                      owner_id,order_id,order_item_id,entry_type,amount_minor,
                      currency,funds_status,source_key,occurred_at,notes
                    ) values($1,$2,$3,'REFUND',$4,'GBP','PENDING',$5,$6,$7)
                    """,
                    owner_id, allocation["order_id"], allocation["order_item_id"],
                    -amount_minor,
                    f"refund:{allocation['order_item_id']}:{source_reference}",
                    occurred_at, note,
                )
            if return_to_stock:
                if client is None:
                    client = _client()
                await client.set_inventory_quantity(
                    inventory_item_id=allocation["shopify_inventory_item_gid"],
                    location_id=allocation["shopify_location_gid"],
                    quantity=0,
                    idempotency_key=(
                        f"refund-zero-{refund_id}-{allocation['allocation_index']}"
                    ),
                )
                await connection.execute(
                    "select set_config('tcg.allow_sold_return','on',true)"
                )
                returned = await connection.fetchrow(
                    """
                    update tcg.inventory_items
                    set status='INSPECTION',version=version+1,updated_at=now()
                    where id=$1 and owner_id=$2 and status='SOLD'
                    returning id
                    """,
                    allocation["inventory_id"], owner_id,
                )
                if returned is None:
                    raise ShopifyProcessingError(
                        "RETURN_STATE_MISMATCH",
                        "Returned inventory is not SOLD",
                    )
                await connection.execute(
                    """
                    update tcg.shopify_inventory_links
                    set sync_state='ARCHIVED',
                        last_synced_at=clock_timestamp(),
                        version=version+1
                    where id=$1
                    """,
                    allocation["inventory_link_id"],
                )
            created.append({
                "order_item_id": str(allocation["order_item_id"]),
                "amount_minor": amount_minor,
                "return_to_stock": return_to_stock,
            })

    shipping_created: list[dict[str, Any]] = []
    if shipping_refund_minor:
        duplicate_shipping = await connection.fetchval(
            """
            select exists(
              select 1
              from tcg.financial_ledger_entries
              where order_id=$1
                and entry_type='SHIPPING_REFUND'
                and source_key like $2
            )
            """,
            order["id"], f"shopify:{refund_id}:shipping:%",
        )
        if not duplicate_shipping:
            shipping_rows = await connection.fetch(
                """
                select
                  oi.id as order_item_id,
                  oi.owner_id,
                  coalesce(
                    sum(le.amount_minor)
                      filter (where le.entry_type='SHIPPING_REVENUE'),
                    0
                  )::bigint as shipping_revenue_minor,
                  coalesce(
                    -sum(le.amount_minor)
                      filter (where le.entry_type='SHIPPING_REFUND'),
                    0
                  )::bigint as shipping_refunded_minor
                from tcg.order_items oi
                left join tcg.financial_ledger_entries le
                  on le.order_item_id=oi.id
                where oi.order_id=$1
                group by oi.id,oi.owner_id
                order by oi.id
                """,
                order["id"],
            )
            remaining_shipping = [
                max(
                    int(row["shipping_revenue_minor"] or 0)
                    - int(row["shipping_refunded_minor"] or 0),
                    0,
                )
                for row in shipping_rows
            ]
            remaining_total = sum(remaining_shipping)
            if shipping_refund_minor > remaining_total:
                raise ShopifyProcessingError(
                    "SHIPPING_REFUND_EXCEEDS_REVENUE",
                    "Shopify shipping refund exceeds remaining recorded shipping revenue",
                )
            if remaining_total <= 0:
                raise ShopifyProcessingError(
                    "SHIPPING_REFUND_WITHOUT_REVENUE",
                    "Shopify refunded shipping but Drop Rate has no refundable shipping revenue",
                )
            shipping_allocations = allocate_minor(
                shipping_refund_minor,
                remaining_shipping,
            )
            for row, amount_minor, capacity in zip(
                shipping_rows,
                shipping_allocations,
                remaining_shipping,
            ):
                if amount_minor <= 0:
                    continue
                if amount_minor > capacity:
                    raise ShopifyProcessingError(
                        "SHIPPING_REFUND_ALLOCATION_EXCEEDED",
                        "Shipping refund allocation exceeded recorded shipping revenue",
                    )
                source_key = (
                    f"shopify:{refund_id}:shipping:{row['order_item_id']}"
                )
                await connection.execute(
                    """
                    insert into tcg.financial_ledger_entries(
                      owner_id,order_id,order_item_id,entry_type,amount_minor,
                      currency,funds_status,source_key,occurred_at,notes
                    ) values($1,$2,$3,'SHIPPING_REFUND',$4,'GBP','PENDING',$5,$6,$7)
                    on conflict(source_key) do nothing
                    """,
                    row["owner_id"], order["id"], row["order_item_id"],
                    -amount_minor, source_key, occurred_at,
                    "Shopify shipping refund allocated against original shipping revenue.",
                )
                shipping_created.append({
                    "order_item_id": str(row["order_item_id"]),
                    "amount_minor": amount_minor,
                })

    gross_revenue = await connection.fetchval(
        """
        select coalesce(sum(amount_minor),0)::bigint
        from tcg.financial_ledger_entries
        where order_id=$1
          and entry_type in ('SALE_REVENUE','SHIPPING_REVENUE')
        """,
        order["id"],
    )
    total_refund = await connection.fetchval(
        """
        select coalesce(-sum(amount_minor),0)::bigint
        from tcg.financial_ledger_entries
        where order_id=$1
          and entry_type in ('REFUND','SHIPPING_REFUND')
        """,
        order["id"],
    )
    gross_revenue_minor = int(gross_revenue or 0)
    total_refund_minor = int(total_refund or 0)
    if total_refund_minor > gross_revenue_minor:
        raise ShopifyProcessingError(
            "REFUND_EXCEEDS_GROSS_REVENUE",
            "Recorded refunds exceed original Shopify gross revenue",
        )
    next_status = (
        "REFUNDED"
        if gross_revenue_minor > 0 and total_refund_minor >= gross_revenue_minor
        else "PARTIALLY_REFUNDED"
    )
    await connection.execute(
        "update tcg.orders set status=$2,updated_at=now() where id=$1",
        order["id"], next_status,
    )
    return {
        "status": "PROCESSED",
        "action": "REFUND_RECORDED",
        "items": created,
        "shipping_refund_minor": shipping_refund_minor,
        "shipping_allocations": shipping_created,
    }

