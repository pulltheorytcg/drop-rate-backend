from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Annotated, Any, Mapping
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .settings import Settings, get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError
from .shopify_copy_groups import copy_group_metafields
from .shopify_pooling import (
    _clean,
    _key,
    _money,
    _set_actor,
    _shopify_client,
    pooled_product_description_html,
    raw_pool_identity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/shopify/pooling", tags=["shopify-pooling"])


class PublishedRawPoolApplyRequest(BaseModel):
    max_groups: int = Field(default=25, ge=1, le=50)


def _group_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _clean(row.get("catalogue_id")),
        _key(row.get("language") or row.get("catalogue_language")),
        _key(row.get("condition")),
    )


def evaluate_published_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("Published raw pool group cannot be empty")

    pool = raw_pool_identity(rows[0])
    blockers: list[str] = []
    prices = {
        int(row["store_price_minor"])
        for row in rows
        if row.get("store_price_minor") is not None
    }

    if len(rows) < 2:
        blockers.append("single physical copy")
    if len({_clean(row.get("shopify_product_gid")) for row in rows}) < 2:
        blockers.append("already on one Shopify product")
    if any(row.get("store_price_minor") is None for row in rows):
        blockers.append("missing store price")
    elif len(prices) != 1:
        blockers.append("pool members have different store prices")
    if any(_clean(row.get("product_type")) != "CARD" for row in rows):
        blockers.append("non-card inventory")
    if any(_clean(row.get("grading_company")) or _clean(row.get("grade")) for row in rows):
        blockers.append("graded inventory cannot auto-pool")
    if any(_clean(row.get("status")) != "APPROVED" for row in rows):
        blockers.append("inventory not APPROVED")
    if any(row.get("sale_intent") != "FOR_SALE" for row in rows):
        blockers.append("inventory not FOR_SALE")
    if any(row.get("identity_confirmed") is not True for row in rows):
        blockers.append("identity not confirmed")
    if any(not _clean(row.get("language") or row.get("catalogue_language")) for row in rows):
        blockers.append("missing language")
    if any(not _clean(row.get("condition")) for row in rows):
        blockers.append("missing condition")
    if any(row.get("acquisition_cost_minor") is None for row in rows):
        blockers.append("missing acquisition cost")
    if any(row.get("storage_location_id") is None for row in rows):
        blockers.append("missing storage location")
    if any(row.get("test_mode") is True for row in rows):
        blockers.append("test Shopify link")
    if any(_clean(row.get("sync_state")) != "PUBLISHED" for row in rows):
        blockers.append("Shopify link is not PUBLISHED")
    if any(row.get("reserved_order_reference") or row.get("reserved_line_reference") for row in rows):
        blockers.append("Shopify link reserved by order")
    if any(row.get("has_listing_membership") for row in rows):
        blockers.append("inventory already belongs to marketplace listing")
    if any(row.get("has_active_reservation") for row in rows):
        blockers.append("inventory actively reserved")
    if any(row.get("created_by_user_id") is None for row in rows):
        blockers.append("Shopify link has no admin actor")

    locations = {_clean(row.get("shopify_location_gid")) for row in rows}
    if len(locations) != 1 or "" in locations:
        blockers.append("Shopify location mismatch")
    publications = {_clean(row.get("shopify_publication_gid")) for row in rows}
    if len(publications) != 1 or "" in publications:
        blockers.append("Shopify publication mismatch")
    synced_prices = {
        int(row["synced_price_minor"])
        for row in rows
        if row.get("synced_price_minor") is not None
    }
    if len(synced_prices) != 1 or (prices and synced_prices != prices):
        blockers.append("Shopify synced price mismatch")

    expected_key = _group_key(rows[0])
    if any(_group_key(row) != expected_key for row in rows):
        blockers.append("pool identity mismatch")

    by_product = Counter(_clean(row.get("shopify_product_gid")) for row in rows)
    product_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        product_rows[_clean(row.get("shopify_product_gid"))].append(row)

    def anchor_key(product_gid: str) -> tuple[Any, ...]:
        members = product_rows[product_gid]
        pooled = any(
            _clean(row.get("listing_key")).startswith("shopify-pool:")
            or _clean(row.get("sku")).startswith("DRP-")
            for row in members
        )
        earliest = min(str(row.get("linked_at") or "") for row in members)
        return (0 if pooled else 1, -by_product[product_gid], earliest, product_gid)

    product_gids = sorted(product_rows, key=anchor_key)
    anchor_product_gid = product_gids[0]
    anchor_members = sorted(
        product_rows[anchor_product_gid],
        key=lambda row: (str(row.get("linked_at") or ""), _clean(row.get("inventory_code"))),
    )
    anchor = anchor_members[0]

    ordered = sorted(
        rows,
        key=lambda row: (
            0 if _clean(row.get("shopify_product_gid")) == anchor_product_gid else 1,
            int(row.get("allocation_priority") or 999999),
            str(row.get("linked_at") or ""),
            _clean(row.get("inventory_code")),
        ),
    )

    return {
        "pool": pool,
        "ready": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "quantity": len(rows),
        "price_minor": next(iter(prices)) if len(prices) == 1 else None,
        "anchor_product_gid": anchor_product_gid,
        "anchor_variant_gid": _clean(anchor.get("shopify_variant_gid")),
        "anchor_inventory_item_gid": _clean(anchor.get("shopify_inventory_item_gid")),
        "anchor_location_gid": _clean(anchor.get("shopify_location_gid")),
        "anchor_publication_gid": _clean(anchor.get("shopify_publication_gid")),
        "retire_product_gids": [gid for gid in product_gids if gid != anchor_product_gid],
        "members": ordered,
    }


async def _load_rows(
    connection: asyncpg.Connection,
    *,
    shop_domain: str,
    catalogue_id: UUID | None = None,
    language_key: str | None = None,
    condition_key: str | None = None,
    for_update: bool = False,
) -> list[dict[str, Any]]:
    filters = ["sil.shop_domain=$1", "sil.test_mode=false", "sil.sync_state='PUBLISHED'",
               "i.status='APPROVED'", "i.sale_intent='FOR_SALE'", "p.product_type='CARD'",
               "nullif(btrim(coalesce(i.grading_company,'')),'') is null",
               "nullif(btrim(coalesce(i.grade,'')),'') is null"]
    args: list[Any] = [shop_domain]
    if catalogue_id is not None:
        args.append(catalogue_id)
        filters.append(f"i.catalogue_id=${len(args)}")
    if language_key is not None:
        args.append(language_key)
        filters.append(f"lower(btrim(coalesce(i.language,p.language,'')))=${len(args)}")
    if condition_key is not None:
        args.append(condition_key)
        filters.append(f"lower(btrim(coalesce(i.condition,'')))=${len(args)}")

    lock = " for update of i,sil" if for_update else ""
    rows = await connection.fetch(
        f"""
        select
          i.id as inventory_id,i.catalogue_id,i.owner_id,i.inventory_code,
          i.status,i.sale_intent,i.identity_confirmed,i.language,i.condition,
          i.grading_company,i.grade,i.acquisition_cost_minor,i.storage_location_id,
          i.store_price_minor,p.product_type,p.language as catalogue_language,
          sil.id as link_id,sil.created_by_user_id,sil.listing_key,
          sil.allocation_priority,sil.shop_domain,sil.shopify_product_gid,
          sil.shopify_variant_gid,sil.shopify_inventory_item_gid,
          sil.shopify_location_gid,sil.shopify_publication_gid,sil.sku,
          sil.sync_state,sil.test_mode,sil.synced_price_minor,sil.linked_at,
          sil.reserved_order_reference,sil.reserved_line_reference,
          sil.version as link_version,
          exists(
            select 1 from tcg.listing_inventory_members lim
            where lim.inventory_id=i.id and lim.state <> 'REMOVED'
          ) as has_listing_membership,
          exists(
            select 1 from tcg.inventory_reservations ir
            where ir.inventory_id=i.id and ir.status='ACTIVE'
          ) as has_active_reservation
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id=i.catalogue_id
        join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
        where {" and ".join(filters)}
        order by i.catalogue_id,sil.linked_at,i.inventory_code,i.id
        {lock}
        """,
        *args,
    )
    return [dict(row) for row in rows]


def _groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_group_key(row)].append(row)
    result = [
        evaluate_published_group(members)
        for members in grouped.values()
        if len(members) > 1 and len({_clean(row.get("shopify_product_gid")) for row in members}) > 1
    ]
    result.sort(
        key=lambda group: (
            not group["ready"],
            -int(group["quantity"]),
            str(group["pool"]["listing_key"]),
        )
    )
    return result


def _single_variant(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    variants = snapshot.get("variants")
    nodes = variants.get("nodes") if isinstance(variants, Mapping) else None
    if not isinstance(nodes, list) or len(nodes) != 1 or not isinstance(nodes[0], dict):
        raise RuntimeError("Published raw pool product must have exactly one Shopify variant")
    return nodes[0]


async def _compensate(
    client: ShopifyAdminClient,
    *,
    snapshots: dict[str, dict[str, Any]],
    location_id: str,
    key: str,
) -> None:
    for index, (product_id, snapshot) in enumerate(snapshots.items(), start=1):
        try:
            variant = _single_variant(snapshot)
            inventory_item = variant.get("inventoryItem") or {}
            await client.update_product(
                product_id=product_id,
                product={"descriptionHtml": str(snapshot.get("descriptionHtml") or "")},
            )
            await client.update_variant_pool_identity(
                product_id=product_id,
                variant_id=str(variant["id"]),
                price=str(variant.get("price") or "0.00"),
                sku=str(inventory_item.get("sku") or ""),
            )
            await client.set_inventory_quantity(
                inventory_item_id=str(inventory_item["id"]),
                location_id=location_id,
                quantity=int(variant.get("inventoryQuantity") or 0),
                idempotency_key=f"{key}:{index}",
            )
            await client.set_product_status(
                product_id=product_id,
                status=str(snapshot.get("status") or "ACTIVE"),
            )
        except Exception:
            logger.exception("Published raw pool compensation failed for %s", product_id)


async def _apply_one(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    client: ShopifyAdminClient,
    actor_user_id: UUID,
    seed: Mapping[str, Any],
) -> dict[str, Any]:
    first = seed["members"][0]
    catalogue_id = UUID(str(first["catalogue_id"]))
    language_key = _key(first.get("language") or first.get("catalogue_language"))
    condition_key = _key(first.get("condition"))
    listing_key = str(seed["pool"]["listing_key"])
    request_id = f"shopify-published-pool:{uuid4()}"

    async with pool.acquire() as connection:
        await _set_actor(connection, actor_user_id, request_id)
        locked = await connection.fetchval(
            "select pg_try_advisory_lock(hashtextextended($1,0))",
            listing_key,
        )
        if not locked:
            return {"listing_key": listing_key, "status": "BUSY"}
        try:
            async with connection.transaction():
                rows = await _load_rows(
                    connection,
                    shop_domain=str(settings.shopify_shop_domain),
                    catalogue_id=catalogue_id,
                    language_key=language_key,
                    condition_key=condition_key,
                    for_update=True,
                )
            current = evaluate_published_group(rows)
            if not current["ready"]:
                return {
                    "listing_key": listing_key,
                    "status": "BLOCKED",
                    "blockers": current["blockers"],
                }

            anchor_product_id = str(current["anchor_product_gid"])
            anchor_variant_id = str(current["anchor_variant_gid"])
            anchor_inventory_item_id = str(current["anchor_inventory_item_gid"])
            location_id = str(current["anchor_location_gid"])
            publication_id = str(current["anchor_publication_gid"])
            target_sku = str(current["pool"]["sku"])
            target_price = int(current["price_minor"])
            target_quantity = int(current["quantity"])

            distinct_products = list(dict.fromkeys(
                _clean(row["shopify_product_gid"]) for row in current["members"]
            ))
            snapshots: dict[str, dict[str, Any]] = {}
            expected_remote_qty: Counter[str] = Counter(
                _clean(row["shopify_product_gid"]) for row in current["members"]
            )
            for product_id in distinct_products:
                snapshot = await client.get_product_snapshot(product_id)
                if str(snapshot.get("status") or "").upper() != "ACTIVE":
                    return {
                        "listing_key": listing_key,
                        "status": "BLOCKED",
                        "blockers": [f"remote product {product_id} is not ACTIVE"],
                    }
                variant = _single_variant(snapshot)
                inventory_item = variant.get("inventoryItem")
                if not isinstance(inventory_item, Mapping):
                    raise RuntimeError("Published raw product has no inventory item")
                local = next(
                    row for row in current["members"]
                    if _clean(row["shopify_product_gid"]) == product_id
                )
                if str(variant.get("id")) != str(local["shopify_variant_gid"]):
                    raise RuntimeError("Shopify variant changed during published pool planning")
                if str(inventory_item.get("id")) != str(local["shopify_inventory_item_gid"]):
                    raise RuntimeError("Shopify inventory item changed during published pool planning")
                if inventory_item.get("tracked") is not True:
                    raise RuntimeError("Published raw inventory is not tracked")
                if str(variant.get("inventoryPolicy") or "").upper() != "DENY":
                    raise RuntimeError("Published raw variant allows overselling")
                if str(variant.get("price") or "") != _money(target_price):
                    raise RuntimeError("Published raw product price drift detected")
                if int(variant.get("inventoryQuantity") or 0) != expected_remote_qty[product_id]:
                    raise RuntimeError("Published raw Shopify quantity does not match eligible physical stock")
                if not await client.product_published_on_publication(
                    product_id=product_id,
                    publication_id=publication_id,
                ):
                    raise RuntimeError("Published raw product is not on the configured publication")
                snapshots[product_id] = snapshot

            operation = f"published-pool:{current['pool']['fingerprint'][:16]}:{uuid4().hex[:10]}"
            remote_changed = False
            try:
                anchor_snapshot = snapshots[anchor_product_id]
                pooled_description = pooled_product_description_html(
                    str(anchor_snapshot.get("descriptionHtml") or "")
                )
                if _clean(anchor_snapshot.get("descriptionHtml")) != _clean(pooled_description):
                    await client.update_product(
                        product_id=anchor_product_id,
                        product={"descriptionHtml": pooled_description},
                    )
                    remote_changed = True

                await client.update_variant_pool_identity(
                    product_id=anchor_product_id,
                    variant_id=anchor_variant_id,
                    price=_money(target_price),
                    sku=target_sku,
                )
                remote_changed = True
                await client.set_inventory_quantity(
                    inventory_item_id=anchor_inventory_item_id,
                    location_id=location_id,
                    quantity=target_quantity,
                    idempotency_key=f"{operation}:anchor",
                )
                await client.set_product_metafields(
                    product_id=anchor_product_id,
                    metafields=copy_group_metafields(
                        catalogue_id=catalogue_id,
                        handles=[str(anchor_snapshot.get("handle") or "")],
                        total_count=target_quantity,
                    ),
                )

                for index, product_id in enumerate(current["retire_product_gids"], start=1):
                    snapshot = snapshots[product_id]
                    variant = _single_variant(snapshot)
                    inventory_item = variant.get("inventoryItem") or {}
                    await client.set_inventory_quantity(
                        inventory_item_id=str(inventory_item["id"]),
                        location_id=location_id,
                        quantity=0,
                        idempotency_key=f"{operation}:secondary:{index}",
                    )
                    await client.set_product_status(product_id=product_id, status="ARCHIVED")

                verified_anchor = await client.get_product_snapshot(anchor_product_id)
                verified_variant = _single_variant(verified_anchor)
                verified_item = verified_variant.get("inventoryItem") or {}
                if str(verified_anchor.get("status") or "").upper() != "ACTIVE":
                    raise RuntimeError("Published pool anchor is not ACTIVE after consolidation")
                if str(verified_item.get("sku") or "") != target_sku:
                    raise RuntimeError("Published pool SKU did not persist")
                if int(verified_variant.get("inventoryQuantity") or 0) != target_quantity:
                    raise RuntimeError("Published pool quantity did not persist")
                for product_id in current["retire_product_gids"]:
                    retired = await client.get_product_snapshot(product_id)
                    retired_variant = _single_variant(retired)
                    if str(retired.get("status") or "").upper() != "ARCHIVED":
                        raise RuntimeError("Duplicate Shopify product was not archived")
                    if int(retired_variant.get("inventoryQuantity") or 0) != 0:
                        raise RuntimeError("Duplicate Shopify product retained sellable quantity")

                expected_ids = {str(row["inventory_id"]) for row in current["members"]}
                async with connection.transaction():
                    reloaded = await _load_rows(
                        connection,
                        shop_domain=str(settings.shopify_shop_domain),
                        catalogue_id=catalogue_id,
                        language_key=language_key,
                        condition_key=condition_key,
                        for_update=True,
                    )
                    if {str(row["inventory_id"]) for row in reloaded} != expected_ids:
                        raise RuntimeError("Published pool membership changed before database commit")

                    current_by_id = {str(row["inventory_id"]): row for row in current["members"]}
                    ordered = sorted(
                        reloaded,
                        key=lambda row: (
                            0 if _clean(row["shopify_product_gid"]) == anchor_product_id else 1,
                            int(row.get("allocation_priority") or 999999),
                            str(row.get("linked_at") or ""),
                            _clean(row["inventory_code"]),
                        ),
                    )
                    for priority, row in enumerate(ordered, start=1):
                        old = current_by_id[str(row["inventory_id"])]
                        old_values = {
                            "listing_key": old["listing_key"],
                            "allocation_priority": old["allocation_priority"],
                            "shopify_product_gid": old["shopify_product_gid"],
                            "shopify_variant_gid": old["shopify_variant_gid"],
                            "shopify_inventory_item_gid": old["shopify_inventory_item_gid"],
                            "sku": old["sku"],
                            "synced_price_minor": old["synced_price_minor"],
                            "sync_state": old["sync_state"],
                            "version": old["link_version"],
                        }
                        updated = await connection.fetchrow(
                            """
                            update tcg.shopify_inventory_links
                            set listing_key=$2,
                                allocation_priority=$3,
                                shopify_product_gid=$4,
                                shopify_variant_gid=$5,
                                shopify_inventory_item_gid=$6,
                                shopify_location_gid=$7,
                                shopify_publication_gid=$8,
                                sku=$9,
                                synced_price_minor=$10,
                                last_synced_at=clock_timestamp(),
                                version=version+1
                            where id=$1 and version=$11 and sync_state='PUBLISHED'
                            returning id
                            """,
                            row["link_id"],
                            listing_key,
                            priority,
                            anchor_product_id,
                            anchor_variant_id,
                            anchor_inventory_item_id,
                            location_id,
                            publication_id,
                            target_sku,
                            target_price,
                            row["link_version"],
                        )
                        if updated is None:
                            raise RuntimeError("Published Shopify inventory link changed during commit")
                        await connection.execute(
                            "select tcg.record_shopify_raw_pool_audit($1,$2,$3::jsonb,$4::jsonb)",
                            request_id,
                            row["inventory_id"],
                            json.dumps(old_values, default=str),
                            json.dumps({
                                "listing_key": listing_key,
                                "allocation_priority": priority,
                                "shopify_product_gid": anchor_product_id,
                                "shopify_variant_gid": anchor_variant_id,
                                "shopify_inventory_item_gid": anchor_inventory_item_id,
                                "sku": target_sku,
                                "synced_price_minor": target_price,
                                "sync_state": "PUBLISHED",
                                "quantity": target_quantity,
                                "migration": "PUBLISHED_POOL_PHASE_B",
                            }),
                        )

                return {
                    "listing_key": listing_key,
                    "status": "POOLED",
                    "quantity": target_quantity,
                    "product_gid": anchor_product_id,
                    "variant_gid": anchor_variant_id,
                    "archived_products": current["retire_product_gids"],
                }
            except Exception:
                if remote_changed:
                    await _compensate(
                        client,
                        snapshots=snapshots,
                        location_id=location_id,
                        key=f"{operation}:compensate",
                    )
                raise
        finally:
            try:
                await connection.execute(
                    "select pg_advisory_unlock(hashtextextended($1,0))",
                    listing_key,
                )
            finally:
                await connection.execute("select set_config('tcg.user_id','',false)")
                await connection.execute("select set_config('tcg.request_id','',false)")


@router.get("/published-raw-plan")
async def published_raw_plan(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    if not settings.shopify_shop_domain:
        raise HTTPException(status_code=409, detail="Shopify shop domain is not configured")
    async with request.app.state.db_pool.acquire() as connection:
        await _set_actor(connection, user.user_id, request.state.request_id)
        try:
            rows = await _load_rows(
                connection,
                shop_domain=str(settings.shopify_shop_domain),
            )
        finally:
            await connection.execute("select set_config('tcg.user_id','',false)")
            await connection.execute("select set_config('tcg.request_id','',false)")

    groups = _groups(rows)
    ready = [group for group in groups if group["ready"]]
    blocked = [group for group in groups if not group["ready"]]
    return jsonable_encoder({
        "mode": "PLAN_ONLY",
        "groups": len(groups),
        "ready_groups": len(ready),
        "ready_items": sum(int(group["quantity"]) for group in ready),
        "blocked_groups": len(blocked),
        "ready": ready,
        "blocked": blocked[:50],
    })


@router.post("/published-raw-apply")
async def apply_published_raw_pools(
    payload: PublishedRawPoolApplyRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    if not settings.shopify_shop_domain:
        raise HTTPException(status_code=409, detail="Shopify shop domain is not configured")
    client = _shopify_client(settings)

    async with request.app.state.db_pool.acquire() as connection:
        await _set_actor(connection, user.user_id, request.state.request_id)
        try:
            rows = await _load_rows(
                connection,
                shop_domain=str(settings.shopify_shop_domain),
            )
        finally:
            await connection.execute("select set_config('tcg.user_id','',false)")
            await connection.execute("select set_config('tcg.request_id','',false)")

    selected = [group for group in _groups(rows) if group["ready"]][: payload.max_groups]
    results: list[dict[str, Any]] = []
    for group in selected:
        try:
            results.append(
                await _apply_one(
                    request.app.state.db_pool,
                    settings=settings,
                    client=client,
                    actor_user_id=user.user_id,
                    seed=group,
                )
            )
        except ShopifyApiError as exc:
            results.append({
                "listing_key": group["pool"]["listing_key"],
                "status": "SHOPIFY_ERROR",
                "detail": exc.detail,
                "retryable": exc.retryable,
            })
        except Exception as exc:
            logger.exception("Published raw pooling failed for %s", group["pool"]["listing_key"])
            results.append({
                "listing_key": group["pool"]["listing_key"],
                "status": "ERROR",
                "detail": str(exc)[:500],
            })

    return jsonable_encoder({
        "status": "COMPLETE",
        "selected_groups": len(selected),
        "pooled_groups": sum(1 for row in results if row["status"] == "POOLED"),
        "blocked_groups": sum(1 for row in results if row["status"] in {"BLOCKED", "BUSY"}),
        "failed_groups": sum(1 for row in results if row["status"] in {"ERROR", "SHOPIFY_ERROR"}),
        "results": results,
    })
