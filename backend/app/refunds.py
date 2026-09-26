from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .access_control import require_platform_admin_request
from .ownership import current_owner as _owner
from .auth import AuthenticatedUser, require_user
from .db import user_connection


router = APIRouter(prefix="/api/v1")


class RefundCreate(BaseModel):
    reference: str = Field(min_length=1, max_length=96)
    amount_minor: int = Field(gt=0)
    return_to_stock: bool = False
    reason: str = Field(default="", max_length=1000)
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def normalise(self) -> "RefundCreate":
        self.reference = self.reference.strip()
        self.reason = self.reason.strip()
        if not self.reference:
            raise ValueError("reference cannot be blank")
        return self



@router.get("/finance/refunds")
async def list_refunds(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select
                r.id, r.order_id, r.order_item_id, r.inventory_id,
                r.source_reference, r.amount_minor, r.currency,
                r.return_to_stock, r.reason, r.occurred_at, r.created_at,
                i.inventory_code, p.game, p.name, p.set_name, p.card_number,
                o.order_number, o.source_reference as order_reference
            from tcg.refund_events r
            join tcg.inventory_items i on i.id = r.inventory_id
            join tcg.catalogue_products p on p.id = i.catalogue_id
            join tcg.orders o on o.id = r.order_id
            where r.owner_id = $1
            order by r.occurred_at desc, r.id
            """,
            owner["id"],
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/finance/order-items/{order_item_id}/refunds", status_code=201, dependencies=[Depends(require_platform_admin_request)])
async def create_refund(
    order_item_id: UUID,
    payload: RefundCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)

        item = await connection.fetchrow(
            """
            select
                oi.id, oi.order_id, oi.inventory_id, oi.owner_id,
                oi.net_sale_minor, oi.cost_basis_minor,
                o.status as order_status,
                i.status as inventory_status, i.inventory_code, i.version
            from tcg.order_items oi
            join tcg.orders o on o.id = oi.order_id
            join tcg.inventory_items i on i.id = oi.inventory_id
            where oi.id = $1 and oi.owner_id = $2
            for update of oi, o, i
            """,
            order_item_id, owner["id"],
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Order item not found")
        if item["order_status"] == "CANCELLED":
            raise HTTPException(status_code=422, detail="Cancelled orders cannot be refunded")

        duplicate = await connection.fetchrow(
            """
            select id
            from tcg.refund_events
            where order_item_id = $1 and source_reference = $2
            """,
            order_item_id, payload.reference,
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="This refund reference has already been recorded")

        shipping_revenue = await connection.fetchval(
            """
            select coalesce(sum(amount_minor), 0)::bigint
            from tcg.financial_ledger_entries
            where order_item_id = $1 and entry_type = 'SHIPPING_REVENUE'
            """,
            order_item_id,
        )
        prior_refunds = await connection.fetchval(
            """
            select coalesce(sum(amount_minor), 0)::bigint
            from tcg.refund_events
            where order_item_id = $1
            """,
            order_item_id,
        )
        prior_return = await connection.fetchval(
            """
            select exists(
                select 1 from tcg.refund_events
                where order_item_id = $1 and return_to_stock
            )
            """,
            order_item_id,
        )

        refundable_total = int(item["net_sale_minor"]) + int(shipping_revenue or 0)
        remaining = refundable_total - int(prior_refunds or 0)
        if payload.amount_minor > remaining:
            raise HTTPException(status_code=422, detail={
                "message": "Refund exceeds the remaining refundable amount",
                "remaining_refundable_minor": max(remaining, 0),
            })

        cumulative_refund = int(prior_refunds or 0) + payload.amount_minor
        if payload.return_to_stock:
            if prior_return:
                raise HTTPException(status_code=409, detail="This item has already been returned to stock")
            if item["inventory_status"] != "SOLD":
                raise HTTPException(status_code=409, detail="Only SOLD inventory can be returned")
            if cumulative_refund < int(item["net_sale_minor"]):
                raise HTTPException(
                    status_code=422,
                    detail="Returning stock requires the item sale value to be fully refunded",
                )

        funds_status = await connection.fetchval(
            """
            select funds_status
            from tcg.financial_ledger_entries
            where order_item_id = $1 and entry_type = 'SALE_REVENUE'
            order by created_at
            limit 1
            """,
            order_item_id,
        ) or "AVAILABLE"

        refund_id = uuid4()
        refund = await connection.fetchrow(
            """
            insert into tcg.refund_events(
                id, owner_id, order_id, order_item_id, inventory_id,
                source_reference, amount_minor, currency, return_to_stock,
                reason, occurred_at
            ) values ($1, $2, $3, $4, $5, $6, $7, 'GBP', $8, $9, $10)
            returning *
            """,
            refund_id,
            owner["id"],
            item["order_id"],
            order_item_id,
            item["inventory_id"],
            payload.reference,
            payload.amount_minor,
            payload.return_to_stock,
            payload.reason,
            occurred_at,
        )

        await connection.execute(
            """
            insert into tcg.financial_ledger_entries(
                owner_id, order_id, order_item_id, entry_type,
                amount_minor, currency, funds_status, source_key,
                occurred_at, available_at, notes
            ) values ($1, $2, $3, 'REFUND', $4, 'GBP', $5, $6, $7,
                case when $5 = 'AVAILABLE' then $7 else null end, $8)
            """,
            owner["id"],
            item["order_id"],
            order_item_id,
            -payload.amount_minor,
            funds_status,
            f"refund:{order_item_id}:{payload.reference}",
            occurred_at,
            payload.reason,
        )

        inventory = None
        if payload.return_to_stock:
            await connection.execute("select set_config('tcg.allow_sold_return', 'on', true)")
            inventory = await connection.fetchrow(
                """
                update tcg.inventory_items
                set status = 'INSPECTION', version = version + 1, updated_at = now()
                where id = $1 and owner_id = $2 and status = 'SOLD'
                returning id, inventory_code, status, version
                """,
                item["inventory_id"], owner["id"],
            )
            if inventory is None:
                raise HTTPException(status_code=409, detail="Inventory changed while recording the return")

            # A returned physical item must remain unavailable on every channel
            # until it passes inspection again. Historical order/listing links
            # remain intact; only the current channel state is made non-sellable.
            await connection.execute(
                """
                update tcg.shopify_inventory_links
                set sync_state='ARCHIVED',
                    reserved_order_reference=null,
                    reserved_line_reference=null,
                    reserved_at=null,
                    version=version+1,
                    last_synced_at=clock_timestamp()
                where inventory_id=$1 and owner_id=$2
                  and sync_state in ('DRAFT','PUBLISHED','SOLD','ERROR')
                """,
                item["inventory_id"], owner["id"],
            )
            await connection.execute(
                """
                update tcg.ebay_inventory_links
                set state='WITHDRAWN',
                    withdrawal_reason='RETURN_TO_INSPECTION',
                    withdrawn_at=coalesce(withdrawn_at,clock_timestamp()),
                    last_error_code=null,
                    version=version+1,
                    updated_at=clock_timestamp()
                where inventory_id=$1 and owner_id=$2
                  and state in ('LIVE','SOLD','WITHDRAWN','ERROR')
                """,
                item["inventory_id"], owner["id"],
            )

        order_refundable = await connection.fetchval(
            """
            select
                coalesce(sum(oi.net_sale_minor), 0)
                + coalesce((
                    select sum(le.amount_minor)
                    from tcg.financial_ledger_entries le
                    where le.order_id = $1 and le.entry_type = 'SHIPPING_REVENUE'
                ), 0)
            from tcg.order_items oi
            where oi.order_id = $1
            """,
            item["order_id"],
        )
        order_refunded = await connection.fetchval(
            """
            select coalesce(-sum(amount_minor), 0)::bigint
            from tcg.financial_ledger_entries
            where order_id = $1 and entry_type = 'REFUND'
            """,
            item["order_id"],
        )
        next_status = "REFUNDED" if int(order_refunded or 0) >= int(order_refundable or 0) else "PARTIALLY_REFUNDED"
        order = await connection.fetchrow(
            """
            update tcg.orders
            set status = $2, updated_at = now()
            where id = $1
            returning id, source, source_reference, order_number, status, placed_at, updated_at
            """,
            item["order_id"], next_status,
        )

        return jsonable_encoder({
            "refund": dict(refund),
            "order": dict(order),
            "inventory": dict(inventory) if inventory is not None else None,
            "remaining_refundable_minor": max(remaining - payload.amount_minor, 0),
        })
