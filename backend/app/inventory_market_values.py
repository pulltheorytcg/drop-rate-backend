from __future__ import annotations

from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection


router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


async def _owner(connection: asyncpg.Connection) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        select id
        from tcg.owners
        where active
        order by founder_slot nulls last
        limit 1
        """
    )
    if row is None:
        raise HTTPException(status_code=403, detail="No active owner membership")
    return row


@router.get("/market-values")
async def inventory_market_values(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    inventory_id: list[UUID] = Query(default=[]),
) -> dict:
    """Return current read-only pricing outputs for visible founder inventory rows."""
    ids = list(dict.fromkeys(inventory_id))
    if len(ids) > 100:
        raise HTTPException(status_code=422, detail="At most 100 inventory IDs may be requested")
    if not ids:
        return {"items": []}

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
                i.market_value_minor,
                i.recommended_retail_minor,
                i.pricing_updated_at,
                s.confidence,
                s.source_count,
                s.observation_count,
                s.newest_observation_at
            from tcg.inventory_items i
            left join tcg.pricing_snapshots s on s.id = i.latest_pricing_snapshot_id
            where i.owner_id = $1
              and i.id = any($2::uuid[])
            """,
            owner["id"],
            ids,
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})
