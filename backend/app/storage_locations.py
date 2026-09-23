from __future__ import annotations

from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .schemas import (
    StorageLocationAssignment,
    StorageLocationCreate,
    StorageLocationPatch,
)


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


async def _location_summary(
    connection: asyncpg.Connection,
    location_id: UUID,
    owner_id: UUID,
) -> asyncpg.Record | None:
    return await connection.fetchrow(
        """
        select
            sl.id, sl.code, sl.label, sl.location_type, sl.active, sl.notes,
            sl.version, sl.created_at, sl.updated_at,
            count(i.id)::int as item_count
        from tcg.storage_locations sl
        left join tcg.inventory_items i on i.storage_location_id = sl.id
        where sl.id = $1 and sl.owner_id = $2
        group by sl.id
        """,
        location_id,
        owner_id,
    )


@router.get("/storage-locations")
async def list_storage_locations(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    include_inactive: bool = Query(default=False),
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select
                sl.id, sl.code, sl.label, sl.location_type, sl.active, sl.notes,
                sl.version, sl.created_at, sl.updated_at,
                count(i.id)::int as item_count
            from tcg.storage_locations sl
            left join tcg.inventory_items i on i.storage_location_id = sl.id
            where sl.owner_id = $1 and ($2::boolean or sl.active)
            group by sl.id
            order by sl.active desc, sl.code
            """,
            owner["id"],
            include_inactive,
        )
        unlocated = await connection.fetchval(
            """
            select count(*)::int
            from tcg.inventory_items
            where owner_id = $1 and storage_location_id is null
            """,
            owner["id"],
        )
        return jsonable_encoder(
            {
                "items": [dict(row) for row in rows],
                "unlocated_count": unlocated,
            }
        )


@router.post("/storage-locations", status_code=201)
async def create_storage_location(
    payload: StorageLocationCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        try:
            row = await connection.fetchrow(
                """
                insert into tcg.storage_locations(
                    owner_id, code, label, location_type, notes
                ) values ($1, $2, $3, $4, $5)
                returning *
                """,
                owner["id"],
                payload.code,
                payload.label,
                payload.location_type,
                payload.notes,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=409,
                detail="A storage location with this code already exists",
            ) from exc
        except asyncpg.CheckViolationError as exc:
            raise HTTPException(
                status_code=422,
                detail="Location code must use uppercase letters/numbers, dashes and optional / segments",
            ) from exc
        return jsonable_encoder(dict(row))


@router.patch("/storage-locations/{location_id}")
async def update_storage_location(
    location_id: UUID,
    payload: StorageLocationPatch,
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
        current = await connection.fetchrow(
            """
            select * from tcg.storage_locations
            where id = $1 and owner_id = $2
            for update
            """,
            location_id,
            owner["id"],
        )
        if current is None:
            raise HTTPException(status_code=404, detail="Storage location not found")
        if current["version"] != expected_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Storage location changed",
                    "current_version": current["version"],
                },
            )

        if values.get("active") is False and current["active"]:
            item_count = await connection.fetchval(
                """
                select count(*)::int from tcg.inventory_items
                where owner_id = $1 and storage_location_id = $2
                """,
                owner["id"],
                location_id,
            )
            if item_count:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Move inventory out of this location before deactivating it",
                        "item_count": item_count,
                    },
                )

        assignments: list[str] = []
        params: list[object] = [location_id, owner["id"], expected_version]
        for column, value in values.items():
            params.append(value)
            assignments.append(f"{column} = ${len(params)}")
        assignments.extend(["version = version + 1", "updated_at = now()"])

        updated = await connection.fetchrow(
            f"""
            update tcg.storage_locations
            set {', '.join(assignments)}
            where id = $1 and owner_id = $2 and version = $3
            returning *
            """,
            *params,
        )
        if updated is None:
            raise HTTPException(status_code=409, detail="Storage location changed during update")
        summary = await _location_summary(connection, location_id, owner["id"])
        return jsonable_encoder(dict(summary))


@router.post("/storage-locations/{location_id}/assign")
async def assign_storage_location(
    location_id: UUID,
    payload: StorageLocationAssignment,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        location = await connection.fetchrow(
            """
            select id, code, active
            from tcg.storage_locations
            where id = $1 and owner_id = $2
            """,
            location_id,
            owner["id"],
        )
        if location is None:
            raise HTTPException(status_code=404, detail="Storage location not found")
        if not location["active"]:
            raise HTTPException(status_code=422, detail="Cannot assign inventory to an inactive location")

        ids = [item.inventory_id for item in payload.items]
        rows = await connection.fetch(
            """
            select id, version, status
            from tcg.inventory_items
            where owner_id = $1 and id = any($2::uuid[])
            order by id
            for update
            """,
            owner["id"],
            ids,
        )
        if len(rows) != len(ids):
            raise HTTPException(status_code=404, detail="One or more inventory items were not found")
        sold = [str(row["id"]) for row in rows if row["status"] == "SOLD"]
        if sold:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Sold inventory cannot be moved; use the refund/return workflow",
                    "items": sold,
                },
            )
        current = {row["id"]: row["version"] for row in rows}
        stale = [
            {
                "inventory_id": str(item.inventory_id),
                "current_version": current[item.inventory_id],
            }
            for item in payload.items
            if current[item.inventory_id] != item.version
        ]
        if stale:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "One or more inventory items changed",
                    "items": stale,
                },
            )

        updated = []
        for item in payload.items:
            row = await connection.fetchrow(
                """
                update tcg.inventory_items
                set storage_location_id = $1,
                    version = version + 1,
                    updated_at = now()
                where id = $2 and owner_id = $3 and version = $4
                returning id, inventory_code, storage_location_id, location, version
                """,
                location_id,
                item.inventory_id,
                owner["id"],
                item.version,
            )
            if row is None:
                raise HTTPException(status_code=409, detail="Inventory item changed during location assignment")
            updated.append(dict(row))

        return jsonable_encoder(
            {
                "location": dict(location),
                "updated_count": len(updated),
                "items": updated,
            }
        )
