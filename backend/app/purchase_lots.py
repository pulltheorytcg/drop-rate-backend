from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from .ownership import current_owner as _owner
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .schemas import PurchaseLotCreate, PurchaseLotDetach, PurchaseLotPatch


router = APIRouter(prefix="/api/v1")



async def _lot_summary(
    connection: asyncpg.Connection,
    lot_id: UUID,
    owner_id: UUID,
) -> asyncpg.Record | None:
    return await connection.fetchrow(
        """
        select
            pl.id, pl.owner_id, pl.lot_code, pl.description, pl.source,
            pl.purchase_date, pl.purchase_price_minor, pl.fees_minor,
            pl.shipping_minor, pl.total_cost_minor, pl.currency,
            pl.allocation_method, pl.notes, pl.version,
            pl.created_at, pl.updated_at,
            count(i.id)::int as item_count,
            coalesce(sum(i.acquisition_cost_minor), 0)::bigint as allocated_cost_minor,
            (pl.total_cost_minor - coalesce(sum(i.acquisition_cost_minor), 0))::bigint
                as remaining_cost_minor
        from tcg.purchase_lots pl
        left join tcg.inventory_items i on i.purchase_lot_id = pl.id
        where pl.id = $1 and pl.owner_id = $2
        group by pl.id
        """,
        lot_id,
        owner_id,
    )


async def _lot_items(
    connection: asyncpg.Connection,
    lot_id: UUID,
    owner_id: UUID,
) -> list[asyncpg.Record]:
    return await connection.fetch(
        """
        select
            i.id, i.inventory_code, i.acquisition_cost_minor, i.acquisition_date,
            i.currency, i.condition, i.seal_status, i.grading_company, i.grade,
            i.language, i.location, i.store_price_minor, i.identity_confirmed,
            i.status, i.version,
            p.product_type, p.game, p.name, p.set_name, p.card_number,
            p.variant, p.rarity
        from tcg.inventory_items i
        join tcg.catalogue_products p on p.id = i.catalogue_id
        where i.purchase_lot_id = $1 and i.owner_id = $2
        order by i.inventory_code
        """,
        lot_id,
        owner_id,
    )


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


@router.get("/purchase-lots/{lot_id}")
async def get_purchase_lot(
    lot_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        lot = await _lot_summary(connection, lot_id, owner["id"])
        if lot is None:
            raise HTTPException(status_code=404, detail="Purchase lot not found")
        items = await _lot_items(connection, lot_id, owner["id"])
        return jsonable_encoder({"lot": dict(lot), "items": [dict(row) for row in items]})


@router.patch("/purchase-lots/{lot_id}")
async def update_purchase_lot(
    lot_id: UUID,
    payload: PurchaseLotPatch,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    values = payload.model_dump(exclude_unset=True)
    expected_version = values.pop("version")

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        lot = await connection.fetchrow(
            """
            select * from tcg.purchase_lots
            where id = $1 and owner_id = $2
            for update
            """,
            lot_id,
            owner["id"],
        )
        if lot is None:
            raise HTTPException(status_code=404, detail="Purchase lot not found")
        if lot["version"] != expected_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Purchase lot changed",
                    "current_version": lot["version"],
                },
            )

        allocated_cost = await connection.fetchval(
            """
            select coalesce(sum(acquisition_cost_minor), 0)
            from tcg.inventory_items
            where purchase_lot_id = $1 and owner_id = $2
            """,
            lot_id,
            owner["id"],
        )
        new_purchase_price = values.get("purchase_price_minor", lot["purchase_price_minor"])
        new_fees = values.get("fees_minor", lot["fees_minor"])
        new_shipping = values.get("shipping_minor", lot["shipping_minor"])
        new_total = new_purchase_price + new_fees + new_shipping
        if new_total < allocated_cost:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Purchase lot total cannot be lower than already allocated cost",
                    "allocated_cost_minor": allocated_cost,
                    "proposed_total_cost_minor": new_total,
                },
            )

        item_count = await connection.fetchval(
            "select count(*) from tcg.inventory_items where purchase_lot_id = $1 and owner_id = $2",
            lot_id,
            owner["id"],
        )
        if "currency" in values and values["currency"] != lot["currency"] and item_count:
            raise HTTPException(
                status_code=422,
                detail="Currency cannot be changed after inventory has been allocated to the lot",
            )

        assignments: list[str] = []
        params: list[object] = [lot_id, owner["id"], expected_version]
        for column, value in values.items():
            params.append(value)
            assignments.append(f"{column} = ${len(params)}")
        assignments.extend(["version = version + 1", "updated_at = now()"])

        updated_lot = await connection.fetchrow(
            f"""
            update tcg.purchase_lots
            set {', '.join(assignments)}
            where id = $1 and owner_id = $2 and version = $3
            returning *
            """,
            *params,
        )
        if updated_lot is None:
            raise HTTPException(status_code=409, detail="Purchase lot changed during update")

        if "purchase_date" in values:
            await connection.execute(
                """
                update tcg.inventory_items
                set acquisition_date = $1,
                    version = version + 1,
                    updated_at = now()
                where purchase_lot_id = $2 and owner_id = $3
                """,
                values["purchase_date"],
                lot_id,
                owner["id"],
            )

        summary = await _lot_summary(connection, lot_id, owner["id"])
        items = await _lot_items(connection, lot_id, owner["id"])
        return jsonable_encoder({"lot": dict(summary), "items": [dict(row) for row in items]})


@router.post("/purchase-lots/{lot_id}/items/{inventory_id}/detach")
async def detach_purchase_lot_item(
    lot_id: UUID,
    inventory_id: UUID,
    payload: PurchaseLotDetach,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        lot = await connection.fetchrow(
            """
            select * from tcg.purchase_lots
            where id = $1 and owner_id = $2
            for update
            """,
            lot_id,
            owner["id"],
        )
        if lot is None:
            raise HTTPException(status_code=404, detail="Purchase lot not found")
        if lot["version"] != payload.version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Purchase lot changed",
                    "current_version": lot["version"],
                },
            )

        item = await connection.fetchrow(
            """
            select id, version, status, purchase_lot_id
            from tcg.inventory_items
            where id = $1 and owner_id = $2
            for update
            """,
            inventory_id,
            owner["id"],
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        if item["purchase_lot_id"] != lot_id:
            raise HTTPException(status_code=409, detail="Inventory item does not belong to this purchase lot")
        if item["version"] != payload.inventory_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Inventory item changed",
                    "current_version": item["version"],
                },
            )
        if item["status"] not in {"DRAFT", "INSPECTION", "APPROVED", "WITHDRAWN"}:
            raise HTTPException(
                status_code=409,
                detail="Historical or sold inventory cannot be detached from its acquisition lot",
            )

        updated_item = await connection.fetchrow(
            """
            update tcg.inventory_items
            set purchase_lot_id = null,
                acquisition_cost_minor = null,
                acquisition_date = null,
                status = case when status = 'APPROVED' then 'DRAFT' else status end,
                version = version + 1,
                updated_at = now()
            where id = $1 and owner_id = $2 and version = $3
            returning id, inventory_code, acquisition_cost_minor, acquisition_date,
                purchase_lot_id, status, version
            """,
            inventory_id,
            owner["id"],
            payload.inventory_version,
        )
        if updated_item is None:
            raise HTTPException(status_code=409, detail="Inventory item changed during detach")

        await connection.execute(
            """
            update tcg.purchase_lots
            set version = version + 1, updated_at = now()
            where id = $1 and owner_id = $2 and version = $3
            """,
            lot_id,
            owner["id"],
            payload.version,
        )

        summary = await _lot_summary(connection, lot_id, owner["id"])
        return jsonable_encoder({"lot": dict(summary), "item": dict(updated_item)})
