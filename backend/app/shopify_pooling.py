from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from typing import Annotated, Any, Mapping
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .settings import Settings, get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/shopify/pooling", tags=["shopify-pooling"])


class DraftRawPoolApplyRequest(BaseModel):
    max_groups: int = Field(default=25, ge=1, le=50)


class DraftRawPoolPublishRequest(BaseModel):
    max_groups: int = Field(default=25, ge=1, le=50)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _key(value: object) -> str:
    return _clean(value).casefold()


def _money(minor: int) -> str:
    return f"{minor / 100:.2f}"


_SINGLE_COPY_DESCRIPTION = (
    " is an individually tracked physical trading card from Drop Rate inventory."
)
_POOLED_COPY_DESCRIPTION = (
    " is offered from a pool of interchangeable physical copies held by Drop Rate. "
    "Each physical copy is tracked individually in our inventory system."
)
_INVENTORY_ID_ROW = re.compile(
    r"<li><strong>Inventory ID:</strong>.*?</li>",
    flags=re.IGNORECASE | re.DOTALL,
)


def pooled_product_description_html(description_html: str) -> str:
    """Convert the deterministic single-copy description into pooled-safe copy."""

    source = str(description_html or "").strip()
    if not source:
        raise ValueError("Pooled Shopify product description is missing")
    if _POOLED_COPY_DESCRIPTION in source and "Inventory ID:" not in source:
        return source
    if _SINGLE_COPY_DESCRIPTION not in source:
        raise ValueError("Pooled Shopify product description is not a recognised Drop Rate card description")

    pooled = _INVENTORY_ID_ROW.sub("", source)
    pooled = pooled.replace(_SINGLE_COPY_DESCRIPTION, _POOLED_COPY_DESCRIPTION, 1)
    if "Inventory ID:" in pooled:
        raise ValueError("Pooled Shopify product description still exposes a single Inventory ID")
    return pooled


def raw_pool_identity(row: Mapping[str, Any]) -> dict[str, str]:
    """Return the deterministic identity for an interchangeable raw-card offer."""

    catalogue_id = _clean(row.get("catalogue_id"))
    language = _clean(row.get("language") or row.get("catalogue_language"))
    condition = _clean(row.get("condition"))
    if not catalogue_id:
        raise ValueError("catalogue_id is required")
    identity = {
        "catalogue_id": catalogue_id,
        "product_type": "CARD",
        "pooling_mode": "POOLED",
        "language": _key(language),
        "condition": _key(condition),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "fingerprint": digest,
        "listing_key": f"shopify-pool:{digest}",
        "sku": f"DRP-{digest[:20].upper()}",
        "language": language,
        "condition": condition,
    }


def _group_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _clean(row.get("catalogue_id")),
        _key(row.get("language") or row.get("catalogue_language")),
        _key(row.get("condition")),
    )


def _evaluate_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("Pool group cannot be empty")
    identity = raw_pool_identity(rows[0])
    blockers: list[str] = []

    if len(rows) < 2:
        blockers.append("single physical copy")

    prices = {
        int(row["store_price_minor"])
        for row in rows
        if row.get("store_price_minor") is not None
    }
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
    if any(_clean(row.get("sync_state")) != "DRAFT" for row in rows):
        blockers.append("Shopify link is not DRAFT")
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
    if len(publications) != 1:
        blockers.append("Shopify publication mismatch")

    expected_key = _group_key(rows[0])
    if any(_group_key(row) != expected_key for row in rows):
        blockers.append("pool identity mismatch")

    blockers = list(dict.fromkeys(blockers))
    ordered = sorted(
        rows,
        key=lambda row: (
            row.get("linked_at"),
            _clean(row.get("inventory_code")),
            _clean(row.get("inventory_id")),
        ),
    )
    return {
        "pool": identity,
        "ready": not blockers,
        "blockers": blockers,
        "quantity": len(rows),
        "price_minor": next(iter(prices)) if len(prices) == 1 else None,
        "primary_inventory_id": _clean(ordered[0].get("inventory_id")),
        "members": ordered,
    }


async def _load_draft_raw_rows(
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
          i.acquisition_cost_minor,
          i.storage_location_id,
          i.store_price_minor,
          i.version as inventory_version,
          p.product_type,
          p.language as catalogue_language,
          sil.id as link_id,
          sil.created_by_user_id,
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
          sil.test_mode,
          sil.synced_price_minor,
          sil.linked_at,
          sil.reserved_order_reference,
          sil.reserved_line_reference,
          sil.version as link_version,
          exists(
            select 1
            from tcg.listing_inventory_members lim
            where lim.inventory_id=i.id and lim.state <> 'REMOVED'
          ) as has_listing_membership,
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
          and i.sale_intent='FOR_SALE'
          and i.status in ('DRAFT','INSPECTION','APPROVED')
          and p.product_type='CARD'
          and nullif(btrim(coalesce(i.grading_company,'')),'') is null
          and nullif(btrim(coalesce(i.grade,'')),'') is null
        order by i.catalogue_id,i.created_at,i.id
        """,
        shop_domain,
    )
    return [dict(row) for row in rows]


def _build_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_group_key(row)].append(row)
    result = [
        _evaluate_group(members)
        for members in grouped.values()
        if len(members) > 1
    ]
    result.sort(
        key=lambda group: (
            not group["ready"],
            -int(group["quantity"]),
            str(group["pool"]["listing_key"]),
        )
    )
    return result


def _is_consolidated_group(group: Mapping[str, Any]) -> bool:
    members = list(group.get("members") or [])
    if len(members) < 2:
        return False
    pool = group.get("pool")
    if not isinstance(pool, Mapping):
        return False
    listing_key = _clean(pool.get("listing_key"))
    sku = _clean(pool.get("sku"))
    if not listing_key.startswith("shopify-pool:") or not sku.startswith("DRP-"):
        return False
    first = members[0]
    product_gid = _clean(first.get("shopify_product_gid"))
    variant_gid = _clean(first.get("shopify_variant_gid"))
    inventory_item_gid = _clean(first.get("shopify_inventory_item_gid"))
    location_gid = _clean(first.get("shopify_location_gid"))
    if not all((product_gid, variant_gid, inventory_item_gid, location_gid)):
        return False
    return all(
        _clean(row.get("listing_key")) == listing_key
        and _clean(row.get("sku")) == sku
        and _clean(row.get("shopify_product_gid")) == product_gid
        and _clean(row.get("shopify_variant_gid")) == variant_gid
        and _clean(row.get("shopify_inventory_item_gid")) == inventory_item_gid
        and _clean(row.get("shopify_location_gid")) == location_gid
        for row in members
    )


def _public_group(group: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "listing_key": group["pool"]["listing_key"],
        "sku": group["pool"]["sku"],
        "language": group["pool"]["language"],
        "condition": group["pool"]["condition"],
        "quantity": group["quantity"],
        "price_minor": group["price_minor"],
        "ready": group["ready"],
        "blockers": group["blockers"],
        "primary_inventory_id": group["primary_inventory_id"],
        "members": [
            {
                "inventory_id": str(row["inventory_id"]),
                "inventory_code": row["inventory_code"],
                "owner_id": str(row["owner_id"]),
                "shopify_product_gid": row["shopify_product_gid"],
                "shopify_variant_gid": row["shopify_variant_gid"],
            }
            for row in group["members"]
        ],
    }


def _shopify_client(settings: Settings) -> ShopifyAdminClient:
    if not all(
        (
            settings.shopify_shop_domain,
            settings.shopify_client_id,
            settings.shopify_client_secret,
        )
    ):
        raise HTTPException(status_code=409, detail="Shopify configuration is incomplete")
    return ShopifyAdminClient(
        shop_domain=str(settings.shopify_shop_domain),
        client_id=str(settings.shopify_client_id),
        client_secret=str(settings.shopify_client_secret),
        api_version=settings.shopify_api_version,
    )


async def _set_actor(connection: asyncpg.Connection, user_id: UUID, request_id: str) -> None:
    await connection.execute("select set_config('tcg.user_id',$1,false)", str(user_id))
    await connection.execute("select set_config('tcg.request_id',$1,false)", request_id)
    if not await connection.fetchval("select tcg.is_platform_admin()"):
        raise HTTPException(status_code=403, detail="Platform admin access is required")


async def _reload_group(
    connection: asyncpg.Connection,
    *,
    shop_domain: str,
    catalogue_id: UUID,
    language_key: str,
    condition_key: str,
    for_update: bool,
) -> dict[str, Any]:
    lock = " for update of i,sil" if for_update else ""
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
          i.acquisition_cost_minor,
          i.storage_location_id,
          i.store_price_minor,
          i.version as inventory_version,
          p.product_type,
          p.language as catalogue_language,
          sil.id as link_id,
          sil.created_by_user_id,
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
          sil.test_mode,
          sil.synced_price_minor,
          sil.linked_at,
          sil.reserved_order_reference,
          sil.reserved_line_reference,
          sil.version as link_version,
          exists(
            select 1
            from tcg.listing_inventory_members lim
            where lim.inventory_id=i.id and lim.state <> 'REMOVED'
          ) as has_listing_membership,
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
          and i.sale_intent='FOR_SALE'
          and i.catalogue_id=$2
          and lower(btrim(coalesce(i.language,p.language,'')))=$3
          and lower(btrim(coalesce(i.condition,'')))=$4
          and p.product_type='CARD'
          and nullif(btrim(coalesce(i.grading_company,'')),'') is null
          and nullif(btrim(coalesce(i.grade,'')),'') is null
        order by sil.linked_at,i.inventory_code,i.id
        {lock}
        """,
        shop_domain,
        catalogue_id,
        language_key,
        condition_key,
    )
    return _evaluate_group([dict(row) for row in rows])


def _single_variant(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    variants = snapshot.get("variants")
    nodes = variants.get("nodes") if isinstance(variants, Mapping) else None
    if not isinstance(nodes, list) or len(nodes) != 1 or not isinstance(nodes[0], dict):
        raise RuntimeError("Draft raw pool product must have exactly one Shopify variant")
    return nodes[0]


async def _compensate_remote(
    client: ShopifyAdminClient,
    *,
    primary_snapshot: Mapping[str, Any],
    secondary_snapshots: list[Mapping[str, Any]],
    location_id: str,
    compensation_key: str,
) -> None:
    try:
        primary_variant = _single_variant(primary_snapshot)
        primary_item = primary_variant.get("inventoryItem") or {}
        await client.update_variant_pool_identity(
            product_id=str(primary_snapshot["id"]),
            variant_id=str(primary_variant["id"]),
            price=str(primary_variant.get("price") or "0.00"),
            sku=str(primary_item.get("sku") or ""),
        )
        await client.set_inventory_quantity(
            inventory_item_id=str(primary_item["id"]),
            location_id=location_id,
            quantity=int(primary_variant.get("inventoryQuantity") or 0),
            idempotency_key=f"{compensation_key}:primary",
        )
    except Exception:
        logger.exception("Raw pool primary compensation failed")

    for index, snapshot in enumerate(secondary_snapshots, start=1):
        try:
            variant = _single_variant(snapshot)
            inventory_item = variant.get("inventoryItem") or {}
            await client.set_product_status(product_id=str(snapshot["id"]), status="DRAFT")
            await client.set_inventory_quantity(
                inventory_item_id=str(inventory_item["id"]),
                location_id=location_id,
                quantity=int(variant.get("inventoryQuantity") or 0),
                idempotency_key=f"{compensation_key}:secondary:{index}",
            )
        except Exception:
            logger.exception("Raw pool secondary compensation failed for %s", snapshot.get("id"))


async def _apply_one_group(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    client: ShopifyAdminClient,
    actor_user_id: UUID,
    seed_group: Mapping[str, Any],
) -> dict[str, Any]:
    first = seed_group["members"][0]
    catalogue_id = UUID(str(first["catalogue_id"]))
    language_key = _key(first.get("language") or first.get("catalogue_language"))
    condition_key = _key(first.get("condition"))
    lock_key = str(seed_group["pool"]["listing_key"])
    request_id = f"shopify-raw-pool:{uuid4()}"

    async with pool.acquire() as connection:
        await _set_actor(connection, actor_user_id, request_id)
        locked = await connection.fetchval(
            "select pg_try_advisory_lock(hashtextextended($1,0))",
            lock_key,
        )
        if not locked:
            return {
                "listing_key": lock_key,
                "status": "BUSY",
                "detail": "Another raw-pool operation already holds this group lock",
            }
        try:
            async with connection.transaction():
                current = await _reload_group(
                    connection,
                    shop_domain=str(settings.shopify_shop_domain),
                    catalogue_id=catalogue_id,
                    language_key=language_key,
                    condition_key=condition_key,
                    for_update=True,
                )
            if not current["ready"]:
                return {
                    "listing_key": lock_key,
                    "status": "BLOCKED",
                    "blockers": current["blockers"],
                }

            members = current["members"]
            primary = members[0]
            expected_ids = {str(row["inventory_id"]) for row in members}
            target_key = str(current["pool"]["listing_key"])
            target_sku = str(current["pool"]["sku"])
            target_price_minor = int(current["price_minor"])
            location_id = str(primary["shopify_location_gid"])

            if all(
                str(row["listing_key"]) == target_key
                and str(row["shopify_product_gid"]) == str(primary["shopify_product_gid"])
                and str(row["shopify_variant_gid"]) == str(primary["shopify_variant_gid"])
                and str(row["sku"]) == target_sku
                for row in members
            ):
                return {
                    "listing_key": target_key,
                    "status": "ALREADY_POOLED",
                    "quantity": len(members),
                    "primary_product_gid": str(primary["shopify_product_gid"]),
                }

            snapshots: list[dict[str, Any]] = []
            for row in members:
                snapshot = await client.get_product_snapshot(str(row["shopify_product_gid"]))
                if str(snapshot.get("status") or "").upper() != "DRAFT":
                    return {
                        "listing_key": target_key,
                        "status": "BLOCKED",
                        "blockers": ["remote Shopify product is not DRAFT"],
                    }
                variant = _single_variant(snapshot)
                inventory_item = variant.get("inventoryItem")
                if not isinstance(inventory_item, Mapping):
                    raise RuntimeError("Shopify draft variant has no inventory item")
                if str(variant.get("id")) != str(row["shopify_variant_gid"]):
                    raise RuntimeError("Shopify variant changed during raw pool planning")
                if str(inventory_item.get("id")) != str(row["shopify_inventory_item_gid"]):
                    raise RuntimeError("Shopify inventory item changed during raw pool planning")
                snapshots.append(snapshot)

            primary_snapshot = snapshots[0]
            secondary_snapshots = snapshots[1:]
            primary_variant = _single_variant(primary_snapshot)
            primary_inventory_item = primary_variant["inventoryItem"]
            operation_token = uuid4().hex[:12]
            operation_key = (
                f"raw-pool:{current['pool']['fingerprint'][:16]}:{operation_token}"
            )
            compensation_key = f"{operation_key}:compensate"

            remote_changed = False
            try:
                await client.update_variant_pool_identity(
                    product_id=str(primary_snapshot["id"]),
                    variant_id=str(primary_variant["id"]),
                    price=_money(target_price_minor),
                    sku=target_sku,
                )
                remote_changed = True
                await client.set_inventory_quantity(
                    inventory_item_id=str(primary_inventory_item["id"]),
                    location_id=location_id,
                    quantity=len(members),
                    idempotency_key=f"{operation_key}:primary",
                )


                for index, snapshot in enumerate(secondary_snapshots, start=1):
                    variant = _single_variant(snapshot)
                    inventory_item = variant["inventoryItem"]
                    await client.set_inventory_quantity(
                        inventory_item_id=str(inventory_item["id"]),
                        location_id=location_id,
                        quantity=0,
                        idempotency_key=f"{operation_key}:secondary:{index}",
                    )
                    await client.set_product_status(
                        product_id=str(snapshot["id"]),
                        status="ARCHIVED",
                    )

                async with connection.transaction():
                    rechecked = await _reload_group(
                        connection,
                        shop_domain=str(settings.shopify_shop_domain),
                        catalogue_id=catalogue_id,
                        language_key=language_key,
                        condition_key=condition_key,
                        for_update=True,
                    )
                    if not rechecked["ready"]:
                        raise RuntimeError("Raw pool readiness changed before database commit")
                    rechecked_ids = {str(row["inventory_id"]) for row in rechecked["members"]}
                    if rechecked_ids != expected_ids:
                        raise RuntimeError("Raw pool membership changed before database commit")

                    for priority, row in enumerate(rechecked["members"], start=1):
                        old_values = {
                            "listing_key": row["listing_key"],
                            "allocation_priority": row["allocation_priority"],
                            "shopify_product_gid": row["shopify_product_gid"],
                            "shopify_variant_gid": row["shopify_variant_gid"],
                            "shopify_inventory_item_gid": row["shopify_inventory_item_gid"],
                            "sku": row["sku"],
                            "synced_price_minor": row["synced_price_minor"],
                            "version": row["link_version"],
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
                            where id=$1
                              and version=$11
                              and sync_state='DRAFT'
                            returning *
                            """,
                            row["link_id"],
                            target_key,
                            priority,
                            str(primary["shopify_product_gid"]),
                            str(primary["shopify_variant_gid"]),
                            str(primary["shopify_inventory_item_gid"]),
                            location_id,
                            primary["shopify_publication_gid"],
                            target_sku,
                            target_price_minor,
                            row["link_version"],
                        )
                        if updated is None:
                            raise RuntimeError("Shopify inventory link changed during raw pool commit")
                        await connection.execute(
                            """
                            select tcg.record_shopify_raw_pool_audit(
                                $1,$2,$3::jsonb,$4::jsonb
                            )
                            """,
                            request_id,
                            row["inventory_id"],
                            json.dumps(old_values, default=str),
                            json.dumps({
                                "listing_key": target_key,
                                "allocation_priority": priority,
                                "shopify_product_gid": primary["shopify_product_gid"],
                                "shopify_variant_gid": primary["shopify_variant_gid"],
                                "shopify_inventory_item_gid": primary["shopify_inventory_item_gid"],
                                "sku": target_sku,
                                "synced_price_minor": target_price_minor,
                                "quantity": len(members),
                            }, default=str),
                        )

                return {
                    "listing_key": target_key,
                    "status": "POOLED",
                    "quantity": len(members),
                    "price_minor": target_price_minor,
                    "sku": target_sku,
                    "primary_inventory_id": str(primary["inventory_id"]),
                    "primary_product_gid": str(primary["shopify_product_gid"]),
                    "archived_secondary_products": [
                        str(snapshot["id"]) for snapshot in secondary_snapshots
                    ],
                }
            except Exception:
                if remote_changed:
                    await _compensate_remote(
                        client,
                        primary_snapshot=primary_snapshot,
                        secondary_snapshots=secondary_snapshots,
                        location_id=location_id,
                        compensation_key=compensation_key,
                    )
                raise
        finally:
            try:
                await connection.execute(
                    "select pg_advisory_unlock(hashtextextended($1,0))",
                    lock_key,
                )
            finally:
                await connection.execute("select set_config('tcg.user_id','',false)")
                await connection.execute("select set_config('tcg.request_id','',false)")


async def _publish_one_group(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    client: ShopifyAdminClient,
    actor_user_id: UUID,
    seed_group: Mapping[str, Any],
) -> dict[str, Any]:
    first = seed_group["members"][0]
    catalogue_id = UUID(str(first["catalogue_id"]))
    language_key = _key(first.get("language") or first.get("catalogue_language"))
    condition_key = _key(first.get("condition"))
    lock_key = str(seed_group["pool"]["listing_key"])
    request_id = f"shopify-raw-pool-publish:{uuid4()}"

    async with pool.acquire() as connection:
        await _set_actor(connection, actor_user_id, request_id)
        locked = await connection.fetchval(
            "select pg_try_advisory_lock(hashtextextended($1,0))",
            lock_key,
        )
        if not locked:
            return {
                "listing_key": lock_key,
                "status": "BUSY",
                "detail": "Another raw-pool operation already holds this group lock",
            }
        try:
            async with connection.transaction():
                current = await _reload_group(
                    connection,
                    shop_domain=str(settings.shopify_shop_domain),
                    catalogue_id=catalogue_id,
                    language_key=language_key,
                    condition_key=condition_key,
                    for_update=True,
                )
            if not current["ready"]:
                return {
                    "listing_key": lock_key,
                    "status": "BLOCKED",
                    "blockers": current["blockers"],
                }
            if not _is_consolidated_group(current):
                return {
                    "listing_key": lock_key,
                    "status": "BLOCKED",
                    "blockers": ["raw group is not yet consolidated onto one Shopify variant"],
                }

            members = current["members"]
            primary = members[0]
            product_id = str(primary["shopify_product_gid"])
            variant_id = str(primary["shopify_variant_gid"])
            inventory_item_id = str(primary["shopify_inventory_item_gid"])
            publication_id = str(
                settings.shopify_publication_gid
                or primary.get("shopify_publication_gid")
                or ""
            )
            if not publication_id:
                return {
                    "listing_key": lock_key,
                    "status": "BLOCKED",
                    "blockers": ["Shopify publication is not configured"],
                }

            snapshot = await client.get_product_snapshot(product_id)
            if str(snapshot.get("status") or "").upper() != "DRAFT":
                return {
                    "listing_key": lock_key,
                    "status": "BLOCKED",
                    "blockers": ["pooled Shopify product is not DRAFT"],
                }

            pooled_description = pooled_product_description_html(
                str(snapshot.get("descriptionHtml") or "")
            )
            if _clean(snapshot.get("descriptionHtml")) != _clean(pooled_description):
                await client.update_product(
                    product_id=product_id,
                    product={"descriptionHtml": pooled_description},
                )
                snapshot = await client.get_product_snapshot(product_id)
                if str(snapshot.get("status") or "").upper() != "DRAFT":
                    raise RuntimeError(
                        "Pooled Shopify product status changed while correcting public copy"
                    )
                if _clean(snapshot.get("descriptionHtml")) != _clean(pooled_description):
                    raise RuntimeError("Pooled Shopify description did not persist")

            media = snapshot.get("media")
            media_nodes = media.get("nodes") if isinstance(media, Mapping) else None
            if not isinstance(media_nodes, list) or not media_nodes:
                return {
                    "listing_key": lock_key,
                    "status": "BLOCKED",
                    "blockers": ["pooled Shopify product has no image"],
                }

            variant = _single_variant(snapshot)
            inventory_item = variant.get("inventoryItem")
            if not isinstance(inventory_item, Mapping):
                raise RuntimeError("Pooled Shopify variant has no inventory item")
            if str(variant.get("id") or "") != variant_id:
                raise RuntimeError("Pooled Shopify variant changed before publication")
            if str(inventory_item.get("id") or "") != inventory_item_id:
                raise RuntimeError("Pooled Shopify inventory item changed before publication")
            if str(inventory_item.get("sku") or "") != str(current["pool"]["sku"]):
                raise RuntimeError("Pooled Shopify SKU does not match backend pool")
            if inventory_item.get("tracked") is not True:
                raise RuntimeError("Pooled Shopify inventory is not tracked")
            if str(variant.get("inventoryPolicy") or "").upper() != "DENY":
                raise RuntimeError("Pooled Shopify variant allows overselling")
            if str(variant.get("price") or "") != _money(int(current["price_minor"])):
                raise RuntimeError("Pooled Shopify price does not match backend pool")
            if int(variant.get("inventoryQuantity") or 0) != len(members):
                raise RuntimeError("Pooled Shopify quantity does not match physical member count")

            await client.set_product_status(product_id=product_id, status="ACTIVE")
            await client.publish_product(
                product_id=product_id,
                publication_id=publication_id,
            )
            if not await client.product_published_on_publication(
                product_id=product_id,
                publication_id=publication_id,
            ):
                try:
                    await client.set_product_status(product_id=product_id, status="DRAFT")
                except Exception:
                    logger.exception(
                        "Pooled publication compensation failed for %s",
                        lock_key,
                    )
                raise RuntimeError("Pooled Shopify publication verification failed")

            expected_ids = {str(row["inventory_id"]) for row in members}
            try:
                async with connection.transaction():
                    rows = await connection.fetch(
                        """
                        select
                          sil.*,
                          i.status as inventory_status,
                          i.sale_intent as inventory_sale_intent
                        from tcg.shopify_inventory_links sil
                        join tcg.inventory_items i on i.id=sil.inventory_id
                        where sil.shop_domain=$1
                          and sil.listing_key=$2
                        order by sil.allocation_priority,sil.linked_at,sil.id
                        for update of sil,i
                        """,
                        str(settings.shopify_shop_domain),
                        lock_key,
                    )
                    if {str(row["inventory_id"]) for row in rows} != expected_ids:
                        raise RuntimeError("Pooled membership changed before publication commit")
                    if any(row["sync_state"] != "DRAFT" for row in rows):
                        raise RuntimeError("Pooled link state changed before publication commit")
                    if any(row["inventory_status"] != "APPROVED" for row in rows):
                        raise RuntimeError("Pooled inventory is no longer APPROVED")
                    if any(row["inventory_sale_intent"] != "FOR_SALE" for row in rows):
                        raise RuntimeError("Pooled inventory is no longer FOR_SALE")
                    if any(
                        row["reserved_order_reference"] or row["reserved_line_reference"]
                        for row in rows
                    ):
                        raise RuntimeError("Pooled inventory became reserved before publication commit")

                    for row in rows:
                        result = await connection.execute(
                            """
                            update tcg.shopify_inventory_links
                            set sync_state='PUBLISHED',
                                last_synced_at=clock_timestamp(),
                                version=version+1
                            where id=$1
                              and sync_state='DRAFT'
                            """,
                            row["id"],
                        )
                        if not str(result).endswith("1"):
                            raise RuntimeError(
                                "Pooled publication did not update exactly one physical link"
                            )
                        await connection.execute(
                            """
                            select tcg.record_shopify_raw_pool_published_audit(
                                $1,$2,$3::jsonb,$4::jsonb
                            )
                            """,
                            request_id,
                            row["inventory_id"],
                            json.dumps({
                                "listing_key": lock_key,
                                "sync_state": "DRAFT",
                            }),
                            json.dumps({
                                "listing_key": lock_key,
                                "sync_state": "PUBLISHED",
                                "shopify_product_gid": product_id,
                                "shopify_variant_gid": variant_id,
                                "quantity": len(rows),
                            }),
                        )
            except Exception:
                try:
                    await client.set_product_status(product_id=product_id, status="DRAFT")
                except Exception:
                    logger.exception(
                        "Pooled publication database compensation failed for %s",
                        lock_key,
                    )
                raise

            return {
                "listing_key": lock_key,
                "status": "PUBLISHED",
                "quantity": len(members),
                "product_gid": product_id,
                "variant_gid": variant_id,
            }
        finally:
            try:
                await connection.execute(
                    "select pg_advisory_unlock(hashtextextended($1,0))",
                    lock_key,
                )
            finally:
                await connection.execute("select set_config('tcg.user_id','',false)")
                await connection.execute("select set_config('tcg.request_id','',false)")


@router.get("/draft-raw-plan")
async def draft_raw_pool_plan(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    settings = get_settings()
    if not settings.shopify_shop_domain:
        raise HTTPException(status_code=409, detail="Shopify shop domain is not configured")

    async with request.app.state.db_pool.acquire() as connection:
        await _set_actor(connection, user.user_id, request.state.request_id)
        try:
            rows = await _load_draft_raw_rows(
                connection,
                shop_domain=str(settings.shopify_shop_domain),
            )
        finally:
            await connection.execute("select set_config('tcg.user_id','',false)")
            await connection.execute("select set_config('tcg.request_id','',false)")

    groups = _build_groups(rows)
    ready = [group for group in groups if group["ready"]]
    blocked = [group for group in groups if not group["ready"]]
    blocker_counts: dict[str, int] = {}
    for group in blocked:
        for blocker in group["blockers"]:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1

    return jsonable_encoder({
        "mode": "PLAN_ONLY",
        "shop_domain": settings.shopify_shop_domain,
        "groups": len(groups),
        "physical_items": sum(int(group["quantity"]) for group in groups),
        "ready_groups": len(ready),
        "ready_items": sum(int(group["quantity"]) for group in ready),
        "blocked_groups": len(blocked),
        "blockers": blocker_counts,
        "ready": [_public_group(group) for group in ready],
        "blocked": [_public_group(group) for group in blocked[:50]],
    })


@router.post("/draft-raw-apply")
async def apply_draft_raw_pools(
    payload: DraftRawPoolApplyRequest,
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
            rows = await _load_draft_raw_rows(
                connection,
                shop_domain=str(settings.shopify_shop_domain),
            )
        finally:
            await connection.execute("select set_config('tcg.user_id','',false)")
            await connection.execute("select set_config('tcg.request_id','',false)")

    ready = [group for group in _build_groups(rows) if group["ready"]]
    selected = ready[: payload.max_groups]
    results: list[dict[str, Any]] = []
    for group in selected:
        try:
            results.append(
                await _apply_one_group(
                    request.app.state.db_pool,
                    settings=settings,
                    client=client,
                    actor_user_id=user.user_id,
                    seed_group=group,
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
            logger.exception("Draft raw pooling failed for %s", group["pool"]["listing_key"])
            results.append({
                "listing_key": group["pool"]["listing_key"],
                "status": "ERROR",
                "detail": str(exc)[:500],
            })

    return jsonable_encoder({
        "status": "COMPLETE",
        "selected_groups": len(selected),
        "pooled_groups": sum(1 for row in results if row["status"] == "POOLED"),
        "already_pooled_groups": sum(
            1 for row in results if row["status"] == "ALREADY_POOLED"
        ),
        "blocked_groups": sum(1 for row in results if row["status"] in {"BLOCKED","BUSY"}),
        "failed_groups": sum(
            1 for row in results if row["status"] in {"ERROR","SHOPIFY_ERROR"}
        ),
        "results": results,
    })


@router.post("/draft-raw-publish")
async def publish_draft_raw_pools(
    payload: DraftRawPoolPublishRequest,
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
            rows = await _load_draft_raw_rows(
                connection,
                shop_domain=str(settings.shopify_shop_domain),
            )
        finally:
            await connection.execute("select set_config('tcg.user_id','',false)")
            await connection.execute("select set_config('tcg.request_id','',false)")

    consolidated = [
        group
        for group in _build_groups(rows)
        if group["ready"] and _is_consolidated_group(group)
    ]
    selected = consolidated[: payload.max_groups]
    results: list[dict[str, Any]] = []
    for group in selected:
        try:
            results.append(
                await _publish_one_group(
                    request.app.state.db_pool,
                    settings=settings,
                    client=client,
                    actor_user_id=user.user_id,
                    seed_group=group,
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
            logger.exception(
                "Draft raw pool publication failed for %s",
                group["pool"]["listing_key"],
            )
            results.append({
                "listing_key": group["pool"]["listing_key"],
                "status": "ERROR",
                "detail": str(exc)[:500],
            })

    return jsonable_encoder({
        "status": "COMPLETE",
        "selected_groups": len(selected),
        "published_groups": sum(1 for row in results if row["status"] == "PUBLISHED"),
        "blocked_groups": sum(1 for row in results if row["status"] in {"BLOCKED","BUSY"}),
        "failed_groups": sum(
            1 for row in results if row["status"] in {"ERROR","SHOPIFY_ERROR"}
        ),
        "results": results,
    })
