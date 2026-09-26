from __future__ import annotations

from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner


router = APIRouter(prefix="/api/v1/condition-review", tags=["condition-review"])

RAW_CONDITIONS = {
    "Near Mint",
    "Lightly Played",
    "Moderately Played",
    "Heavily Played",
    "Damaged",
}


class ConditionReviewRequest(BaseModel):
    version: int = Field(ge=1)
    decision: str = Field(
        pattern="^(APPROVE_NEAR_MINT|VERIFY_GRADED|REJECT_BELOW_NEAR_MINT|NEEDS_RESHOOT)$"
    )
    observed_condition: str | None = None
    reshoot_side: str | None = Field(default=None, pattern="^(FRONT|BACK|BOTH)$")
    notes: str = Field(default="", max_length=2000)


async def _founder(connection: asyncpg.Connection) -> asyncpg.Record:
    owner = await _owner(connection)
    if owner["role"] != "FOUNDER":
        raise HTTPException(status_code=403, detail="Only a founder can review card condition")
    return owner


def _is_graded(item: asyncpg.Record | dict) -> bool:
    return bool(
        str(item.get("grading_company") or "").strip()
        and str(item.get("grade") or "").strip()
    )


async def _ready_evidence(
    connection: asyncpg.Connection,
    *,
    owner_id: UUID,
    inventory_id: UUID,
) -> dict[str, asyncpg.Record]:
    rows = await connection.fetch(
        """
        select *
        from tcg.media_assets
        where owner_id=$1
          and inventory_id=$2
          and scope='INVENTORY_ITEM'
          and side in ('FRONT','BACK')
          and approval_status='APPROVED'
          and rights_status='VERIFIED'
          and shopify_file_status='READY'
          and capture_context is not null
        order by created_at desc,id desc
        """,
        owner_id,
        inventory_id,
    )
    by_side: dict[str, asyncpg.Record] = {}
    for row in rows:
        by_side.setdefault(str(row["side"]), row)
    return by_side


@router.get("/queue")
async def condition_review_queue(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _founder(connection)
        rows = await connection.fetch(
            """
            select
                i.id,i.inventory_code,i.version,i.status,i.condition,
                i.condition_review_status,i.grading_company,i.grade,
                i.identity_confirmed,i.language,
                p.game,p.name,p.set_name,p.card_number,p.variant,
                front.id as front_asset_id,
                front.capture_context as front_capture_context,
                front.shopify_cdn_url as front_image_url,
                back.id as back_asset_id,
                back.capture_context as back_capture_context,
                back.shopify_cdn_url as back_image_url
            from tcg.inventory_items i
            join tcg.catalogue_products p on p.id=i.catalogue_id
            left join lateral (
                select m.id,m.capture_context,m.shopify_cdn_url
                from tcg.media_assets m
                where m.owner_id=i.owner_id
                  and m.inventory_id=i.id
                  and m.scope='INVENTORY_ITEM'
                  and m.side='FRONT'
                  and m.approval_status='APPROVED'
                  and m.rights_status='VERIFIED'
                  and m.shopify_file_status='READY'
                  and m.capture_context is not null
                order by m.created_at desc,m.id desc
                limit 1
            ) front on true
            left join lateral (
                select m.id,m.capture_context,m.shopify_cdn_url
                from tcg.media_assets m
                where m.owner_id=i.owner_id
                  and m.inventory_id=i.id
                  and m.scope='INVENTORY_ITEM'
                  and m.side='BACK'
                  and m.approval_status='APPROVED'
                  and m.rights_status='VERIFIED'
                  and m.shopify_file_status='READY'
                  and m.capture_context is not null
                order by m.created_at desc,m.id desc
                limit 1
            ) back on true
            where i.owner_id=$1
              and i.status in ('DRAFT','INSPECTION','APPROVED')
              and p.product_type='CARD'
            order by
              case
                when i.condition_review_status in ('VERIFIED_NEAR_MINT','VERIFIED_GRADED') then 2
                when front.id is not null and back.id is not null then 0
                else 1
              end,
              i.updated_at,
              i.inventory_code
            """,
            owner["id"],
        )

    items = []
    for source in rows:
        item = dict(source)
        graded = _is_graded(item)
        photo_ready = bool(item["front_asset_id"] and item["back_asset_id"])
        item["is_graded"] = graded
        item["photo_ready"] = photo_ready
        item["review_ready"] = photo_ready and item["condition_review_status"] not in {
            "VERIFIED_NEAR_MINT",
            "VERIFIED_GRADED",
        }
        item["sellable_condition_verified"] = item["condition_review_status"] in {
            "VERIFIED_NEAR_MINT",
            "VERIFIED_GRADED",
        }
        items.append(item)

    return jsonable_encoder({
        "items": items,
        "counts": {
            "total": len(items),
            "photo_ready": sum(1 for item in items if item["photo_ready"]),
            "needs_review": sum(1 for item in items if item["review_ready"]),
            "verified": sum(1 for item in items if item["sellable_condition_verified"]),
            "below_near_mint": sum(
                1 for item in items
                if item["condition_review_status"] == "REJECTED_BELOW_NEAR_MINT"
            ),
        },
        "policy": {
            "raw_sellable_condition": "Near Mint",
            "graded_uses_slab_verification": True,
            "ai_can_suggest_but_not_override": True,
        },
    })


@router.post("/{inventory_id}")
async def review_condition(
    inventory_id: UUID,
    payload: ConditionReviewRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool, user.user_id, request.state.request_id
    ) as connection:
        owner = await _founder(connection)
        async with connection.transaction():
            item = await connection.fetchrow(
                """
                select i.*,p.product_type
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
            if item["product_type"] != "CARD":
                raise HTTPException(status_code=422, detail="Condition review is only for cards")
            if item["version"] != payload.version:
                raise HTTPException(
                    status_code=409,
                    detail={"message": "Inventory item changed", "current_version": item["version"]},
                )

            evidence = await _ready_evidence(
                connection,
                owner_id=owner["id"],
                inventory_id=inventory_id,
            )
            front = evidence.get("FRONT")
            back = evidence.get("BACK")
            if front is None or back is None:
                raise HTTPException(
                    status_code=422,
                    detail="Ready physical-item FRONT and BACK photos are required before condition review",
                )

            graded = _is_graded(item)
            observed = (payload.observed_condition or "").strip() or None
            notes = payload.notes.strip()

            if payload.decision == "APPROVE_NEAR_MINT":
                if graded:
                    raise HTTPException(
                        status_code=422,
                        detail="Graded cards use slab verification, not raw Near Mint approval",
                    )
                if observed not in {None, "Near Mint"}:
                    raise HTTPException(
                        status_code=422,
                        detail="Near Mint approval cannot record a lower observed condition",
                    )
                observed = "Near Mint"
                status = "VERIFIED_NEAR_MINT"
                condition = "Near Mint"
                verified_at = True
            elif payload.decision == "VERIFY_GRADED":
                if not graded:
                    raise HTTPException(
                        status_code=422,
                        detail="Only graded inventory can use graded slab verification",
                    )
                observed = None
                status = "VERIFIED_GRADED"
                condition = None
                verified_at = True
            elif payload.decision == "REJECT_BELOW_NEAR_MINT":
                if graded:
                    raise HTTPException(
                        status_code=422,
                        detail="Use graded slab verification for graded inventory",
                    )
                if observed not in RAW_CONDITIONS - {"Near Mint"}:
                    raise HTTPException(
                        status_code=422,
                        detail="Choose the observed below-Near-Mint condition",
                    )
                status = "REJECTED_BELOW_NEAR_MINT"
                condition = observed
                verified_at = False
            else:
                side = payload.reshoot_side or "BOTH"
                targets = ["FRONT", "BACK"] if side == "BOTH" else [side]
                asset_ids = [
                    evidence[target]["id"]
                    for target in targets
                    if evidence.get(target) is not None
                ]
                await connection.execute(
                    """
                    update tcg.media_assets
                    set approval_status='REJECTED',
                        updated_at=clock_timestamp(),
                        version=version+1
                    where owner_id=$1 and id=any($2::uuid[])
                    """,
                    owner["id"],
                    asset_ids,
                )
                status = "NEEDS_RESHOOT"
                condition = None if not graded else item["condition"]
                verified_at = False

            row = await connection.fetchrow(
                """
                update tcg.inventory_items
                set condition=$3,
                    condition_review_status=$4,
                    condition_verified_at=case when $5 then clock_timestamp() else null end,
                    condition_verified_by_user_id=case when $5 then $6 else null end,
                    version=version+1,
                    updated_at=clock_timestamp()
                where id=$1 and owner_id=$2 and version=$7
                returning *
                """,
                inventory_id,
                owner["id"],
                condition,
                status,
                verified_at,
                user.user_id,
                payload.version,
            )
            if row is None:
                raise HTTPException(status_code=409, detail="Inventory item changed during review")

            await connection.execute(
                """
                insert into tcg.condition_review_events(
                    owner_id,inventory_id,front_media_asset_id,back_media_asset_id,
                    decision,observed_condition,reshoot_side,notes,created_by_user_id
                ) values($1,$2,$3,$4,$5,$6,$7,$8,$9)
                """,
                owner["id"],
                inventory_id,
                front["id"],
                back["id"],
                payload.decision,
                observed,
                payload.reshoot_side,
                notes,
                user.user_id,
            )

    return jsonable_encoder({
        "inventory": dict(row),
        "condition_review_status": status,
        "shopify_eligible_condition": status in {"VERIFIED_NEAR_MINT", "VERIFIED_GRADED"},
    })
