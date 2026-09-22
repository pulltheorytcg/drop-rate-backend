from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .schemas import InventoryPatch

router = APIRouter(prefix="/api/v1")


def _request_id(request: Request) -> str:
    return request.state.request_id


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active owner membership",
        )
    return row


@router.get("/me")
async def me(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        return {
            "user_id": str(user.user_id),
            "owner": dict(owner),
        }


@router.get("/inventory")
async def list_inventory(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    search: str | None = Query(default=None, max_length=200),
    status_filter: str | None = Query(default=None, alias="status", max_length=30),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    search_value = (search or "").strip()
    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        params: list[object] = [owner["id"]]
        filters = ["i.owner_id = $1"]

        if search_value:
            params.append(f"%{search_value}%")
            index = len(params)
            filters.append(
                f"""(
                    i.inventory_code ilike ${index}
                    or p.name ilike ${index}
                    or p.set_name ilike ${index}
                    or coalesce(p.card_number, '') ilike ${index}
                    or p.game ilike ${index}
                )"""
            )
        if status_filter:
            params.append(status_filter)
            filters.append(f"i.status = ${len(params)}")

        where = " and ".join(filters)
        total = await connection.fetchval(
            f"""
            select count(*)
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id = i.catalogue_id
            where {where}
            """,
            *params,
        )

        params.extend([limit, offset])
        rows = await connection.fetch(
            f"""
            select
                i.id,
                i.inventory_code,
                i.acquisition_cost_minor,
                i.acquisition_date,
                i.currency,
                i.condition,
                i.grading_company,
                i.grade,
                i.certificate_number,
                i.language,
                i.location,
                i.store_price_minor,
                i.imported_valuation_minor,
                i.imported_valuation_date,
                i.imported_price_override_minor,
                i.identity_confirmed,
                i.status,
                i.notes,
                i.version,
                i.created_at,
                i.updated_at,
                p.id as catalogue_id,
                p.product_type,
                p.game,
                p.name,
                p.set_name,
                p.card_number,
                p.variant,
                p.rarity,
                p.language as catalogue_language
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id = i.catalogue_id
            where {where}
            order by i.updated_at desc, i.inventory_code
            limit ${len(params) - 1} offset ${len(params)}
            """,
            *params,
        )
        return jsonable_encoder(
            {
                "owner": dict(owner),
                "total": total,
                "limit": limit,
                "offset": offset,
                "items": [dict(row) for row in rows],
            }
        )


@router.patch("/inventory/{inventory_id}")
async def update_inventory(
    inventory_id: UUID,
    payload: InventoryPatch,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    values = payload.model_dump(exclude_unset=True)
    expected_version = values.pop("version")
    if not values:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one editable field is required",
        )

    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        assignments: list[str] = []
        params: list[object] = [inventory_id, owner["id"], expected_version]
        for column, value in values.items():
            params.append(value)
            assignments.append(f"{column} = ${len(params)}")
        assignments.extend(["version = version + 1", "updated_at = now()"])

        row = await connection.fetchrow(
            f"""
            update tcg.inventory_items
            set {", ".join(assignments)}
            where id = $1 and owner_id = $2 and version = $3
            returning *
            """,
            *params,
        )
        if row is None:
            visible = await connection.fetchval(
                """
                select version
                from tcg.inventory_items
                where id = $1 and owner_id = $2
                """,
                inventory_id,
                owner["id"],
            )
            if visible is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Inventory item not found",
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Inventory item changed", "current_version": visible},
            )
        return jsonable_encoder(dict(row))


@router.post("/automation/inventory-review")
async def inventory_review(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=96),
    ],
) -> dict:
    run_key = idempotency_key.strip()
    if not run_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key cannot be blank",
        )

    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        existing = await connection.fetchrow(
            """
            select id, result, created_at
            from tcg.automation_runs
            where owner_id = $1
              and job_type = 'INVENTORY_REVIEW'
              and run_key = $2
            """,
            owner["id"],
            run_key,
        )
        if existing is not None:
            return jsonable_encoder(
                {
                    "run_id": existing["id"],
                    "created_at": existing["created_at"],
                    "replayed": True,
                    "result": existing["result"],
                }
            )

        counts = await connection.fetchrow(
            """
            select
                count(*)::int as total_items,
                count(*) filter (where acquisition_cost_minor is null)::int
                    as missing_acquisition_cost,
                count(*) filter (where location is null or btrim(location) = '')::int
                    as missing_location,
                count(*) filter (where store_price_minor is null)::int
                    as missing_store_price,
                count(*) filter (where not identity_confirmed)::int
                    as identity_unconfirmed
            from tcg.inventory_items
            where owner_id = $1
            """,
            owner["id"],
        )
        result = dict(counts)

        try:
            created = await connection.fetchrow(
                """
                insert into tcg.automation_runs(
                    owner_id, job_type, run_key, result
                )
                values ($1, 'INVENTORY_REVIEW', $2, $3::jsonb)
                returning id, created_at
                """,
                owner["id"],
                run_key,
                json.dumps(result),
            )
        except asyncpg.UniqueViolationError:
            created = await connection.fetchrow(
                """
                select id, created_at, result
                from tcg.automation_runs
                where owner_id = $1
                  and job_type = 'INVENTORY_REVIEW'
                  and run_key = $2
                """,
                owner["id"],
                run_key,
            )
            return jsonable_encoder(
                {
                    "run_id": created["id"],
                    "created_at": created["created_at"],
                    "replayed": True,
                    "result": created["result"],
                }
            )

        return jsonable_encoder(
            {
                "run_id": created["id"],
                "created_at": created["created_at"],
                "replayed": False,
                "result": result,
            }
        )
