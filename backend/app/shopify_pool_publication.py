from __future__ import annotations

import json
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Annotated, Any, Mapping
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .settings import Settings, get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError
from .shopify_completeness import required_collection_titles
from .shopify_pooling import _set_actor, _shopify_client


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/shopify/pooling", tags=["shopify-pooling"])


class PooledPublishApplyRequest(BaseModel):
    max_groups: int = Field(default=50, ge=1, le=100)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _money(minor: int) -> str:
    return f"{Decimal(int(minor)) / Decimal(100):.2f}"


async def _load_pooled_draft_rows(
    connection: asyncpg.Connection,
    *,
    shop_domain: str,
) -> list[dict[str, Any]]:
    rows = await connection.fetch(
        """
        select
          i.id as inventory_id,
          i.catalogue_id,
          i.owner_id,
          i.inventory_code,
          i.status,
          i.sale_intent,
          i.identity_confirmed,
          i.language,
          i.condition,
          i.grading_company,
          i.grade,
          i.store_price_minor,
          i.storage_location_id,
          p.product_type,
          p.game,
          p.set_name,
          p.name,
          p.card_number,
          p.variant,
          p.rarity,
          p.language as catalogue_language,
          sil.id as link_id,
          sil.listing_key,
          sil.allocation_priority,
          sil.shop_domain,
          sil.shopify_product_gid,
          sil.shopify_variant_gid,
          sil.shopify_inventory_item_gid,
          sil.shopify_location_gid,
          sil.shopify_publication_gid,
          sil.sku,
          sil.sync_state,
          sil.synced_price_minor,
          sil.reserved_order_reference,
          sil.reserved_line_reference,
          sil.version as link_version,
          exists(
            select 1
            from tcg.inventory_reservations ir
            where ir.inventory_id=i.id and ir.status='ACTIVE'
          ) as has_active_reservation
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
        where sil.shop_domain=$1
          and sil.test_mode=false
          and sil.sync_state='DRAFT'
          and sil.listing_key like 'shopify-pool:%'
        order by sil.listing_key,sil.allocation_priority,sil.linked_at,i.id
        """,
        shop_domain,
    )
    return [dict(row) for row in rows]


def _evaluate_pool(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("Pooled publication group cannot be empty")

    blockers: list[str] = []
    first = rows[0]
    listing_key = _clean(first.get("listing_key"))

    if not listing_key.startswith("shopify-pool:"):
        blockers.append("invalid pooled listing key")
    if len(rows) < 2:
        blockers.append("pool has fewer than two physical members")

    shared_fields = (
        "catalogue_id",
        "shopify_product_gid",
        "shopify_variant_gid",
        "shopify_inventory_item_gid",
        "shopify_location_gid",
        "shopify_publication_gid",
        "sku",
        "synced_price_minor",
    )
    for field in shared_fields:
        values = {_clean(row.get(field)) for row in rows}
        if len(values) != 1 or "" in values:
            blockers.append(f"pooled links disagree on {field}")

    if any(_clean(row.get("status")) != "APPROVED" for row in rows):
        blockers.append("inventory not APPROVED")
    if any(row.get("sale_intent") != "FOR_SALE" for row in rows):
        blockers.append("inventory not FOR_SALE")
    if any(row.get("identity_confirmed") is not True for row in rows):
        blockers.append("identity not confirmed")
    if any(not _clean(row.get("language") or row.get("catalogue_language")) for row in rows):
        blockers.append("language missing")
    if any(not _clean(row.get("condition")) for row in rows):
        blockers.append("condition missing")
    if any(_clean(row.get("grading_company")) or _clean(row.get("grade")) for row in rows):
        blockers.append("graded inventory cannot use raw pool publication")
    if any(row.get("store_price_minor") is None for row in rows):
        blockers.append("store price missing")
    if any(row.get("storage_location_id") is None for row in rows):
        blockers.append("storage location missing")
    if any(row.get("reserved_order_reference") or row.get("reserved_line_reference") for row in rows):
        blockers.append("Shopify link reserved")
    if any(row.get("has_active_reservation") for row in rows):
        blockers.append("active inventory reservation")

    prices = {
        int(row["store_price_minor"])
        for row in rows
        if row.get("store_price_minor") is not None
    }
    if len(prices) != 1:
        blockers.append("pool members have different store prices")
    synced_prices = {
        int(row["synced_price_minor"])
        for row in rows
        if row.get("synced_price_minor") is not None
    }
    if len(synced_prices) != 1 or (prices and synced_prices != prices):
        blockers.append("pooled link price differs from inventory price")

    priorities = [int(row["allocation_priority"]) for row in rows]
    if priorities != list(range(1, len(rows) + 1)):
        blockers.append("allocation priority is not contiguous")

    return {
        "listing_key": listing_key,
        "quantity": len(rows),
        "price_minor": next(iter(prices)) if len(prices) == 1 else None,
        "product_gid": _clean(first.get("shopify_product_gid")),
        "variant_gid": _clean(first.get("shopify_variant_gid")),
        "inventory_item_gid": _clean(first.get("shopify_inventory_item_gid")),
        "location_gid": _clean(first.get("shopify_location_gid")),
        "publication_gid": _clean(first.get("shopify_publication_gid")),
        "sku": _clean(first.get("sku")),
        "rows": rows,
        "ready": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
    }


def _build_pool_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_clean(row.get("listing_key"))].append(row)
    groups = [_evaluate_pool(members) for members in grouped.values()]
    groups.sort(key=lambda g: (not g["ready"], -int(g["quantity"]), g["listing_key"]))
    return groups


def _variant(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    variants = snapshot.get("variants")
    nodes = variants.get("nodes") if isinstance(variants, Mapping) else None
    if not isinstance(nodes, list) or len(nodes) != 1 or not isinstance(nodes[0], Mapping):
        raise RuntimeError("Pooled Shopify product must have exactly one variant")
    return nodes[0]


def _remote_blockers(group: Mapping[str, Any], snapshot: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if _clean(snapshot.get("id")) != group["product_gid"]:
        blockers.append("remote product id mismatch")
    if _clean(snapshot.get("status")).upper() != "DRAFT":
        blockers.append("remote product is not DRAFT")

    media = snapshot.get("media")
    media_nodes = media.get("nodes") if isinstance(media, Mapping) else None
    if not isinstance(media_nodes, list) or not media_nodes:
        blockers.append("remote image missing")

    collections = snapshot.get("collections")
    collection_nodes = collections.get("nodes") if isinstance(collections, Mapping) else None
    actual_collections = {
        _clean(node.get("title"))
        for node in collection_nodes or []
        if isinstance(node, Mapping) and _clean(node.get("title"))
    }
    expected_collections = set(required_collection_titles(group["rows"][0]))
    if not expected_collections.issubset(actual_collections):
        blockers.append("remote collection missing")

    try:
        variant = _variant(snapshot)
    except RuntimeError as exc:
        blockers.append(str(exc))
        return blockers

    if _clean(variant.get("id")) != group["variant_gid"]:
        blockers.append("remote variant id mismatch")
    if _clean(variant.get("price")) != _money(int(group["price_minor"])):
        blockers.append("remote price mismatch")
    if _clean(variant.get("inventoryPolicy")).upper() != "DENY":
        blockers.append("remote oversell policy mismatch")
    try:
        quantity = int(variant.get("inventoryQuantity"))
    except (TypeError, ValueError):
        quantity = -1
    if quantity != int(group["quantity"]):
        blockers.append("remote pooled quantity mismatch")

    inventory_item = variant.get("inventoryItem")
    if not isinstance(inventory_item, Mapping):
        blockers.append("remote inventory item missing")
    else:
        if _clean(inventory_item.get("id")) != group["inventory_item_gid"]:
            blockers.append("remote inventory item id mismatch")
        if _clean(inventory_item.get("sku")) != group["sku"]:
            blockers.append("remote pooled sku mismatch")
        if inventory_item.get("tracked") is not True:
            blockers.append("remote inventory is not tracked")

    return list(dict.fromkeys(blockers))


async def _reload_pool(
    connection: asyncpg.Connection,
    *,
    shop_domain: str,
    listing_key: str,
    for_update: bool,
) -> dict[str, Any]:
    lock = " for update of sil,i" if for_update else ""
    rows = await connection.fetch(
        f"""
        select
          i.id as inventory_id,
          i.catalogue_id,
          i.owner_id,
          i.inventory_code,
          i.status,
          i.sale_intent,
          i.identity_confirmed,
          i.language,
          i.condition,
          i.grading_company,
          i.grade,
          i.store_price_minor,
          i.storage_location_id,
          p.product_type,
          p.game,
          p.set_name,
          p.name,
          p.card_number,
          p.variant,
          p.rarity,
          p.language as catalogue_language,
          sil.id as link_id,
          sil.listing_key,
          sil.allocation_priority,
          sil.shop_domain,
          sil.shopify_product_gid,
          sil.shopify_variant_gid,
          sil.shopify_inventory_item_gid,
          sil.shopify_location_gid,
          sil.shopify_publication_gid,
          sil.sku,
          sil.sync_state,
          sil.synced_price_minor,
          sil.reserved_order_reference,
          sil.reserved_line_reference,
          sil.version as link_version,
          exists(
            select 1
            from tcg.inventory_reservations ir
            where ir.inventory_id=i.id and ir.status='ACTIVE'
          ) as has_active_reservation
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
        where sil.shop_domain=$1
          and sil.test_mode=false
          and sil.sync_state='DRAFT'
          and sil.listing_key=$2
        order by sil.allocation_priority,sil.linked_at,i.id
        {lock}
        """,
        shop_domain,
        listing_key,
    )
    return _evaluate_pool([dict(row) for row in rows])


async def _mark_pool_published(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    actor_user_id: UUID,
    seed_group: Mapping[str, Any],
) -> None:
    request_id = f"shopify-pool-publish:{uuid4()}"
    async with pool.acquire() as connection:
        await _set_actor(connection, actor_user_id, request_id)
        async with connection.transaction():
            current = await _reload_pool(
                connection,
                shop_domain=str(settings.shopify_shop_domain),
                listing_key=str(seed_group["listing_key"]),
                for_update=True,
            )
            if not current["ready"]:
                raise RuntimeError(
                    "Pooled publication readiness changed before database commit: "
                    + "; ".join(current["blockers"])
                )
            if {
                str(row["inventory_id"]) for row in current["rows"]
            } != {
                str(row["inventory_id"]) for row in seed_group["rows"]
            }:
                raise RuntimeError("Pooled publication membership changed before database commit")

            for row in current["rows"]:
                old_values = {
                    "sync_state": row["sync_state"],
                    "listing_key": row["listing_key"],
                    "shopify_product_gid": row["shopify_product_gid"],
                    "shopify_variant_gid": row["shopify_variant_gid"],
                }
                updated = await connection.fetchrow(
                    """
                    update tcg.shopify_inventory_links
                    set sync_state='PUBLISHED',
                        last_synced_at=clock_timestamp(),
                        version=version+1
                    where id=$1
                      and version=$2
                      and sync_state='DRAFT'
                      and reserved_order_reference is null
                      and reserved_line_reference is null
                    returning *
                    """,
                    row["link_id"],
                    row["link_version"],
                )
                if updated is None:
                    raise RuntimeError("Pooled Shopify link changed before publication commit")
                await connection.execute(
                    """
                    insert into tcg.audit_events(
                      actor,request_id,action,entity_type,entity_id,old_values,new_values
                    ) values(
                      $1,$2,'SHOPIFY_RAW_POOL_PUBLISHED',
                      'SHOPIFY_INVENTORY_LINK',$3,$4::jsonb,$5::jsonb
                    )
                    """,
                    str(actor_user_id),
                    request_id,
                    row["inventory_id"],
                    json.dumps(old_values, default=str),
                    json.dumps(
                        {
                            "sync_state": "PUBLISHED",
                            "listing_key": updated["listing_key"],
                            "shopify_product_gid": updated["shopify_product_gid"],
                            "shopify_variant_gid": updated["shopify_variant_gid"],
                            "quantity": current["quantity"],
                        },
                        default=str,
                    ),
                )


async def _publish_one_pool(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    client: ShopifyAdminClient,
    actor_user_id: UUID,
    seed_group: Mapping[str, Any],
) -> dict[str, Any]:
    if not settings.shopify_publication_gid:
        raise RuntimeError("Shopify publication is not configured")

    async with pool.acquire() as connection:
        await _set_actor(connection, actor_user_id, f"shopify-pool-publish-plan:{uuid4()}")
        current = await _reload_pool(
            connection,
            shop_domain=str(settings.shopify_shop_domain),
            listing_key=str(seed_group["listing_key"]),
            for_update=False,
        )
    if not current["ready"]:
        return {
            "listing_key": seed_group["listing_key"],
            "status": "BLOCKED",
            "blockers": current["blockers"],
        }

    snapshot = await client.get_product_snapshot(str(current["product_gid"]))
    blockers = _remote_blockers(current, snapshot)
    if blockers:
        return {
            "listing_key": current["listing_key"],
            "status": "BLOCKED",
            "blockers": blockers,
        }

    await client.set_product_status(
        product_id=str(current["product_gid"]),
        status="ACTIVE",
    )
    try:
        await client.publish_product(
            product_id=str(current["product_gid"]),
            publication_id=str(settings.shopify_publication_gid),
        )
        final_snapshot = await client.get_product_snapshot(str(current["product_gid"]))
        if _clean(final_snapshot.get("status")).upper() != "ACTIVE":
            raise RuntimeError("Pooled Shopify product did not become ACTIVE")
        published = await client.product_published_on_publication(
            product_id=str(current["product_gid"]),
            publication_id=str(settings.shopify_publication_gid),
        )
        if not published:
            raise RuntimeError("Pooled Shopify product is not on the target publication")
        final_blockers = [
            blocker
            for blocker in _remote_blockers(
                current,
                {**final_snapshot, "status": "DRAFT"},
            )
            if blocker != "remote product is not DRAFT"
        ]
        if final_blockers:
            raise RuntimeError(
                "Pooled Shopify product changed during publication: "
                + "; ".join(final_blockers)
            )
        await _mark_pool_published(
            pool,
            settings=settings,
            actor_user_id=actor_user_id,
            seed_group=current,
        )
    except Exception:
        try:
            await client.set_product_status(
                product_id=str(current["product_gid"]),
                status="DRAFT",
            )
        except Exception:
            logger.exception(
                "Pooled publication compensation failed for %s",
                current["listing_key"],
            )
        raise

    return {
        "listing_key": current["listing_key"],
        "status": "PUBLISHED",
        "quantity": current["quantity"],
        "product_gid": current["product_gid"],
        "variant_gid": current["variant_gid"],
        "sku": current["sku"],
    }


@router.get("/pooled-publish-plan")
async def pooled_publish_plan(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    if not settings.shopify_shop_domain:
        raise HTTPException(status_code=409, detail="Shopify shop domain is not configured")

    async with request.app.state.db_pool.acquire() as connection:
        await _set_actor(connection, user.user_id, request.state.request_id)
        rows = await _load_pooled_draft_rows(
            connection,
            shop_domain=str(settings.shopify_shop_domain),
        )

    groups = _build_pool_groups(rows)
    ready = [group for group in groups if group["ready"]]
    blocked = [group for group in groups if not group["ready"]]
    blocker_counts: dict[str, int] = {}
    for group in blocked:
        for blocker in group["blockers"]:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1

    return jsonable_encoder(
        {
            "mode": "PLAN_ONLY",
            "groups": len(groups),
            "physical_items": sum(group["quantity"] for group in groups),
            "ready_groups": len(ready),
            "ready_items": sum(group["quantity"] for group in ready),
            "blocked_groups": len(blocked),
            "blockers": blocker_counts,
            "ready": [
                {
                    "listing_key": group["listing_key"],
                    "quantity": group["quantity"],
                    "price_minor": group["price_minor"],
                    "product_gid": group["product_gid"],
                    "variant_gid": group["variant_gid"],
                    "sku": group["sku"],
                }
                for group in ready
            ],
        }
    )


@router.post("/pooled-publish-apply")
async def pooled_publish_apply(
    payload: PooledPublishApplyRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    if not settings.shopify_shop_domain or not settings.shopify_publication_gid:
        raise HTTPException(status_code=409, detail="Shopify publication is not configured")

    actor_user_id = user.user_id
    client = _shopify_client(settings)

    async with request.app.state.db_pool.acquire() as connection:
        await _set_actor(connection, actor_user_id, request.state.request_id)
        rows = await _load_pooled_draft_rows(
            connection,
            shop_domain=str(settings.shopify_shop_domain),
        )
    groups = _build_pool_groups(rows)
    selected = [group for group in groups if group["ready"]][: payload.max_groups]

    results: list[dict[str, Any]] = []
    for group in selected:
        try:
            results.append(
                await _publish_one_pool(
                    request.app.state.db_pool,
                    settings=settings,
                    client=client,
                    actor_user_id=actor_user_id,
                    seed_group=group,
                )
            )
        except (ShopifyApiError, RuntimeError, ValueError) as exc:
            logger.exception("Pooled publication failed for %s", group["listing_key"])
            results.append(
                {
                    "listing_key": group["listing_key"],
                    "status": "ERROR",
                    "detail": str(exc)[:500],
                    "error_type": type(exc).__name__,
                }
            )

    return jsonable_encoder(
        {
            "status": "COMPLETE",
            "selected_groups": len(selected),
            "published_groups": sum(1 for row in results if row["status"] == "PUBLISHED"),
            "blocked_groups": sum(1 for row in results if row["status"] == "BLOCKED"),
            "failed_groups": sum(1 for row in results if row["status"] == "ERROR"),
            "results": results,
        }
    )
