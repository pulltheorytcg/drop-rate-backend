from __future__ import annotations

from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from .ownership import current_owner as _owner
from .auth import AuthenticatedUser, require_user
from .db import user_connection


router = APIRouter(prefix="/api/v1")



@router.get("/inventory/state")
async def inventory_state(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    ids: str = Query(min_length=1, max_length=4000),
) -> dict:
    raw_ids = [value.strip() for value in ids.split(",") if value.strip()]
    if not raw_ids or len(raw_ids) > 100:
        raise HTTPException(status_code=422, detail="Provide between 1 and 100 inventory IDs")

    try:
        inventory_ids = [UUID(value) for value in raw_ids]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid inventory ID") from exc

    if len(inventory_ids) != len(set(inventory_ids)):
        raise HTTPException(status_code=422, detail="Inventory IDs must be unique")

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select
                i.id,
                i.condition,
                i.seal_status,
                i.version,
                p.product_type
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id = i.catalogue_id
            where i.owner_id = $1 and i.id = any($2::uuid[])
            """,
            owner["id"],
            inventory_ids,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})
