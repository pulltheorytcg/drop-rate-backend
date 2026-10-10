"""Owner-isolated, read-only Shopify dispatch queue for Seller Hub and founders.

No customer address, label, Shopify fulfillment mutation or financial write is
available on this surface. A storage location or inventory owner does not prove
physical custody. The queue deliberately fails closed until shipper verification,
postage provider setup, and exact Shopify fulfillment-order preflight are built.
"""
from __future__ import annotations

from typing import Annotated, Any, Mapping

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from .access_control import current_access_context
from .auth import AuthenticatedUser, require_user
from .db import user_connection


router = APIRouter(prefix="/api/v1/fulfilment", tags=["seller-fulfilment"])

# Deliberately not flags supplied by the client. Activating fulfillment requires
# a separate reviewed migration + provider readback, not a UI-only toggle.
CAPABILITIES = {
    "shopify_order_allocation": True,
    "carrier_label_purchase": False,
    "dispatch_confirmation": False,
    "shopify_tracking_sync": False,
    "buyer_address_access": False,
}


def evaluate_dispatch_review(row: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one exact physical order-item allocation, without guessing.

    A PAID order in our database is not proof that Shopify still has an open
    fulfillment order; checkout refund/cancel and custody can change later.
    """
    blockers: list[str] = []
    if str(row.get("order_status") or "").upper() != "PAID":
        blockers.append("ORDER_REFUND_REVIEW_REQUIRED")
    if str(row.get("physical_status") or "").upper() != "SOLD":
        blockers.append("PHYSICAL_INVENTORY_STATE_MISMATCH")
    if (
        not row.get("shopify_line_item_id")
        or not row.get("shopify_variant_gid")
        or str(row.get("shopify_order_id") or "") != str(row.get("source_reference") or "")
    ):
        blockers.append("SHOPIFY_ALLOCATION_INCOMPLETE")

    # Nothing in the current storage_locations table establishes the actual
    # shipping custodian or validated return address. Even a non-NULL location
    # must NOT grant access to protected buyer delivery addresses.
    blockers.append("PHYSICAL_SHIPPER_UNVERIFIED")
    blockers.append("CARRIER_AND_SHOPIFY_FULFILMENT_NOT_CONNECTED")
    return {
        "state": "REVIEW_REQUIRED" if len(blockers) > 2 else "AWAITING_DISPATCH_SETUP",
        "blockers": blockers,
        "can_buy_label": False,
        "can_confirm_dispatched": False,
    }


@router.get("/to-ship")
async def owner_to_ship(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Owner-specific potentially dispatchable order lines; never buyer PII."""
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id,
    ) as connection:
        access = await current_access_context(connection)
        # Restricted owners and founders see their OWN physical inventory only.
        # Platform-admin access never implies arbitrary seller shipping custody.
        owner_id = access["owner_id"]
        total = await connection.fetchval(
            """
            select count(*)::int
            from tcg.order_items oi
            join tcg.orders o on o.id=oi.order_id
            join tcg.inventory_items i
              on i.id=oi.inventory_id and i.owner_id=$1
            where oi.owner_id=$1
              and o.source='SHOPIFY'
              and o.status in ('PAID','PARTIALLY_REFUNDED')
            """,
            owner_id,
        )
        rows = await connection.fetch(
            """
            select
              oi.id as order_item_id,
              o.order_number, o.source_reference, o.status as order_status,
              o.placed_at,
              i.inventory_code, i.status as physical_status,
              p.name as card_name, p.game, p.set_name, p.card_number,
              oi.net_sale_minor,
              sol.shopify_order_id, sol.shopify_line_item_id,
              sol.shopify_variant_gid
            from tcg.order_items oi
            join tcg.orders o on o.id=oi.order_id
            join tcg.inventory_items i
              on i.id=oi.inventory_id and i.owner_id=$1
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join tcg.shopify_order_item_links sol
              on sol.order_item_id=oi.id and sol.owner_id=$1
            where oi.owner_id=$1
              and o.source='SHOPIFY'
              and o.status in ('PAID','PARTIALLY_REFUNDED')
            order by o.placed_at desc,oi.id
            limit $2 offset $3
            """,
            owner_id, limit, offset,
        )

    items: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        review = evaluate_dispatch_review(record)
        items.append({
            "order_item_id": record["order_item_id"],
            "order_number": record["order_number"],
            "placed_at": record["placed_at"],
            "order_status": record["order_status"],
            "inventory_code": record["inventory_code"],
            "card_name": record["card_name"],
            "game": record["game"],
            "set_name": record["set_name"],
            "card_number": record["card_number"],
            "net_sale_minor": record["net_sale_minor"],
            **review,
        })
    return jsonable_encoder({
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "items": items,
        "capabilities": CAPABILITIES.copy(),
        "note": "Dispatch remains on hold until shipper, genuine label and Shopify fulfillment checks are verified.",
    })
