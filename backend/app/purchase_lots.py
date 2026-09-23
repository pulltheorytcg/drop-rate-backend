from __future__ import annotations

from typing import Annotated
from uuid import uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .schemas import PurchaseLotCreate


router = APIRouter(prefix="/api/v1")


async def _owner(connection: asyncpg.Connection) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        select id, display_name, owner_type, founder_slot
        from tcg.owners
        where active
        order by founder_slot nulls last
        limit 1
        """
    )
    if row is None:
        raise HTTPException(status_code=403, detail="No active owner membership")
    return row


@router.post("/purchase-lots/create-with-allocation", status_code=201)
async def create_purchase_lot_with_allocation(
    payload: PurchaseLotCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    """Create a purchase lot and its initial inventory allocation atomically."""
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)

        ids = [item.inventory_id for item in payload.items]
        current: dict = {}
        if ids:
            rows = await connection.fetch(
                """
                select id, version, purchase_lot_id
                from tcg.inventory_items
                where owner_id = $1 and id = any($2::uuid[])
                order by id
                for update
                """,
                owner["id"],
                ids,
            )
            if len(rows) != len(ids):
                raise HTTPException(
                    status_code=404,
                    detail="One or more inventory items were not found",
                )
            current = {row["id"]: row for row in rows}
            stale = [
                {
                    "inventory_id": str(item.inventory_id),
                    "current_version": current[item.inventory_id]["version"],
                }
                for item in payload.items
                if current[item.inventory_id]["version"] != item.version
            ]
            if stale:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "One or more inventory items changed",
                        "items": stale,
                    },
                )
            conflicts = [
                str(item.inventory_id)
                for item in payload.items
                if current[item.inventory_id]["purchase_lot_id"] is not None
            ]
            if conflicts:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "One or more inventory items already belong to a purchase lot",
                        "items": conflicts,
                    },
                )

        lot_id = uuid4()
        year = payload.purchase_date.year if payload.purchase_date else 0
        prefix = str(year) if year else "UNDATED"
        lot_code = f"LOT-{prefix}-{lot_id.hex[:8].upper()}"

        lot = await connection.fetchrow(
            """
            insert into tcg.purchase_lots(
                id, owner_id, lot_code, description, source, purchase_date,
                purchase_price_minor, fees_minor, shipping_minor, currency,
                allocation_method, notes
            ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            returning *
            """,
            lot_id,
            owner["id"],
            lot_code,
            payload.description,
            payload.source,
            payload.purchase_date,
            payload.purchase_price_minor,
            payload.fees_minor,
            payload.shipping_minor,
            payload.currency,
            payload.allocation_method,
            payload.notes,
        )

        updated = []
        for item in payload.items:
            row = await connection.fetchrow(
                """
                update tcg.inventory_items
                set purchase_lot_id = $1,
                    acquisition_cost_minor = $2,
                    acquisition_date = $3,
                    currency = $4,
                    version = version + 1,
                    updated_at = now()
                where id = $5 and owner_id = $6 and version = $7
                returning id, inventory_code, purchase_lot_id,
                    acquisition_cost_minor, acquisition_date, currency, version
                """,
                lot_id,
                item.acquisition_cost_minor,
                payload.purchase_date,
                payload.currency,
                item.inventory_id,
                owner["id"],
                item.version,
            )
            if row is None:
                raise HTTPException(
                    status_code=409,
                    detail="Inventory item changed during allocation",
                )
            updated.append(dict(row))

        allocated_cost = sum(item.acquisition_cost_minor for item in payload.items)
        return jsonable_encoder(
            {
                "lot": dict(lot),
                "allocated_cost_minor": allocated_cost,
                "remaining_cost_minor": lot["total_cost_minor"] - allocated_cost,
                "updated_count": len(updated),
                "items": updated,
            }
        )
