from __future__ import annotations

import json
import logging
from collections import Counter
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID, uuid4

import asyncpg

from .db import user_connection
from .settings import Settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError
from .shopify_linked_draft_reconciliation import (
    ReconciliationBlocked,
    _prepare_core,
    parse_language_map,
)
from .shopify_pooled_offers import build_shopify_offer_plan


logger = logging.getLogger(__name__)


def _money(minor: int) -> str:
    return f"{Decimal(int(minor)) / Decimal(100):.2f}"


def _first_variant(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    variants = snapshot.get("variants")
    nodes = variants.get("nodes") if isinstance(variants, Mapping) else None
    if not isinstance(nodes, list) or len(nodes) != 1 or not isinstance(nodes[0], Mapping):
        raise RuntimeError("Pooled offer anchor must have exactly one Shopify variant")
    return nodes[0]


def _member_ids(offer: Mapping[str, Any]) -> list[UUID]:
    return [UUID(str(row["inventory_id"])) for row in offer["members"]]


def _already_pooled(offer: Mapping[str, Any]) -> bool:
    target = offer["target"]
    return all(
        str(member.get("current_listing_key") or "") == str(offer["listing_key"])
        and str(member.get("current_sku") or "") == str(offer["sku"])
        and str(member.get("current_product_gid") or "")
        == str(target["shopify_product_gid"])
        and str(member.get("current_variant_gid") or "")
        == str(target["shopify_variant_gid"])
        and str(member.get("current_inventory_item_gid") or "")
        == str(target["shopify_inventory_item_gid"])
        and str(member.get("current_location_gid") or "")
        == str(target["shopify_location_gid"])
        for member in offer["members"]
    )


async def _candidate_ids(
    pool: asyncpg.Pool,
    *,
    actor_user_id: UUID,
    shop_domain: str,
) -> list[UUID]:
    async with user_connection(
        pool,
        actor_user_id,
        f"shopify-pooled-offer-candidates:{uuid4()}",
    ) as connection:
        rows = await connection.fetch(
            """
            select i.id
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            join tcg.shopify_inventory_links sil on sil.inventory_id=i.id
            where p.product_type='CARD'
              and nullif(btrim(coalesce(i.grading_company,'')),'') is null
              and nullif(btrim(coalesce(i.grade,'')),'') is null
              and i.sale_intent='FOR_SALE'
              and i.status in ('DRAFT','INSPECTION','APPROVED')
              and sil.shop_domain=$1
              and sil.test_mode=false
              and sil.sync_state in ('DRAFT','PUBLISHED')
            order by i.created_at,i.id
            """,
            shop_domain,
        )
    return [row["id"] for row in rows]


async def _prepare_candidates_read_only(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    actor_user_id: UUID,
    inventory_ids: list[UUID],
    language_map: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    prepared: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for inventory_id in inventory_ids:
        try:
            item, changes = await _prepare_core(
                pool,
                settings=settings,
                actor_user_id=actor_user_id,
                inventory_id=inventory_id,
                language_map=language_map,
                apply=False,
            )
        except ReconciliationBlocked as exc:
            blocked.append(
                {
                    "inventory_id": str(inventory_id),
                    "code": exc.code,
                    "detail": exc.detail,
                }
            )
            continue
        item = dict(item)
        item["planned_core_changes"] = list(changes)
        prepared.append(item)
    return prepared, blocked


async def _prepare_offer_for_apply(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    actor_user_id: UUID,
    planned_offer: Mapping[str, Any],
    language_map: Mapping[str, str],
) -> Mapping[str, Any]:
    prepared: list[dict[str, Any]] = []
    for inventory_id in _member_ids(planned_offer):
        item, _changes = await _prepare_core(
            pool,
            settings=settings,
            actor_user_id=actor_user_id,
            inventory_id=inventory_id,
            language_map=language_map,
            apply=True,
        )
        prepared.append(dict(item))

    current_plan = build_shopify_offer_plan(prepared)
    matches = [
        offer
        for offer in current_plan["offers"]
        if offer["listing_fingerprint"] == planned_offer["listing_fingerprint"]
    ]
    if len(matches) != 1:
        raise RuntimeError("Pooled offer shape changed during APPLY preparation")
    current_offer = matches[0]
    if (
        current_offer["pooling_mode"] != "POOLED"
        or current_offer["quantity"] != planned_offer["quantity"]
        or not current_offer["ready"]
    ):
        raise RuntimeError("Pooled offer is no longer eligible for conversion")
    return current_offer


async def _repoint_links(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    actor_user_id: UUID,
    offer: Mapping[str, Any],
    desired_sync_state: str,
) -> None:
    ids = _member_ids(offer)
    target = offer["target"]
    request_id = f"shopify-pooled-offer-repoint:{uuid4()}"

    async with user_connection(
        pool,
        actor_user_id,
        request_id,
    ) as connection:
        rows = await connection.fetch(
            """
            select sil.*,i.status as inventory_status,i.sale_intent
            from tcg.shopify_inventory_links sil
            join tcg.inventory_items i on i.id=sil.inventory_id
            where sil.inventory_id=any($1::uuid[])
              and sil.shop_domain=$2
            order by sil.inventory_id
            for update of sil,i
            """,
            ids,
            str(settings.shopify_shop_domain),
        )
        if len(rows) != len(ids):
            raise RuntimeError("Pooled offer link set changed before database repoint")

        by_inventory = {str(row["inventory_id"]): row for row in rows}
        for member in offer["members"]:
            row = by_inventory.get(str(member["inventory_id"]))
            if row is None:
                raise RuntimeError("Pooled offer member disappeared before database repoint")
            if row["inventory_status"] != "APPROVED" or row["sale_intent"] != "FOR_SALE":
                raise RuntimeError("Pooled offer member is no longer sellable")
            if row["reserved_order_reference"] or row["reserved_line_reference"]:
                raise RuntimeError("Pooled offer member became reserved during conversion")
            if row["sync_state"] not in {"DRAFT", "PUBLISHED"}:
                raise RuntimeError("Pooled offer Shopify link changed state during conversion")

        for member in offer["members"]:
            current = by_inventory[str(member["inventory_id"])]
            old_values = {
                "listing_key": str(current["listing_key"]),
                "allocation_priority": int(current["allocation_priority"]),
                "shopify_product_gid": str(current["shopify_product_gid"]),
                "shopify_variant_gid": str(current["shopify_variant_gid"]),
                "shopify_inventory_item_gid": str(current["shopify_inventory_item_gid"]),
                "shopify_location_gid": str(current["shopify_location_gid"]),
                "sku": str(current["sku"]),
                "sync_state": str(current["sync_state"]),
                "synced_price_minor": int(current["synced_price_minor"]),
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
                    sync_state=$10,
                    synced_price_minor=$11,
                    reserved_order_reference=null,
                    reserved_line_reference=null,
                    reserved_at=null,
                    last_synced_at=clock_timestamp(),
                    version=version+1
                where id=$1
                  and sync_state in ('DRAFT','PUBLISHED')
                  and reserved_order_reference is null
                  and reserved_line_reference is null
                returning *
                """,
                current["id"],
                str(offer["listing_key"]),
                int(member["allocation_priority"]),
                str(target["shopify_product_gid"]),
                str(target["shopify_variant_gid"]),
                str(target["shopify_inventory_item_gid"]),
                str(target["shopify_location_gid"]),
                str(settings.shopify_publication_gid or current["shopify_publication_gid"] or ""),
                str(offer["sku"]),
                desired_sync_state,
                int(offer["store_price_minor"]),
            )
            if updated is None:
                raise RuntimeError("Pooled offer link changed during database repoint")
            new_values = {
                "listing_key": str(updated["listing_key"]),
                "allocation_priority": int(updated["allocation_priority"]),
                "shopify_product_gid": str(updated["shopify_product_gid"]),
                "shopify_variant_gid": str(updated["shopify_variant_gid"]),
                "shopify_inventory_item_gid": str(updated["shopify_inventory_item_gid"]),
                "shopify_location_gid": str(updated["shopify_location_gid"]),
                "sku": str(updated["sku"]),
                "sync_state": str(updated["sync_state"]),
                "synced_price_minor": int(updated["synced_price_minor"]),
            }
            await connection.execute(
                """
                insert into tcg.audit_events(
                    actor,request_id,action,entity_type,entity_id,old_values,new_values
                ) values(
                    $1,$2,'SHOPIFY_LINK_POOLED_CONVERSION',
                    'SHOPIFY_INVENTORY_LINK',$3,$4::jsonb,$5::jsonb
                )
                """,
                str(actor_user_id),
                request_id,
                updated["inventory_id"],
                json.dumps(old_values),
                json.dumps(new_values),
            )


async def _verify_anchor_draft(
    client: ShopifyAdminClient,
    *,
    offer: Mapping[str, Any],
) -> None:
    target = offer["target"]
    snapshot = await client.get_product_snapshot(str(target["shopify_product_gid"]))
    if str(snapshot.get("status") or "").upper() != "DRAFT":
        raise RuntimeError("Pooled offer anchor must remain DRAFT during quantity verification")
    variant = _first_variant(snapshot)
    if str(variant.get("id") or "") != str(target["shopify_variant_gid"]):
        raise RuntimeError("Pooled offer anchor variant changed during conversion")
    if str(variant.get("price") or "") != _money(int(offer["store_price_minor"])):
        raise RuntimeError("Pooled offer price verification failed")
    if str(variant.get("inventoryPolicy") or "").upper() != "DENY":
        raise RuntimeError("Pooled offer oversell policy verification failed")
    inventory_item = variant.get("inventoryItem")
    if not isinstance(inventory_item, Mapping):
        raise RuntimeError("Pooled offer inventory item is missing")
    if str(inventory_item.get("id") or "") != str(target["shopify_inventory_item_gid"]):
        raise RuntimeError("Pooled offer inventory item changed during conversion")
    if str(inventory_item.get("sku") or "") != str(offer["sku"]):
        raise RuntimeError("Pooled offer SKU verification failed")
    if inventory_item.get("tracked") is not True:
        raise RuntimeError("Pooled offer inventory tracking verification failed")
    if int(variant.get("inventoryQuantity") or 0) != int(offer["quantity"]):
        raise RuntimeError("Pooled offer quantity verification failed")


async def _reconcile_existing_pool(
    client: ShopifyAdminClient,
    *,
    settings: Settings,
    offer: Mapping[str, Any],
) -> dict[str, Any]:
    target = offer["target"]
    live = any(member["sync_state"] == "PUBLISHED" for member in offer["members"])
    await client.set_product_status(
        product_id=str(target["shopify_product_gid"]),
        status="DRAFT",
    )
    await client.update_pooled_offer_variant(
        product_id=str(target["shopify_product_gid"]),
        variant_id=str(target["shopify_variant_gid"]),
        price=_money(int(offer["store_price_minor"])),
        sku=str(offer["sku"]),
    )
    await client.activate_inventory(
        inventory_item_id=str(target["shopify_inventory_item_gid"]),
        location_id=str(target["shopify_location_gid"]),
        idempotency_key=f"pool-activate-{offer['listing_fingerprint'][:20]}",
    )
    await client.set_inventory_quantity(
        inventory_item_id=str(target["shopify_inventory_item_gid"]),
        location_id=str(target["shopify_location_gid"]),
        quantity=int(offer["quantity"]),
        idempotency_key=(
            f"pool-quantity-{offer['listing_fingerprint'][:20]}-{offer['quantity']}"
        ),
    )
    await _verify_anchor_draft(client, offer=offer)
    if live:
        await client.set_product_status(
            product_id=str(target["shopify_product_gid"]),
            status="ACTIVE",
        )
        await client.publish_product(
            product_id=str(target["shopify_product_gid"]),
            publication_id=str(settings.shopify_publication_gid),
        )
        published = await client.product_published_on_publication(
            product_id=str(target["shopify_product_gid"]),
            publication_id=str(settings.shopify_publication_gid),
        )
        if not published:
            raise RuntimeError("Pooled offer publication verification failed")
    return {
        "status": "ALREADY_POOLED_RECONCILED",
        "listing_key": offer["listing_key"],
        "quantity": offer["quantity"],
        "live": live,
    }


async def _apply_offer(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    client: ShopifyAdminClient,
    actor_user_id: UUID,
    offer: Mapping[str, Any],
    language_map: Mapping[str, str],
) -> dict[str, Any]:
    current_offer = await _prepare_offer_for_apply(
        pool,
        settings=settings,
        actor_user_id=actor_user_id,
        planned_offer=offer,
        language_map=language_map,
    )
    target = current_offer["target"]
    if _already_pooled(current_offer):
        return await _reconcile_existing_pool(
            client,
            settings=settings,
            offer=current_offer,
        )

    was_live = any(
        member["sync_state"] == "PUBLISHED" for member in current_offer["members"]
    )
    desired_sync_state = "PUBLISHED" if was_live else "DRAFT"

    product_ids = sorted(
        {
            str(member["current_product_gid"])
            for member in current_offer["members"]
            if str(member.get("current_product_gid") or "")
        }
    )
    for product_id in product_ids:
        await client.set_product_status(product_id=product_id, status="DRAFT")

    inventory_targets = sorted(
        {
            (
                str(member["current_inventory_item_gid"]),
                str(member["current_location_gid"]),
            )
            for member in current_offer["members"]
            if str(member.get("current_inventory_item_gid") or "")
            and str(member.get("current_location_gid") or "")
        }
    )
    for inventory_item_id, location_id in inventory_targets:
        await client.set_inventory_quantity(
            inventory_item_id=inventory_item_id,
            location_id=location_id,
            quantity=0,
            idempotency_key=(
                f"pool-freeze-{current_offer['listing_fingerprint'][:16]}-"
                f"{inventory_item_id.rsplit('/', 1)[-1]}"
            ),
        )

    await client.update_pooled_offer_variant(
        product_id=str(target["shopify_product_gid"]),
        variant_id=str(target["shopify_variant_gid"]),
        price=_money(int(current_offer["store_price_minor"])),
        sku=str(current_offer["sku"]),
    )
    await client.activate_inventory(
        inventory_item_id=str(target["shopify_inventory_item_gid"]),
        location_id=str(target["shopify_location_gid"]),
        idempotency_key=f"pool-activate-{current_offer['listing_fingerprint'][:20]}",
    )

    await _repoint_links(
        pool,
        settings=settings,
        actor_user_id=actor_user_id,
        offer=current_offer,
        desired_sync_state=desired_sync_state,
    )

    await client.set_inventory_quantity(
        inventory_item_id=str(target["shopify_inventory_item_gid"]),
        location_id=str(target["shopify_location_gid"]),
        quantity=int(current_offer["quantity"]),
        idempotency_key=(
            f"pool-quantity-{current_offer['listing_fingerprint'][:20]}-"
            f"{current_offer['quantity']}"
        ),
    )
    await _verify_anchor_draft(client, offer=current_offer)

    if was_live:
        await client.set_product_status(
            product_id=str(target["shopify_product_gid"]),
            status="ACTIVE",
        )
        await client.publish_product(
            product_id=str(target["shopify_product_gid"]),
            publication_id=str(settings.shopify_publication_gid),
        )
        published = await client.product_published_on_publication(
            product_id=str(target["shopify_product_gid"]),
            publication_id=str(settings.shopify_publication_gid),
        )
        if not published:
            raise RuntimeError("Pooled offer publication verification failed")

    return {
        "status": "CONVERTED",
        "listing_key": current_offer["listing_key"],
        "quantity": current_offer["quantity"],
        "live": was_live,
        "anchor_product_gid": target["shopify_product_gid"],
        "anchor_variant_gid": target["shopify_variant_gid"],
        "retired_product_gids": current_offer["retire_product_gids"],
    }


async def run_shopify_pooled_offer_conversion(
    pool: asyncpg.Pool,
    settings: Settings,
) -> dict[str, Any]:
    if not settings.shopify_pooled_offer_conversion_enabled:
        return {"status": "DISABLED"}

    if not settings.shopify_catalogue_bootstrap_actor_user_id:
        raise RuntimeError("Pooled offer conversion actor user ID is required")
    if not settings.shopify_shop_domain:
        raise RuntimeError("Pooled offer conversion Shopify domain is required")

    actor_user_id = UUID(settings.shopify_catalogue_bootstrap_actor_user_id)
    language_map = parse_language_map(settings.shopify_pooled_offer_language_map_json)
    candidates = await _candidate_ids(
        pool,
        actor_user_id=actor_user_id,
        shop_domain=str(settings.shopify_shop_domain),
    )
    prepared, preparation_blocked = await _prepare_candidates_read_only(
        pool,
        settings=settings,
        actor_user_id=actor_user_id,
        inventory_ids=candidates,
        language_map=language_map,
    )
    plan = build_shopify_offer_plan(prepared)
    pooled = [
        offer
        for offer in plan["offers"]
        if offer["pooling_mode"] == "POOLED"
        and int(offer["quantity"]) > 1
    ]
    ready = [offer for offer in pooled if offer["ready"]]
    selected = ready[: settings.shopify_pooled_offer_conversion_limit]

    blocker_counts = Counter(row["code"] for row in preparation_blocked)
    for offer in pooled:
        for blocker in offer["blockers"]:
            blocker_counts[str(blocker["code"])] += 1

    summary: dict[str, Any] = {
        "status": "COMPLETE",
        "mode": (
            "APPLY" if settings.shopify_pooled_offer_conversion_apply else "DRY_RUN"
        ),
        "candidate_units": len(candidates),
        "prepared_units": len(prepared),
        "preparation_blocked_units": len(preparation_blocked),
        "pooled_offer_count": len(pooled),
        "ready_pooled_offer_count": len(ready),
        "selected_pooled_offer_count": len(selected),
        "duplicate_products_to_retire": sum(
            len(offer["retire_product_gids"]) for offer in selected
        ),
        "blockers": dict(sorted(blocker_counts.items())),
        "preparation_blocked": preparation_blocked,
        "selected_offers": selected,
    }

    if not settings.shopify_pooled_offer_conversion_apply:
        logger.warning(
            "Shopify pooled offer conversion result: %s",
            json.dumps(summary, default=str),
        )
        return summary

    if not all(
        (
            settings.shopify_client_id,
            settings.shopify_client_secret,
            settings.shopify_location_gid,
            settings.shopify_publication_gid,
        )
    ):
        raise RuntimeError("Pooled offer conversion Shopify APPLY configuration is incomplete")

    client = ShopifyAdminClient(
        shop_domain=str(settings.shopify_shop_domain),
        client_id=str(settings.shopify_client_id),
        client_secret=str(settings.shopify_client_secret),
        api_version=settings.shopify_api_version,
    )

    results: list[dict[str, Any]] = []
    for offer in selected:
        try:
            result = await _apply_offer(
                pool,
                settings=settings,
                client=client,
                actor_user_id=actor_user_id,
                offer=offer,
                language_map=language_map,
            )
        except (ReconciliationBlocked, ShopifyApiError, RuntimeError, ValueError) as exc:
            logger.exception(
                "Shopify pooled offer conversion failed for %s",
                offer["listing_key"],
            )
            results.append(
                {
                    "status": "ERROR",
                    "listing_key": offer["listing_key"],
                    "error_code": (
                        exc.code if isinstance(exc, ReconciliationBlocked)
                        else type(exc).__name__
                    ),
                    "detail": (
                        exc.detail if isinstance(exc, ReconciliationBlocked)
                        else str(exc)
                    ),
                }
            )
            continue
        results.append(result)

    summary["results"] = results
    summary["result_counts"] = dict(
        sorted(Counter(row["status"] for row in results).items())
    )
    logger.warning(
        "Shopify pooled offer conversion result: %s",
        json.dumps(summary, default=str),
    )
    return summary
