from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ebay_sales import EbaySellApiError, withdraw_ebay_for_inventory
from .ownership import current_owner as _owner
from .schemas import InventorySaleIntentChange
from .shopify_pipeline import withdraw_shopify_for_inventory


router = APIRouter(prefix="/api/v1", tags=["inventory"])


async def _pause_marketplace_memberships(
    connection: Any,
    *,
    inventory_id: UUID,
    owner_id: UUID,
    actor_user_id: UUID,
) -> list[dict[str, Any]]:
    memberships = await connection.fetch(
        """
        select *
        from tcg.listing_inventory_members
        where inventory_id=$1 and owner_id=$2 and state='ACTIVE'
        for update
        """,
        inventory_id,
        owner_id,
    )
    paused: list[dict[str, Any]] = []
    for membership in memberships:
        updated = await connection.fetchrow(
            """
            update tcg.listing_inventory_members
            set state='PAUSED',
                version=version+1,
                updated_at=clock_timestamp()
            where id=$1 and owner_id=$2 and state='ACTIVE'
            returning *
            """,
            membership["id"],
            owner_id,
        )
        if updated is None:
            continue
        await connection.execute(
            """
            insert into tcg.marketplace_audit_events(
              owner_id,actor_user_id,action,entity_type,entity_id,
              old_values,new_values,notes
            ) values(
              $1,$2,'MEMBERSHIP_PAUSED_PERSONAL_COLLECTION','MEMBERSHIP',$3,
              $4::jsonb,$5::jsonb,
              'Inventory moved to PERSONAL_COLLECTION; relisting is explicit.'
            )
            """,
            owner_id,
            actor_user_id,
            updated["id"],
            json.dumps(jsonable_encoder(dict(membership))),
            json.dumps(jsonable_encoder(dict(updated))),
        )
        paused.append(dict(updated))
    return paused


@router.post("/inventory/{inventory_id}/sale-intent")
async def change_inventory_sale_intent(
    inventory_id: UUID,
    payload: InventorySaleIntentChange,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Move exact physical inventory between sale stock and a personal collection.

    PERSONAL_COLLECTION is locally authoritative immediately. Channel withdrawal
    happens afterwards so no external network call is made while a database lock
    is held. Every sale-allocation path independently checks sale_intent.
    """

    owner_id: UUID
    inventory: dict[str, Any]
    changed = False
    paused_memberships: list[dict[str, Any]] = []
    had_live_ebay = False

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        owner_id = owner["id"]

        async with connection.transaction():
            item = await connection.fetchrow(
                """
                select id,owner_id,inventory_code,status,sale_intent,version
                from tcg.inventory_items
                where id=$1 and owner_id=$2
                for update
                """,
                inventory_id,
                owner_id,
            )
            if item is None:
                raise HTTPException(status_code=404, detail="Inventory item not found")
            if item["status"] == "SOLD":
                raise HTTPException(
                    status_code=409,
                    detail="Sold inventory cannot move to or from Personal Collection",
                )
            if item["status"] == "RESERVED":
                raise HTTPException(
                    status_code=409,
                    detail="Reserved inventory must be released before changing sale intent",
                )

            if item["sale_intent"] != payload.sale_intent:
                if int(item["version"]) != payload.version:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "Inventory item changed",
                            "current_version": item["version"],
                        },
                    )
                updated = await connection.fetchrow(
                    """
                    update tcg.inventory_items
                    set sale_intent=$3,
                        version=version+1,
                        updated_at=clock_timestamp()
                    where id=$1 and owner_id=$2 and version=$4
                    returning id,owner_id,inventory_code,status,sale_intent,version
                    """,
                    inventory_id,
                    owner_id,
                    payload.sale_intent,
                    payload.version,
                )
                if updated is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Inventory changed while sale intent was being updated",
                    )
                item = updated
                changed = True

            if payload.sale_intent == "PERSONAL_COLLECTION":
                paused_memberships = await _pause_marketplace_memberships(
                    connection,
                    inventory_id=inventory_id,
                    owner_id=owner_id,
                    actor_user_id=user.user_id,
                )
                had_live_ebay = bool(
                    await connection.fetchval(
                        """
                        select exists(
                          select 1
                          from tcg.ebay_inventory_links
                          where inventory_id=$1 and owner_id=$2 and state='LIVE'
                        )
                        """,
                        inventory_id,
                        owner_id,
                    )
                )

            inventory = dict(item)

    if payload.sale_intent == "FOR_SALE":
        return jsonable_encoder(
            {
                "inventory": inventory,
                "changed": changed,
                "idempotent": not changed,
                "requires_listing": True,
                "message": (
                    "Inventory is eligible to be listed again. "
                    "No marketplace listing was reactivated automatically."
                ),
            }
        )

    withdrawal_errors: list[dict[str, object]] = []
    ebay_status = "NOT_LIVE"
    try:
        await withdraw_ebay_for_inventory(
            request.app.state.db_pool,
            [str(inventory_id)],
            reason="PERSONAL_COLLECTION",
        )
        if had_live_ebay:
            ebay_status = "WITHDRAWN"
    except EbaySellApiError:
        ebay_status = "ERROR"
        withdrawal_errors.append(
            {
                "channel": "EBAY",
                "retryable": True,
                "message": "eBay withdrawal failed; retry required",
            }
        )

    shopify_results = await withdraw_shopify_for_inventory(
        request.app.state.db_pool,
        [str(inventory_id)],
        owner_id=owner_id,
        reason="PERSONAL_COLLECTION",
    )
    for result in shopify_results:
        if result.get("status") in {"ERROR", "STALE"}:
            withdrawal_errors.append(
                {
                    "channel": "SHOPIFY",
                    "retryable": bool(result.get("retryable", True)),
                    "message": "Shopify withdrawal failed or changed; retry required",
                }
            )

    response = {
        "inventory": inventory,
        "changed": changed,
        "idempotent": not changed,
        "requires_listing": False,
        "paused_marketplace_memberships": len(paused_memberships),
        "channels": {
            "ebay": ebay_status,
            "shopify": shopify_results,
        },
        "action_required": bool(withdrawal_errors),
    }
    if withdrawal_errors:
        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Inventory is protected as PERSONAL_COLLECTION, but one or "
                    "more channel withdrawals need to be retried."
                ),
                "sale_intent": "PERSONAL_COLLECTION",
                "current_version": inventory["version"],
                "withdrawal_errors": withdrawal_errors,
            },
        )
    return jsonable_encoder(response)
