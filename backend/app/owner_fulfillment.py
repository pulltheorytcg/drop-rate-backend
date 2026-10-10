"""Owner-isolated, read-only Shopify dispatch queue for Seller Hub and founders.

No customer address, label, Shopify fulfillment mutation or financial write is
available on this surface. A storage location or inventory owner does not prove
physical custody. The queue deliberately fails closed until shipper verification,
postage provider setup, and exact Shopify fulfillment-order preflight are built.
"""
from __future__ import annotations

from typing import Annotated, Any, Mapping
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from .access_control import current_access_context
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .settings import get_settings
from .shopify_client import ShopifyAdminClient, ShopifyApiError
from .shopify_packing_slip import PackingSlipNotReady, build_shopify_owner_packing_slip
from .shopify_shipping_labels import (
    ORDER_SHIPPING_QUERY, canonical_shopify_order_gid,
    canonical_shopify_line_gid, ensure_label_api_version,
    evaluate_remote_shipping,
)



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


def _shipping_admin_client() -> ShopifyAdminClient:
    settings = get_settings()
    if not all((
        settings.shopify_shop_domain, settings.shopify_client_id,
        settings.shopify_client_secret, settings.shopify_api_version,
    )):
        raise HTTPException(status_code=503, detail="Shopify connection is not configured")
    try:
        ensure_label_api_version(settings.shopify_api_version)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Shopify shipping API version is outdated") from exc
    return ShopifyAdminClient(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        api_version=settings.shopify_api_version,
    )


@router.get("/shopify-status")
async def owner_shopify_shipping_status(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Prove backend's DIRECT Shopify app scopes, not the ChatGPT connector.

    No admin credentials, customer data or ability to purchase labels is exposed.
    """
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id,
    ) as connection:
        await current_access_context(connection)
    client = _shipping_admin_client()
    try:
        shop = await client.probe_shop()
        scopes = await client.access_scopes()
    except ShopifyApiError as exc:
        raise HTTPException(
            status_code=503 if exc.retryable else 502,
            detail="Shopify Shipping connection could not be verified",
        ) from exc
    can_read = {"read_orders", "read_merchant_managed_fulfillment_orders"} <= scopes
    can_write = {"write_orders", "write_merchant_managed_fulfillment_orders"} <= scopes
    return jsonable_encoder({
        "store_connected": True,
        "shop": str(shop.get("name") or "Drop Rate"),
        "shop_domain": client.shop_domain,
        "api_version": client.api_version,
        "shopify_fulfilment_read_access": can_read,
        "shopify_label_write_scopes_present": can_write,
        "shopify_label_purchase_operation": "ADAPTER_BUILT_PURCHASE_DISABLED",
        "carrier_label_purchase": False,
        "dispatch_confirmation": False,
        "postage_cost_verified": False,
        "reason": (
            "No owner-scoped carrier purchase journal, verified custody, "
            "confirmed postage quote or approved live order pilot."
        ),
    })


@router.get("/to-ship/{order_item_id}/shopify")
async def owner_shopify_preflight(
    order_item_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Read live Shopify FulfillmentOrder for one provably owned physical copy."""
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id,
    ) as connection:
        access = await current_access_context(connection)
        owner_id = access["owner_id"]
        record = await connection.fetchrow(
            """
            select
              o.id as local_order_id, o.source_reference, o.status as order_status,
              i.status as physical_status,
              sol.shopify_order_id, sol.shopify_line_item_id,
              sol.shopify_variant_gid
            from tcg.order_items oi
            join tcg.orders o on o.id=oi.order_id
            join tcg.inventory_items i
              on i.id=oi.inventory_id and i.owner_id=$1
            left join tcg.shopify_order_item_links sol
              on sol.order_item_id=oi.id and sol.owner_id=$1
            where oi.id=$2 and oi.owner_id=$1 and o.source='SHOPIFY'
            """,
            owner_id, order_item_id,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Shopify order allocation not found")
        candidate = dict(record)
        if candidate["order_status"] not in {"PAID", "PARTIALLY_REFUNDED"}:
            raise HTTPException(status_code=409, detail="Order is no longer eligible for dispatch")
        local = await connection.fetch(
            """
            select
              i.status as physical_status,
              sol.shopify_order_id, sol.shopify_line_item_id,
              sol.shopify_variant_gid
            from tcg.order_items oi
            join tcg.inventory_items i
              on i.id=oi.inventory_id and i.owner_id=$1
            left join tcg.shopify_order_item_links sol
              on sol.order_item_id=oi.id and sol.owner_id=$1
            where oi.order_id=$2 and oi.owner_id=$1
            order by oi.id
            """,
            owner_id, candidate["local_order_id"],
        )
    try:
        remote_order_gid = canonical_shopify_order_gid(candidate["source_reference"])
        target_line_gid = canonical_shopify_line_gid(candidate["shopify_line_item_id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Exact Shopify order allocation missing") from exc

    client = _shipping_admin_client()
    if (not candidate.get("shopify_order_id") or
            str(candidate["shopify_order_id"]) != str(candidate["source_reference"])):
        raise HTTPException(status_code=409, detail="Shopify order reference mismatch")
    try:
        result = await client.graphql(
            query=ORDER_SHIPPING_QUERY,
            variables={"orderId": remote_order_gid},
        )
    except ShopifyApiError as exc:
        raise HTTPException(
            status_code=503 if exc.retryable else 502,
            detail="Could not verify live Shopify fulfillment. Dispatch remains locked.",
        ) from exc
    remote = evaluate_remote_shipping(
        order=result.get("order"),
        local_allocations=[dict(x) for x in local],
        target_line_gid=target_line_gid,
    )
    if candidate["order_status"] != "PAID":
        remote["blockers"].insert(0, "LOCAL_PARTIAL_REFUND_REVIEW_REQUIRED")
        remote["state"] = "REVIEW_REQUIRED"
    if candidate["physical_status"] != "SOLD":
        if "PHYSICAL_INVENTORY_STATE_MISMATCH" not in remote["blockers"]:
            remote["blockers"].insert(0, "PHYSICAL_INVENTORY_STATE_MISMATCH")
        remote["state"] = "REVIEW_REQUIRED"
    return jsonable_encoder({
        "order_item_id": order_item_id,
        "order_status": candidate["order_status"],
        **remote,
        "source": "DIRECT_SHOPIFY_ADMIN_API",
    })


@router.get("/to-ship/{order_item_id}/packing-slip")
async def owner_shopify_packing_slip(
    order_item_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Authenticated seller's exact Shopify-derived packing slip, no buyer PII.

    The actual Shopify Admin packing-slip PDF template is not available through
    the official API. The browser renders this Shopify-sourced, owner-only
    pick/packing slip with no customer shipping address. The official carrier
    label must be bought separately and contains the destination address.
    """
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id,
    ) as connection:
        access = await current_access_context(connection)
        owner_id = access["owner_id"]
        selected = await connection.fetchrow(
            """
            select o.id as local_order_id, o.source_reference,
                   o.status as order_status
            from tcg.order_items oi
            join tcg.orders o on o.id=oi.order_id
            join tcg.inventory_items i on i.id=oi.inventory_id and i.owner_id=$1
            join tcg.shopify_order_item_links sol
              on sol.order_item_id=oi.id and sol.owner_id=$1
            where oi.id=$2 and oi.owner_id=$1 and o.source='SHOPIFY'
            """,
            owner_id, order_item_id,
        )
        if selected is None:
            raise HTTPException(status_code=404, detail="Your Shopify order item was not found")
        if selected["order_status"] != "PAID":
            raise HTTPException(status_code=409, detail="Order is no longer paid")
        rows = await connection.fetch(
            """
            select oi.id as order_item_id, o.status as order_status,
                   i.status as physical_status, i.inventory_code,
                   sol.shopify_order_id, sol.shopify_line_item_id
            from tcg.order_items oi
            join tcg.orders o on o.id=oi.order_id
            join tcg.inventory_items i on i.id=oi.inventory_id and i.owner_id=$1
            join tcg.shopify_order_item_links sol
              on sol.order_item_id=oi.id and sol.owner_id=$1
            where oi.owner_id=$1 and oi.order_id=$2
              and o.source='SHOPIFY'
            order by oi.id
            """,
            owner_id, selected["local_order_id"],
        )
    try:
        source_gid = canonical_shopify_order_gid(selected["source_reference"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Shopify order identity is missing") from exc

    client = _shipping_admin_client()
    try:
        remote = await client.graphql(
            query=ORDER_SHIPPING_QUERY, variables={"orderId": source_gid},
        )
    except ShopifyApiError as exc:
        raise HTTPException(
            status_code=503 if exc.retryable else 502,
            detail="Shopify packing slip could not be verified",
        ) from exc
    try:
        prepared = build_shopify_owner_packing_slip(
            remote_order=remote.get("order"),
            source_reference=str(selected["source_reference"]),
            owner_allocations=[dict(row) for row in rows],
        )
    except PackingSlipNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return jsonable_encoder(prepared)
