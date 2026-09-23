from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .schemas import (
    BulkCostAllocation,
    InventoryApproval,
    InventoryPatch,
    PurchaseLotAllocation,
    PurchaseLotCreate,
    ReadinessIssue,
)

router = APIRouter(prefix="/api/v1")

ACTIVE_INVENTORY_SQL = "i.status not in ('SOLD', 'WITHDRAWN')"
READY_SQL = f"""
    i.acquisition_cost_minor is not null
    and i.condition is not null and btrim(i.condition) <> ''
    and i.location is not null and btrim(i.location) <> ''
    and i.store_price_minor is not null
    and i.identity_confirmed
    and {ACTIVE_INVENTORY_SQL}
"""

ISSUE_FILTERS = {
    "missing_cost": f"({ACTIVE_INVENTORY_SQL}) and i.acquisition_cost_minor is null",
    "missing_condition": f"({ACTIVE_INVENTORY_SQL}) and (i.condition is null or btrim(i.condition) = '')",
    "missing_location": f"({ACTIVE_INVENTORY_SQL}) and (i.location is null or btrim(i.location) = '')",
    "missing_price": f"({ACTIVE_INVENTORY_SQL}) and i.store_price_minor is null",
    "identity_unconfirmed": f"({ACTIVE_INVENTORY_SQL}) and not i.identity_confirmed",
    "approval_ready": f"i.status in ('DRAFT', 'INSPECTION') and ({READY_SQL})",
}


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
        return {"user_id": str(user.user_id), "owner": dict(owner)}


@router.get("/inventory/readiness")
async def inventory_readiness(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        row = await connection.fetchrow(
            f"""
            select
                count(*) filter (where {ACTIVE_INVENTORY_SQL})::int as total,
                count(*) filter (where {ISSUE_FILTERS['missing_cost']})::int as missing_cost,
                count(*) filter (where {ISSUE_FILTERS['missing_condition']})::int as missing_condition,
                count(*) filter (where {ISSUE_FILTERS['missing_location']})::int as missing_location,
                count(*) filter (where {ISSUE_FILTERS['missing_price']})::int as missing_price,
                count(*) filter (where {ISSUE_FILTERS['identity_unconfirmed']})::int as identity_unconfirmed,
                count(*) filter (where i.status = 'APPROVED')::int as approved,
                count(*) filter (where {ISSUE_FILTERS['approval_ready']})::int as approval_ready
            from tcg.inventory_items i
            where i.owner_id = $1
            """,
            owner["id"],
        )
        return jsonable_encoder(dict(row))


@router.get("/inventory")
async def list_inventory(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    search: str | None = Query(default=None, max_length=200),
    status_filter: str | None = Query(default=None, alias="status", max_length=30),
    issue: ReadinessIssue | None = Query(default=None),
    storage_location_id: UUID | None = Query(default=None),
    unlocated: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    if storage_location_id is not None and unlocated:
        raise HTTPException(
            status_code=422,
            detail="Choose either a storage location or unlocated inventory, not both",
        )

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
                    or coalesce(i.location, '') ilike ${index}
                )"""
            )
        if status_filter:
            params.append(status_filter)
            filters.append(f"i.status = ${len(params)}")
        if issue:
            filters.append(ISSUE_FILTERS[issue])
        if storage_location_id is not None:
            params.append(storage_location_id)
            filters.append(f"i.storage_location_id = ${len(params)}")
        if unlocated:
            filters.append("i.storage_location_id is null")

        where = " and ".join(filters)
        total = await connection.fetchval(
            f"""select count(*) from tcg.inventory_items i
            join tcg.catalogue_products p on p.id = i.catalogue_id where {where}""",
            *params,
        )

        params.extend([limit, offset])
        rows = await connection.fetch(
            f"""
            select
                i.id, i.inventory_code, i.acquisition_cost_minor, i.acquisition_date,
                i.currency, i.condition, i.grading_company, i.grade,
                i.certificate_number, i.language, i.location, i.storage_location_id,
                sl.code as storage_location_code, sl.label as storage_location_label,
                i.store_price_minor, i.imported_valuation_minor, i.imported_valuation_date,
                i.imported_price_override_minor, i.identity_confirmed, i.status,
                i.notes, i.version, i.created_at, i.updated_at, i.purchase_lot_id,
                pl.lot_code as purchase_lot_code,
                p.id as catalogue_id, p.product_type, p.game, p.name, p.set_name,
                p.card_number, p.variant, p.rarity, p.language as catalogue_language
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id = i.catalogue_id
            left join tcg.purchase_lots pl on pl.id = i.purchase_lot_id
            left join tcg.storage_locations sl on sl.id = i.storage_location_id
            where {where}
            order by i.updated_at desc, i.inventory_code
            limit ${len(params) - 1} offset ${len(params)}
            """,
            *params,
        )
        return jsonable_encoder(
            {"owner": dict(owner), "total": total, "limit": limit,
             "offset": offset, "items": [dict(row) for row in rows]}
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
        raise HTTPException(status_code=422, detail="At least one editable field is required")
    if "location" in values:
        raise HTTPException(
            status_code=422,
            detail="Physical location must be changed using a registered storage location",
        )

    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        current_item = await connection.fetchrow(
            "select status, version from tcg.inventory_items where id = $1 and owner_id = $2",
            inventory_id, owner["id"],
        )
        if current_item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        if current_item["status"] == "SOLD":
            raise HTTPException(status_code=409, detail="Sold inventory is immutable; use the refund/return workflow")

        if "storage_location_id" in values and values["storage_location_id"] is not None:
            visible_location = await connection.fetchrow(
                """
                select id, active from tcg.storage_locations
                where id = $1 and owner_id = $2
                """,
                values["storage_location_id"],
                owner["id"],
            )
            if visible_location is None:
                raise HTTPException(status_code=404, detail="Storage location not found")
            if not visible_location["active"]:
                raise HTTPException(status_code=422, detail="Cannot assign inventory to an inactive location")

        assignments: list[str] = []
        params: list[object] = [inventory_id, owner["id"], expected_version]
        for column, value in values.items():
            params.append(value)
            assignments.append(f"{column} = ${len(params)}")
        assignments.extend(["version = version + 1", "updated_at = now()"])
        row = await connection.fetchrow(
            f"""update tcg.inventory_items set {', '.join(assignments)}
            where id = $1 and owner_id = $2 and version = $3 returning *""",
            *params,
        )
        if row is None:
            visible = await connection.fetchval(
                "select version from tcg.inventory_items where id = $1 and owner_id = $2",
                inventory_id, owner["id"],
            )
            if visible is None:
                raise HTTPException(status_code=404, detail="Inventory item not found")
            raise HTTPException(status_code=409, detail={
                "message": "Inventory item changed", "current_version": visible,
            })
        return jsonable_encoder(dict(row))


@router.post("/inventory/{inventory_id}/approve")
async def approve_inventory(
    inventory_id: UUID,
    payload: InventoryApproval,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        item = await connection.fetchrow(
            """select * from tcg.inventory_items
            where id = $1 and owner_id = $2 for update""",
            inventory_id, owner["id"],
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        if item["version"] != payload.version:
            raise HTTPException(status_code=409, detail={
                "message": "Inventory item changed", "current_version": item["version"],
            })
        if item["status"] == "SOLD":
            raise HTTPException(status_code=409, detail="Sold inventory cannot be approved again")
        missing = []
        if item["acquisition_cost_minor"] is None: missing.append("acquisition cost")
        if not (item["condition"] or "").strip(): missing.append("condition")
        if not (item["location"] or "").strip(): missing.append("location")
        if item["store_price_minor"] is None: missing.append("store price")
        if not item["identity_confirmed"]: missing.append("identity confirmation")
        if item["status"] == "WITHDRAWN": missing.append("active status")
        if missing:
            raise HTTPException(status_code=422, detail={
                "message": "Item is not ready for approval", "missing": missing,
            })
        row = await connection.fetchrow(
            """update tcg.inventory_items
            set status = 'APPROVED', version = version + 1, updated_at = now()
            where id = $1 and owner_id = $2 and version = $3 returning *""",
            inventory_id, owner["id"], payload.version,
        )
        return jsonable_encoder(dict(row))


@router.post("/inventory/bulk-cost")
async def allocate_bulk_cost(
    payload: BulkCostAllocation,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        ids = [item.inventory_id for item in payload.items]
        rows = await connection.fetch(
            """select id, version, status from tcg.inventory_items
            where owner_id = $1 and id = any($2::uuid[]) order by id for update""",
            owner["id"], ids,
        )
        if len(rows) != len(ids):
            raise HTTPException(status_code=404, detail="One or more inventory items were not found")
        sold = [str(row["id"]) for row in rows if row["status"] == "SOLD"]
        if sold:
            raise HTTPException(status_code=409, detail={
                "message": "Acquisition cost cannot be changed after sale",
                "items": sold,
            })
        current = {row["id"]: row["version"] for row in rows}
        stale = [
            {"inventory_id": str(item.inventory_id), "current_version": current[item.inventory_id]}
            for item in payload.items if current[item.inventory_id] != item.version
        ]
        if stale:
            raise HTTPException(status_code=409, detail={
                "message": "One or more inventory items changed", "items": stale,
            })
        updated = []
        for item in payload.items:
            row = await connection.fetchrow(
                """update tcg.inventory_items
                set acquisition_cost_minor = $1, acquisition_date = $2,
                    version = version + 1, updated_at = now()
                where id = $3 and owner_id = $4 and version = $5
                returning id, inventory_code, acquisition_cost_minor, acquisition_date, version""",
                item.acquisition_cost_minor, payload.acquisition_date,
                item.inventory_id, owner["id"], item.version,
            )
            updated.append(dict(row))
        return jsonable_encoder({
            "total_cost_minor": payload.total_cost_minor,
            "updated_count": len(updated), "items": updated,
        })


@router.get("/purchase-lots")
async def list_purchase_lots(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select
                pl.id, pl.lot_code, pl.description, pl.source, pl.purchase_date,
                pl.purchase_price_minor, pl.fees_minor, pl.shipping_minor,
                pl.total_cost_minor, pl.currency, pl.allocation_method, pl.notes,
                pl.version, pl.created_at, pl.updated_at,
                count(i.id)::int as item_count,
                coalesce(sum(i.acquisition_cost_minor), 0)::bigint as allocated_cost_minor,
                (pl.total_cost_minor - coalesce(sum(i.acquisition_cost_minor), 0))::bigint
                    as remaining_cost_minor
            from tcg.purchase_lots pl
            left join tcg.inventory_items i on i.purchase_lot_id = pl.id
            where pl.owner_id = $1
            group by pl.id
            order by pl.created_at desc
            """,
            owner["id"],
        )
        return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/purchase-lots", status_code=201)
async def create_purchase_lot(
    payload: PurchaseLotCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        lot_id = uuid4()
        year = payload.purchase_date.year if payload.purchase_date else 0
        prefix = str(year) if year else "UNDATED"
        lot_code = f"LOT-{prefix}-{lot_id.hex[:8].upper()}"
        row = await connection.fetchrow(
            """
            insert into tcg.purchase_lots(
                id, owner_id, lot_code, description, source, purchase_date,
                purchase_price_minor, fees_minor, shipping_minor, currency,
                allocation_method, notes
            ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            returning *
            """,
            lot_id, owner["id"], lot_code, payload.description, payload.source,
            payload.purchase_date, payload.purchase_price_minor, payload.fees_minor,
            payload.shipping_minor, payload.currency, payload.allocation_method,
            payload.notes,
        )
        return jsonable_encoder(dict(row))


@router.post("/purchase-lots/{lot_id}/allocate")
async def allocate_purchase_lot(
    lot_id: UUID,
    payload: PurchaseLotAllocation,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        lot = await connection.fetchrow(
            """select * from tcg.purchase_lots
            where id = $1 and owner_id = $2 for update""",
            lot_id, owner["id"],
        )
        if lot is None:
            raise HTTPException(status_code=404, detail="Purchase lot not found")
        if lot["version"] != payload.version:
            raise HTTPException(status_code=409, detail={
                "message": "Purchase lot changed", "current_version": lot["version"],
            })

        ids = [item.inventory_id for item in payload.items]
        rows = await connection.fetch(
            """select id, version, purchase_lot_id, status from tcg.inventory_items
            where owner_id = $1 and id = any($2::uuid[]) order by id for update""",
            owner["id"], ids,
        )
        if len(rows) != len(ids):
            raise HTTPException(status_code=404, detail="One or more inventory items were not found")
        sold = [str(row["id"]) for row in rows if row["status"] == "SOLD"]
        if sold:
            raise HTTPException(status_code=409, detail={
                "message": "Sold inventory cannot be reallocated to a purchase lot",
                "items": sold,
            })

        current = {row["id"]: row for row in rows}
        stale = [
            {"inventory_id": str(item.inventory_id), "current_version": current[item.inventory_id]["version"]}
            for item in payload.items
            if current[item.inventory_id]["version"] != item.version
        ]
        if stale:
            raise HTTPException(status_code=409, detail={
                "message": "One or more inventory items changed", "items": stale,
            })

        conflicts = [
            str(item.inventory_id) for item in payload.items
            if current[item.inventory_id]["purchase_lot_id"] not in (None, lot_id)
        ]
        if conflicts:
            raise HTTPException(status_code=409, detail={
                "message": "One or more inventory items already belong to another purchase lot",
                "items": conflicts,
            })

        existing_other_cost = await connection.fetchval(
            """select coalesce(sum(acquisition_cost_minor), 0)
            from tcg.inventory_items
            where purchase_lot_id = $1 and not (id = any($2::uuid[]))""",
            lot_id, ids,
        )
        proposed_cost = sum(item.acquisition_cost_minor for item in payload.items)
        final_allocated_cost = existing_other_cost + proposed_cost
        if final_allocated_cost > lot["total_cost_minor"]:
            raise HTTPException(status_code=422, detail={
                "message": "Allocation exceeds purchase lot total",
                "total_cost_minor": lot["total_cost_minor"],
                "proposed_allocated_cost_minor": final_allocated_cost,
            })

        updated = []
        for item in payload.items:
            row = await connection.fetchrow(
                """update tcg.inventory_items
                set purchase_lot_id = $1, acquisition_cost_minor = $2,
                    acquisition_date = $3, currency = $4,
                    version = version + 1, updated_at = now()
                where id = $5 and owner_id = $6 and version = $7
                returning id, inventory_code, purchase_lot_id,
                    acquisition_cost_minor, acquisition_date, currency, version""",
                lot_id, item.acquisition_cost_minor, lot["purchase_date"],
                lot["currency"], item.inventory_id, owner["id"], item.version,
            )
            updated.append(dict(row))

        lot_row = await connection.fetchrow(
            """update tcg.purchase_lots
            set version = version + 1, updated_at = now()
            where id = $1 and owner_id = $2 and version = $3
            returning *""",
            lot_id, owner["id"], payload.version,
        )
        return jsonable_encoder({
            "lot": dict(lot_row),
            "allocated_cost_minor": final_allocated_cost,
            "remaining_cost_minor": lot["total_cost_minor"] - final_allocated_cost,
            "updated_count": len(updated),
            "items": updated,
        })


@router.post("/automation/inventory-review")
async def inventory_review(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=96)],
) -> dict:
    run_key = idempotency_key.strip()
    if not run_key:
        raise HTTPException(status_code=422, detail="Idempotency-Key cannot be blank")
    async with user_connection(
        request.app.state.db_pool, user.user_id, _request_id(request)
    ) as connection:
        owner = await _owner(connection)
        existing = await connection.fetchrow(
            """select id, result, created_at from tcg.automation_runs
            where owner_id = $1 and job_type = 'INVENTORY_REVIEW' and run_key = $2""",
            owner["id"], run_key,
        )
        if existing is not None:
            return jsonable_encoder({"run_id": existing["id"], "created_at": existing["created_at"], "replayed": True, "result": existing["result"]})
        counts = await connection.fetchrow(
            """select count(*) filter (where status not in ('SOLD', 'WITHDRAWN'))::int as total_items,
            count(*) filter (where status not in ('SOLD', 'WITHDRAWN') and acquisition_cost_minor is null)::int as missing_acquisition_cost,
            count(*) filter (where status not in ('SOLD', 'WITHDRAWN') and (location is null or btrim(location) = ''))::int as missing_location,
            count(*) filter (where status not in ('SOLD', 'WITHDRAWN') and store_price_minor is null)::int as missing_store_price,
            count(*) filter (where status not in ('SOLD', 'WITHDRAWN') and not identity_confirmed)::int as identity_unconfirmed
            from tcg.inventory_items where owner_id = $1""", owner["id"],
        )
        result = dict(counts)
        try:
            created = await connection.fetchrow(
                """insert into tcg.automation_runs(owner_id, job_type, run_key, result)
                values ($1, 'INVENTORY_REVIEW', $2, $3::jsonb) returning id, created_at""",
                owner["id"], run_key, json.dumps(result),
            )
        except asyncpg.UniqueViolationError:
            created = await connection.fetchrow(
                """select id, created_at, result from tcg.automation_runs
                where owner_id = $1 and job_type = 'INVENTORY_REVIEW' and run_key = $2""",
                owner["id"], run_key,
            )
            return jsonable_encoder({"run_id": created["id"], "created_at": created["created_at"], "replayed": True, "result": created["result"]})
        return jsonable_encoder({"run_id": created["id"], "created_at": created["created_at"], "replayed": False, "result": result})
