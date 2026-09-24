from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner


router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])


ListingStatus = Literal["DRAFT", "ACTIVE", "PAUSED", "ARCHIVED"]
MemberState = Literal["ACTIVE", "PAUSED", "REMOVED"]


class ListingFromInventoryCreate(BaseModel):
    version: int = Field(ge=1)
    minimum_sale_price_minor: int | None = Field(default=None, ge=0)


class ListingPatch(BaseModel):
    version: int = Field(ge=1)
    store_price_minor: int | None = Field(default=None, ge=0)
    status: ListingStatus | None = None

    @model_validator(mode="after")
    def at_least_one_change(self) -> "ListingPatch":
        if not (self.model_fields_set - {"version"}):
            raise ValueError("At least one listing field must be changed")
        return self


class ListingMemberPatch(BaseModel):
    version: int = Field(ge=1)
    minimum_sale_price_minor: int | None = Field(default=None, ge=0)
    state: MemberState | None = None

    @model_validator(mode="after")
    def at_least_one_change(self) -> "ListingMemberPatch":
        if not (self.model_fields_set - {"version"}):
            raise ValueError("At least one membership field must be changed")
        return self


class TestReservationCreate(BaseModel):
    reference: str = Field(min_length=1, max_length=120)
    line_reference: str = Field(default="", max_length=120)
    quantity: int = Field(default=1, ge=1, le=20)
    expires_in_minutes: int | None = Field(default=30, ge=5, le=1440)
    notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def normalise(self) -> "TestReservationCreate":
        self.reference = self.reference.strip()
        self.line_reference = self.line_reference.strip()
        self.notes = self.notes.strip()
        if not self.reference:
            raise ValueError("reference cannot be blank")
        return self


class ReservationAction(BaseModel):
    notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def normalise(self) -> "ReservationAction":
        self.notes = self.notes.strip()
        return self


def _clean(value: object) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    return text or None


def _key(value: object) -> str | None:
    text = _clean(value)
    return text.casefold() if text else None


def listing_shape(item: asyncpg.Record) -> dict[str, object]:
    product_type = str(item["product_type"])
    language = _clean(item["language"] or item["catalogue_language"])
    condition = _clean(item["condition"])
    grading_company = _clean(item["grading_company"])
    grade = _clean(item["grade"])
    seal_status = _clean(item["seal_status"])

    if product_type == "CARD" and not grading_company and not grade:
        if not language:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Raw cards need a confirmed language before they can join a pooled listing",
                    "missing": ["language"],
                },
            )
        if not condition:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Raw cards need a condition before they can join a pooled listing",
                    "missing": ["condition"],
                },
            )
        pooling_mode = "POOLED"
        identity = {
            "catalogue_id": str(item["catalogue_id"]),
            "product_type": "CARD",
            "pooling_mode": pooling_mode,
            "language": _key(language),
            "condition": _key(condition),
            "grading_company": None,
            "grade": None,
            "seal_status": None,
        }
    else:
        pooling_mode = "UNIQUE"
        identity = {
            "catalogue_id": str(item["catalogue_id"]),
            "product_type": product_type,
            "pooling_mode": pooling_mode,
            "inventory_id": str(item["id"]),
            "language": _key(language),
            "condition": _key(condition),
            "grading_company": _key(grading_company),
            "grade": _key(grade),
            "seal_status": _key(seal_status),
        }

    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "fingerprint": digest,
        "pooling_mode": pooling_mode,
        "product_type": product_type,
        "language": language,
        "condition": condition,
        "grading_company": grading_company,
        "grade": grade,
        "seal_status": seal_status,
    }


async def _require_founder(connection: asyncpg.Connection) -> asyncpg.Record:
    owner = await _owner(connection)
    if owner["role"] != "FOUNDER":
        raise HTTPException(status_code=403, detail="Founder access is required")
    return owner


async def _set_user_context(connection: asyncpg.Connection, user_id: UUID | str) -> None:
    await connection.execute(
        "select set_config('tcg.user_id',$1,true)",
        str(user_id),
    )


async def pool_state(
    connection: asyncpg.Connection,
    *,
    listing_id: UUID,
    sale_price_minor: int,
) -> dict[str, object]:
    caller_user_id = await connection.fetchval(
        "select nullif(current_setting('tcg.user_id',true),'')"
    )
    members = await connection.fetch(
        """
        select
          id,inventory_id,owner_id,owner_context_user_id,
          minimum_sale_price_minor,allocation_priority,eligible_since,state
        from tcg.listing_inventory_members
        where listing_id=$1 and state='ACTIVE'
        order by allocation_priority,eligible_since,inventory_id
        """,
        listing_id,
    )
    eligible: list[dict[str, object]] = []
    ineligible_price = 0
    unavailable = 0

    grouped: dict[tuple[UUID, UUID], list[asyncpg.Record]] = defaultdict(list)
    for member in members:
        if int(member["minimum_sale_price_minor"]) > sale_price_minor:
            ineligible_price += 1
            continue
        grouped[(member["owner_id"], member["owner_context_user_id"])].append(member)

    try:
        for (owner_id, context_user_id), group in grouped.items():
            await _set_user_context(connection, context_user_id)
            ids = [row["inventory_id"] for row in group]
            rows = await connection.fetch(
                """
                select id,inventory_code,status,identity_confirmed,
                       acquisition_cost_minor,storage_location_id,store_price_minor,version
                from tcg.inventory_items
                where owner_id=$1 and id=any($2::uuid[])
                """,
                owner_id,
                ids,
            )
            by_id = {row["id"]: row for row in rows}
            for member in group:
                item = by_id.get(member["inventory_id"])
                if (
                    item is None
                    or item["status"] != "APPROVED"
                    or not item["identity_confirmed"]
                    or item["acquisition_cost_minor"] is None
                    or item["storage_location_id"] is None
                    or item["store_price_minor"] is None
                ):
                    unavailable += 1
                    continue
                eligible.append(
                    {
                        "membership_id": member["id"],
                        "inventory_id": item["id"],
                        "inventory_code": item["inventory_code"],
                        "owner_id": owner_id,
                        "owner_context_user_id": context_user_id,
                        "minimum_sale_price_minor": member["minimum_sale_price_minor"],
                        "allocation_priority": member["allocation_priority"],
                        "eligible_since": member["eligible_since"],
                        "inventory_version": item["version"],
                        "acquisition_cost_minor": item["acquisition_cost_minor"],
                    }
                )
    finally:
        if caller_user_id:
            await _set_user_context(connection, caller_user_id)

    eligible.sort(
        key=lambda row: (
            int(row["allocation_priority"]),
            row["eligible_since"],
            str(row["inventory_id"]),
        )
    )
    return {
        "eligible": eligible,
        "eligible_quantity": len(eligible),
        "price_floor_blocked_quantity": ineligible_price,
        "unavailable_quantity": unavailable,
        "member_quantity": len(members),
    }


async def reserve_listing_units(
    connection: asyncpg.Connection,
    *,
    listing_id: UUID,
    quantity: int,
    source: str,
    source_reference: str,
    source_line_reference: str,
    notes: str = "",
    expires_at: datetime | None = None,
) -> list[dict[str, object]]:
    listing = await connection.fetchrow(
        """
        select id,managed_by_owner_id,store_price_minor,status,pooling_mode
        from tcg.sellable_listings
        where id=$1
        for update
        """,
        listing_id,
    )
    if listing is None:
        raise HTTPException(status_code=404, detail="Sellable listing not found")
    if listing["status"] != "ACTIVE":
        raise HTTPException(status_code=409, detail="Only ACTIVE listings can reserve stock")

    existing = await connection.fetch(
        """
        select *
        from tcg.inventory_reservations
        where source=$1 and source_reference=$2 and source_line_reference=$3
        order by allocation_index
        """,
        source,
        source_reference,
        source_line_reference,
    )
    if existing:
        if (
            len(existing) != quantity
            or any(row["listing_id"] != listing_id for row in existing)
            or any(
                int(row["sale_price_minor_snapshot"]) != int(listing["store_price_minor"])
                for row in existing
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="Reservation idempotency key already exists with different parameters",
            )
        return [dict(row) for row in existing]

    caller_user_id = await connection.fetchval(
        "select nullif(current_setting('tcg.user_id',true),'')"
    )
    candidates = await connection.fetch(
        """
        select
          id,inventory_id,owner_id,owner_context_user_id,
          minimum_sale_price_minor,allocation_priority,eligible_since
        from tcg.listing_inventory_members
        where listing_id=$1
          and state='ACTIVE'
          and minimum_sale_price_minor <= $2
        order by allocation_priority,eligible_since,inventory_id
        """,
        listing_id,
        listing["store_price_minor"],
    )

    selected: list[dict[str, object]] = []
    try:
        for candidate in candidates:
            if len(selected) >= quantity:
                break
            await _set_user_context(connection, candidate["owner_context_user_id"])
            item = await connection.fetchrow(
                """
                select
                  id,inventory_code,owner_id,status,identity_confirmed,
                  acquisition_cost_minor,storage_location_id,store_price_minor,version
                from tcg.inventory_items
                where id=$1 and owner_id=$2
                for update skip locked
                """,
                candidate["inventory_id"],
                candidate["owner_id"],
            )
            if (
                item is None
                or item["status"] != "APPROVED"
                or not item["identity_confirmed"]
                or item["acquisition_cost_minor"] is None
                or item["storage_location_id"] is None
                or item["store_price_minor"] is None
            ):
                continue

            active = await connection.fetchval(
                """
                select exists(
                  select 1
                  from tcg.inventory_reservations
                  where inventory_id=$1 and status='ACTIVE'
                )
                """,
                item["id"],
            )
            if active:
                continue

            await connection.execute(
                "select set_config('tcg.allow_reserved_transition','on',true)"
            )
            reserved = await connection.fetchrow(
                """
                update tcg.inventory_items
                set status='RESERVED',version=version+1,updated_at=now()
                where id=$1 and owner_id=$2 and status='APPROVED' and version=$3
                returning id,inventory_code,status,version
                """,
                item["id"],
                candidate["owner_id"],
                item["version"],
            )
            if reserved is None:
                continue

            allocation_index = len(selected) + 1
            reservation = await connection.fetchrow(
                """
                insert into tcg.inventory_reservations(
                  reservation_code,listing_id,inventory_id,owner_id,
                  owner_context_user_id,source,source_reference,source_line_reference,
                  allocation_index,status,sale_price_minor_snapshot,
                  acquisition_cost_minor_snapshot,minimum_sale_price_minor_snapshot,
                  allocation_priority_snapshot,inventory_version_snapshot,
                  expires_at,notes
                ) values(
                  $1,$2,$3,$4,$5,$6,$7,$8,$9,'ACTIVE',$10,$11,$12,$13,$14,$15,$16
                )
                returning *
                """,
                f"RSV-{uuid4().hex[:12].upper()}",
                listing_id,
                item["id"],
                candidate["owner_id"],
                candidate["owner_context_user_id"],
                source,
                source_reference,
                source_line_reference,
                allocation_index,
                listing["store_price_minor"],
                item["acquisition_cost_minor"],
                candidate["minimum_sale_price_minor"],
                candidate["allocation_priority"],
                item["version"],
                expires_at,
                notes,
            )
            selected.append(dict(reservation))
    finally:
        if caller_user_id:
            await _set_user_context(connection, caller_user_id)

    if len(selected) != quantity:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Not enough eligible physical inventory is available",
                "requested_quantity": quantity,
                "allocated_quantity": len(selected),
            },
        )
    return selected


async def transition_reservation(
    connection: asyncpg.Connection,
    *,
    reservation_id: UUID,
    target: Literal["RELEASED", "CONSUMED"],
    notes: str,
) -> dict[str, object]:
    caller_user_id = await connection.fetchval(
        "select nullif(current_setting('tcg.user_id',true),'')"
    )
    reservation = await connection.fetchrow(
        """
        select r.*,l.managed_by_owner_id
        from tcg.inventory_reservations r
        join tcg.sellable_listings l on l.id=r.listing_id
        where r.id=$1
        for update of r
        """,
        reservation_id,
    )
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation["status"] == target:
        return {"reservation": dict(reservation), "inventory": None}
    if reservation["status"] != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail=f"Reservation is already {reservation['status']}",
        )

    try:
        await _set_user_context(connection, reservation["owner_context_user_id"])
        item = await connection.fetchrow(
            """
            select id,owner_id,status,version
            from tcg.inventory_items
            where id=$1 and owner_id=$2
            for update
            """,
            reservation["inventory_id"],
            reservation["owner_id"],
        )
        if item is None or item["status"] != "RESERVED":
            raise HTTPException(
                status_code=409,
                detail="Reserved physical inventory is no longer in the expected state",
            )
        await connection.execute(
            "select set_config('tcg.allow_reserved_transition','on',true)"
        )
        next_inventory_status = "APPROVED" if target == "RELEASED" else "SOLD"
        updated_item = await connection.fetchrow(
            """
            update tcg.inventory_items
            set status=$3,version=version+1,updated_at=now()
            where id=$1 and owner_id=$2 and status='RESERVED' and version=$4
            returning id,inventory_code,status,version
            """,
            item["id"],
            item["owner_id"],
            next_inventory_status,
            item["version"],
        )
        if updated_item is None:
            raise HTTPException(
                status_code=409,
                detail="Physical inventory changed during reservation transition",
            )

        timestamp_column = "released_at" if target == "RELEASED" else "consumed_at"
        updated_reservation = await connection.fetchrow(
            f"""
            update tcg.inventory_reservations
            set status=$2,{timestamp_column}=clock_timestamp(),
                notes=case when $3='' then notes else $3 end
            where id=$1 and status='ACTIVE'
            returning *
            """,
            reservation_id,
            target,
            notes,
        )
        if updated_reservation is None:
            raise HTTPException(
                status_code=409,
                detail="Reservation changed during transition",
            )
        return {
            "reservation": dict(updated_reservation),
            "inventory": dict(updated_item),
        }
    finally:
        if caller_user_id:
            await _set_user_context(connection, caller_user_id)


@router.get("/listings")
async def list_sellable_listings(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _require_founder(connection)
        rows = await connection.fetch(
            """
            select distinct
              l.*,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity
            from tcg.sellable_listings l
            join tcg.catalogue_products p on p.id=l.catalogue_id
            join tcg.listing_inventory_members m on m.listing_id=l.id
            where m.owner_id=$1 and m.state <> 'REMOVED'
            order by l.updated_at desc,l.listing_code
            limit $2 offset $3
            """,
            owner["id"],
            limit,
            offset,
        )
        items = []
        for row in rows:
            pool = await pool_state(
                connection,
                listing_id=row["id"],
                sale_price_minor=int(row["store_price_minor"]),
            )
            own = await connection.fetchrow(
                """
                select
                  count(*) filter(where state='ACTIVE')::int as active,
                  count(*) filter(where state='PAUSED')::int as paused
                from tcg.listing_inventory_members
                where listing_id=$1 and owner_id=$2
                """,
                row["id"],
                owner["id"],
            )
            item = dict(row)
            item["pool"] = {
                "eligible_quantity": pool["eligible_quantity"],
                "price_floor_blocked_quantity": pool["price_floor_blocked_quantity"],
                "unavailable_quantity": pool["unavailable_quantity"],
                "member_quantity": pool["member_quantity"],
            }
            item["my_membership"] = dict(own)
            items.append(item)
        total = await connection.fetchval(
            """
            select count(distinct l.id)
            from tcg.sellable_listings l
            join tcg.listing_inventory_members m on m.listing_id=l.id
            where m.owner_id=$1 and m.state <> 'REMOVED'
            """,
            owner["id"],
        )
        return jsonable_encoder({
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": items,
        })


@router.post("/listings/from-inventory/{inventory_id}", status_code=201)
async def create_or_join_listing(
    inventory_id: UUID,
    payload: ListingFromInventoryCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _require_founder(connection)
        item = await connection.fetchrow(
            """
            select
              i.*,p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,
              p.rarity,p.language as catalogue_language
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            where i.id=$1 and i.owner_id=$2
            for update of i
            """,
            inventory_id,
            owner["id"],
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        if item["version"] != payload.version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Inventory item changed",
                    "current_version": item["version"],
                },
            )
        missing = []
        if item["status"] != "APPROVED":
            missing.append("APPROVED status")
        if not item["identity_confirmed"]:
            missing.append("identity confirmation")
        if item["acquisition_cost_minor"] is None:
            missing.append("acquisition cost")
        if item["storage_location_id"] is None:
            missing.append("registered storage location")
        if item["store_price_minor"] is None:
            missing.append("store price")
        if missing:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Inventory is not eligible for a sellable listing",
                    "missing": missing,
                },
            )

        existing_membership = await connection.fetchrow(
            """
            select m.*,l.listing_code,l.status as listing_status,
                   l.store_price_minor as listing_price_minor
            from tcg.listing_inventory_members m
            join tcg.sellable_listings l on l.id=m.listing_id
            where m.inventory_id=$1 and m.state <> 'REMOVED'
            """,
            inventory_id,
        )
        if existing_membership is not None:
            return jsonable_encoder({
                "status": "ALREADY_LISTED",
                "membership": dict(existing_membership),
            })

        shape = listing_shape(item)
        listing = await connection.fetchrow(
            """
            select *
            from tcg.sellable_listings
            where listing_fingerprint=$1
            for update
            """,
            shape["fingerprint"],
        )
        created = False
        if listing is None:
            listing = await connection.fetchrow(
                """
                insert into tcg.sellable_listings(
                  listing_code,catalogue_id,managed_by_owner_id,created_by_user_id,
                  listing_fingerprint,product_type,pooling_mode,language,condition,
                  grading_company,grade,seal_status,currency,store_price_minor,status
                ) values(
                  $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'GBP',$13,'ACTIVE'
                )
                returning *
                """,
                f"LST-{uuid4().hex[:12].upper()}",
                item["catalogue_id"],
                owner["id"],
                user.user_id,
                shape["fingerprint"],
                shape["product_type"],
                shape["pooling_mode"],
                shape["language"],
                shape["condition"],
                shape["grading_company"],
                shape["grade"],
                shape["seal_status"],
                item["store_price_minor"],
            )
            created = True
        elif listing["pooling_mode"] == "UNIQUE":
            raise HTTPException(
                status_code=409,
                detail="Unique listings cannot accept another physical inventory item",
            )

        minimum = (
            payload.minimum_sale_price_minor
            if payload.minimum_sale_price_minor is not None
            else int(item["store_price_minor"])
        )
        membership = await connection.fetchrow(
            """
            insert into tcg.listing_inventory_members(
              listing_id,inventory_id,owner_id,owner_context_user_id,
              minimum_sale_price_minor,allocation_priority,state
            ) values($1,$2,$3,$4,$5,100,'ACTIVE')
            returning *
            """,
            listing["id"],
            inventory_id,
            owner["id"],
            user.user_id,
            minimum,
        )
        pool = await pool_state(
            connection,
            listing_id=listing["id"],
            sale_price_minor=int(listing["store_price_minor"]),
        )
        return jsonable_encoder({
            "status": "CREATED" if created else "JOINED_POOL",
            "listing": dict(listing),
            "membership": dict(membership),
            "eligible_now": int(listing["store_price_minor"]) >= minimum,
            "pool": {
                "eligible_quantity": pool["eligible_quantity"],
                "price_floor_blocked_quantity": pool["price_floor_blocked_quantity"],
                "unavailable_quantity": pool["unavailable_quantity"],
                "member_quantity": pool["member_quantity"],
            },
        })


@router.patch("/listings/{listing_id}")
async def update_listing(
    listing_id: UUID,
    payload: ListingPatch,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    values = payload.model_dump(exclude_unset=True)
    version = values.pop("version")
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _require_founder(connection)
        listing = await connection.fetchrow(
            """
            select *
            from tcg.sellable_listings
            where id=$1 and managed_by_owner_id=$2
            for update
            """,
            listing_id,
            owner["id"],
        )
        if listing is None:
            raise HTTPException(status_code=404, detail="Managed sellable listing not found")
        if listing["version"] != version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Listing changed",
                    "current_version": listing["version"],
                },
            )
        assignments = []
        params: list[object] = [listing_id, owner["id"], version]
        for column, value in values.items():
            params.append(value)
            assignments.append(f"{column}=$" + str(len(params)))
        assignments.extend(["version=version+1", "updated_at=now()"])
        row = await connection.fetchrow(
            f"""
            update tcg.sellable_listings
            set {','.join(assignments)}
            where id=$1 and managed_by_owner_id=$2 and version=$3
            returning *
            """,
            *params,
        )
        return jsonable_encoder(dict(row))


@router.patch("/listings/{listing_id}/inventory/{inventory_id}")
async def update_my_listing_membership(
    listing_id: UUID,
    inventory_id: UUID,
    payload: ListingMemberPatch,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    values = payload.model_dump(exclude_unset=True)
    version = values.pop("version")

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _require_founder(connection)
        membership = await connection.fetchrow(
            """
            select *
            from tcg.listing_inventory_members
            where listing_id=$1 and inventory_id=$2 and owner_id=$3
            for update
            """,
            listing_id,
            inventory_id,
            owner["id"],
        )
        if membership is None:
            raise HTTPException(status_code=404, detail="Listing membership not found")
        if membership["version"] != version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Listing membership changed",
                    "current_version": membership["version"],
                },
            )
        if values.get("state") == "REMOVED":
            has_active = await connection.fetchval(
                """
                select exists(
                  select 1 from tcg.inventory_reservations
                  where inventory_id=$1 and status='ACTIVE'
                )
                """,
                inventory_id,
            )
            if has_active:
                raise HTTPException(
                    status_code=409,
                    detail="Reserved inventory cannot be removed from its listing",
                )

        assignments = []
        params: list[object] = [membership["id"], owner["id"], version]
        for column, value in values.items():
            params.append(value)
            assignments.append(f"{column}=$" + str(len(params)))
        assignments.extend(["version=version+1", "updated_at=clock_timestamp()"])
        row = await connection.fetchrow(
            f"""
            update tcg.listing_inventory_members
            set {','.join(assignments)}
            where id=$1 and owner_id=$2 and version=$3
            returning *
            """,
            *params,
        )
        return jsonable_encoder(dict(row))


@router.post("/listings/{listing_id}/test-reservations", status_code=201)
async def create_test_reservation(
    listing_id: UUID,
    payload: TestReservationCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=payload.expires_in_minutes)
        if payload.expires_in_minutes is not None
        else None
    )
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _require_founder(connection)
        managed = await connection.fetchval(
            """
            select exists(
              select 1 from tcg.sellable_listings
              where id=$1 and managed_by_owner_id=$2
            )
            """,
            listing_id,
            owner["id"],
        )
        if not managed:
            raise HTTPException(status_code=404, detail="Managed sellable listing not found")
        reservations = await reserve_listing_units(
            connection,
            listing_id=listing_id,
            quantity=payload.quantity,
            source="TEST",
            source_reference=payload.reference,
            source_line_reference=payload.line_reference,
            notes=payload.notes,
            expires_at=expires_at,
        )
        return jsonable_encoder({
            "status": "RESERVED",
            "quantity": len(reservations),
            "reservations": reservations,
        })


@router.post("/reservations/{reservation_id}/release")
async def release_test_reservation(
    reservation_id: UUID,
    payload: ReservationAction,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _require_founder(connection)
        managed = await connection.fetchval(
            """
            select exists(
              select 1
              from tcg.inventory_reservations r
              join tcg.sellable_listings l on l.id=r.listing_id
              where r.id=$1 and l.managed_by_owner_id=$2 and r.source='TEST'
            )
            """,
            reservation_id,
            owner["id"],
        )
        if not managed:
            raise HTTPException(status_code=404, detail="Managed test reservation not found")
        result = await transition_reservation(
            connection,
            reservation_id=reservation_id,
            target="RELEASED",
            notes=payload.notes,
        )
        return jsonable_encoder(result)


@router.post("/reservations/{reservation_id}/consume")
async def consume_test_reservation(
    reservation_id: UUID,
    payload: ReservationAction,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _require_founder(connection)
        managed = await connection.fetchval(
            """
            select exists(
              select 1
              from tcg.inventory_reservations r
              join tcg.sellable_listings l on l.id=r.listing_id
              where r.id=$1 and l.managed_by_owner_id=$2 and r.source='TEST'
            )
            """,
            reservation_id,
            owner["id"],
        )
        if not managed:
            raise HTTPException(status_code=404, detail="Managed test reservation not found")
        result = await transition_reservation(
            connection,
            reservation_id=reservation_id,
            target="CONSUMED",
            notes=payload.notes,
        )
        return jsonable_encoder(result)
