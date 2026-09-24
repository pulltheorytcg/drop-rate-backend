from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .auth import AuthenticatedUser, require_user
from .brands import brand_sql
from .db import user_connection
from .ownership import current_owner as _owner


router = APIRouter(prefix="/api/v1/identity-review", tags=["identity-review"])
BRAND_SQL = brand_sql("p")
ACTIVE_SQL = "i.status not in ('SOLD', 'WITHDRAWN')"


class IdentityReviewSelection(BaseModel):
    inventory_id: UUID
    version: int = Field(ge=1)


class IdentityConfirmRequest(BaseModel):
    items: list[IdentityReviewSelection] = Field(min_length=1, max_length=500)
    storage_location_id: UUID | None = None
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_items(self) -> "IdentityConfirmRequest":
        ids = [item.inventory_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each inventory item may appear only once")
        self.notes = self.notes.strip()
        return self


class IdentityRevokeRequest(BaseModel):
    items: list[IdentityReviewSelection] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_items(self) -> "IdentityRevokeRequest":
        ids = [item.inventory_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each inventory item may appear only once")
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("A correction reason is required")
        return self


def _catalogue_snapshot(row) -> dict:
    return {
        "catalogue_id": str(row["catalogue_id"]),
        "product_type": row["product_type"],
        "game": row["game"],
        "brand": row["brand"],
        "name": row["name"],
        "set_name": row["set_name"],
        "card_number": row["card_number"],
        "variant": row["variant"],
        "rarity": row["rarity"],
        "language": row["catalogue_language"],
    }


def _physical_snapshot(row) -> dict:
    return {
        "inventory_id": str(row["id"]),
        "inventory_code": row["inventory_code"],
        "condition": row["condition"],
        "seal_status": row["seal_status"],
        "grading_company": row["grading_company"],
        "grade": row["grade"],
        "certificate_number": row["certificate_number"],
        "language": row["language"],
        "storage_location_id": str(row["storage_location_id"]) if row["storage_location_id"] else None,
        "location": row["location"],
        "status": row["status"],
        "identity_confirmed": row["identity_confirmed"],
        "version": row["version"],
    }


async def _catalogue_for_owner(connection, owner_id: UUID, catalogue_id: UUID):
    return await connection.fetchrow(
        f"""
        select
            p.id as catalogue_id, p.product_type, p.game, {BRAND_SQL} as brand,
            p.name, p.set_name, p.card_number, p.variant, p.rarity,
            p.language as catalogue_language
        from tcg.catalogue_products p
        where p.id = $1
          and exists (
            select 1
            from tcg.inventory_items i
            where i.owner_id = $2
              and i.catalogue_id = p.id
              and {ACTIVE_SQL}
          )
        """,
        catalogue_id,
        owner_id,
    )


@router.get("")
async def list_identity_review_groups(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    brand: str | None = Query(default=None, max_length=80),
    search: str | None = Query(default=None, max_length=200),
    only_unconfirmed: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    search_value = (search or "").strip()
    brand_value = (brand or "").strip()

    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        params: list[object] = [owner["id"]]
        filters = ["i.owner_id = $1", ACTIVE_SQL]

        if brand_value:
            params.append(brand_value)
            filters.append(f"({BRAND_SQL}) = ${len(params)}")
        if search_value:
            params.append(f"%{search_value}%")
            idx = len(params)
            filters.append(
                f"""(
                    p.name ilike ${idx}
                    or p.set_name ilike ${idx}
                    or coalesce(p.card_number, '') ilike ${idx}
                    or p.game ilike ${idx}
                )"""
            )
        where = " and ".join(filters)
        count_where = where + (" and not i.identity_confirmed" if only_unconfirmed else "")
        total_groups = await connection.fetchval(
            f"""select count(distinct p.id)::int
                from tcg.inventory_items i
                join tcg.catalogue_products p on p.id=i.catalogue_id
                where {count_where}""",
            *params,
        )
        group_having = (
            "having count(*) filter(where not i.identity_confirmed) > 0"
            if only_unconfirmed
            else ""
        )
        params.extend([limit, offset])
        rows = await connection.fetch(
            f"""
            select
                p.id as catalogue_id, p.product_type, p.game, {BRAND_SQL} as brand,
                p.name, p.set_name, p.card_number, p.variant, p.rarity,
                p.language as catalogue_language,
                count(*)::int as active_copies,
                count(*) filter(where i.identity_confirmed)::int as confirmed_copies,
                count(*) filter(where not i.identity_confirmed)::int as unconfirmed_copies,
                count(*) filter(where i.storage_location_id is not null)::int as located_copies,
                count(*) filter(where i.grading_company is not null and i.grade is not null)::int as graded_copies
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where {where}
            group by p.id,p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language
            {group_having}
            order by count(*) filter(where not i.identity_confirmed) desc,
                     p.game,p.set_name,p.name,p.card_number nulls last
            limit ${len(params)-1} offset ${len(params)}
            """,
            *params,
        )
        return jsonable_encoder({
            "total_groups": total_groups,
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
        })


@router.get("/{catalogue_id}")
async def identity_review_group(
    catalogue_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        catalogue = await _catalogue_for_owner(connection, owner["id"], catalogue_id)
        if catalogue is None:
            raise HTTPException(status_code=404, detail="Identity review group not found")
        items = await connection.fetch(
            """
            select i.id,i.inventory_code,i.condition,i.seal_status,i.grading_company,i.grade,
                   i.certificate_number,i.language,i.storage_location_id,i.location,
                   i.identity_confirmed,i.status,i.version,i.created_at,i.updated_at,
                   sl.code as storage_location_code,sl.label as storage_location_label
            from tcg.inventory_items i
            left join tcg.storage_locations sl on sl.id=i.storage_location_id
            where i.owner_id=$1 and i.catalogue_id=$2
              and i.status not in ('SOLD','WITHDRAWN')
            order by i.identity_confirmed,i.inventory_code
            """,
            owner["id"], catalogue_id,
        )
        events = await connection.fetch(
            """
            select id,inventory_id,event_type,actor_user_id,verification_method,
                   inventory_version,catalogue_snapshot,physical_snapshot,notes,created_at
            from tcg.identity_verification_events
            where owner_id=$1 and catalogue_id=$2
            order by created_at desc,id desc limit 100
            """,
            owner["id"], catalogue_id,
        )
        return jsonable_encoder({
            "catalogue": dict(catalogue),
            "items": [dict(row) for row in items],
            "events": [dict(row) for row in events],
        })


@router.post("/{catalogue_id}/confirm")
async def confirm_identity_group(
    catalogue_id: UUID,
    payload: IdentityConfirmRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        async with connection.transaction():
            catalogue = await _catalogue_for_owner(connection, owner["id"], catalogue_id)
            if catalogue is None:
                raise HTTPException(status_code=404, detail="Identity review group not found")

            if payload.storage_location_id is not None:
                location = await connection.fetchrow(
                    """select id,code,label,active from tcg.storage_locations
                       where id=$1 and owner_id=$2""",
                    payload.storage_location_id, owner["id"],
                )
                if location is None:
                    raise HTTPException(status_code=404, detail="Storage location not found")
                if not location["active"]:
                    raise HTTPException(status_code=422, detail="Cannot assign confirmed stock to an inactive location")

            ids = [item.inventory_id for item in payload.items]
            rows = await connection.fetch(
                """
                select i.id,i.inventory_code,i.catalogue_id,i.condition,i.seal_status,
                       i.grading_company,i.grade,i.certificate_number,i.language,
                       i.storage_location_id,i.location,i.identity_confirmed,i.status,i.version
                from tcg.inventory_items i
                where i.owner_id=$1 and i.id=any($2::uuid[])
                order by i.id for update
                """,
                owner["id"], ids,
            )
            if len(rows) != len(ids):
                raise HTTPException(status_code=404, detail="One or more selected inventory items were not found")

            by_id = {row["id"]: row for row in rows}
            wrong_catalogue = [str(row["id"]) for row in rows if row["catalogue_id"] != catalogue_id]
            if wrong_catalogue:
                raise HTTPException(status_code=422, detail={"message":"Selected copies do not all belong to this canonical card","items":wrong_catalogue})
            inactive = [str(row["id"]) for row in rows if row["status"] in {"SOLD","WITHDRAWN"}]
            if inactive:
                raise HTTPException(status_code=409, detail={"message":"Sold or withdrawn inventory cannot be identity-confirmed","items":inactive})
            already = [str(row["id"]) for row in rows if row["identity_confirmed"]]
            if already:
                raise HTTPException(status_code=409, detail={"message":"One or more selected copies are already confirmed","items":already})

            stale = [
                {"inventory_id":str(item.inventory_id),"current_version":by_id[item.inventory_id]["version"]}
                for item in payload.items if by_id[item.inventory_id]["version"] != item.version
            ]
            if stale:
                raise HTTPException(status_code=409, detail={"message":"One or more inventory items changed","items":stale})

            catalogue_snapshot = _catalogue_snapshot(catalogue)
            updated = []
            for item in payload.items:
                row = await connection.fetchrow(
                    """
                    update tcg.inventory_items
                    set identity_confirmed=true,
                        storage_location_id=coalesce($1,storage_location_id),
                        version=version+1,updated_at=now()
                    where id=$2 and owner_id=$3 and version=$4
                    returning *
                    """,
                    payload.storage_location_id,item.inventory_id,owner["id"],item.version,
                )
                if row is None:
                    raise HTTPException(status_code=409, detail="Inventory item changed during identity confirmation")
                await connection.execute(
                    """
                    insert into tcg.identity_verification_events(
                        owner_id,inventory_id,catalogue_id,event_type,actor_user_id,
                        verification_method,inventory_version,catalogue_snapshot,
                        physical_snapshot,notes
                    ) values($1,$2,$3,'CONFIRMED',$4,'PHYSICAL_REVIEW',$5,$6::jsonb,$7::jsonb,$8)
                    """,
                    owner["id"],row["id"],catalogue_id,user.user_id,row["version"],
                    json.dumps(catalogue_snapshot),json.dumps(_physical_snapshot(row)),payload.notes,
                )
                updated.append(dict(row))
            return jsonable_encoder({"catalogue":catalogue_snapshot,"confirmed_count":len(updated),"items":updated})


@router.post("/{catalogue_id}/revoke")
async def revoke_identity_group(
    catalogue_id: UUID,
    payload: IdentityRevokeRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        owner = await _owner(connection)
        async with connection.transaction():
            catalogue = await _catalogue_for_owner(connection, owner["id"], catalogue_id)
            if catalogue is None:
                raise HTTPException(status_code=404, detail="Identity review group not found")
            ids = [item.inventory_id for item in payload.items]
            rows = await connection.fetch(
                """select * from tcg.inventory_items
                   where owner_id=$1 and id=any($2::uuid[])
                   order by id for update""",
                owner["id"],ids,
            )
            if len(rows) != len(ids):
                raise HTTPException(status_code=404, detail="One or more selected inventory items were not found")
            by_id = {row["id"]: row for row in rows}
            for row in rows:
                if row["catalogue_id"] != catalogue_id:
                    raise HTTPException(status_code=422, detail="Selected copies do not all belong to this canonical card")
                if row["status"] in {"SOLD","WITHDRAWN","RESERVED"}:
                    raise HTTPException(status_code=409, detail="Sold, withdrawn, or reserved inventory cannot be changed here")
                if not row["identity_confirmed"]:
                    raise HTTPException(status_code=409, detail="One or more selected copies are already unconfirmed")
            stale = [
                {"inventory_id":str(item.inventory_id),"current_version":by_id[item.inventory_id]["version"]}
                for item in payload.items if by_id[item.inventory_id]["version"] != item.version
            ]
            if stale:
                raise HTTPException(status_code=409, detail={"message":"One or more inventory items changed","items":stale})

            catalogue_snapshot = _catalogue_snapshot(catalogue)
            updated = []
            for item in payload.items:
                row = await connection.fetchrow(
                    """update tcg.inventory_items
                       set identity_confirmed=false,version=version+1,updated_at=now()
                       where id=$1 and owner_id=$2 and version=$3 returning *""",
                    item.inventory_id,owner["id"],item.version,
                )
                if row is None:
                    raise HTTPException(status_code=409, detail="Inventory item changed during identity correction")
                await connection.execute(
                    """
                    insert into tcg.identity_verification_events(
                        owner_id,inventory_id,catalogue_id,event_type,actor_user_id,
                        verification_method,inventory_version,catalogue_snapshot,
                        physical_snapshot,notes
                    ) values($1,$2,$3,'REVOKED',$4,'CORRECTION',$5,$6::jsonb,$7::jsonb,$8)
                    """,
                    owner["id"],row["id"],catalogue_id,user.user_id,row["version"],
                    json.dumps(catalogue_snapshot),json.dumps(_physical_snapshot(row)),payload.reason,
                )
                updated.append(dict(row))
            return jsonable_encoder({"catalogue":catalogue_snapshot,"revoked_count":len(updated),"items":updated})
