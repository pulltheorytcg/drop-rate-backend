from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner


router = APIRouter(prefix="/api/v1/action-required", tags=["action-required"])


class ActionRequiredDecision(BaseModel):
    version: int = Field(ge=1)
    decision: str = Field(pattern="^(RESOLVE|DISMISS)$")


async def upsert_action_required(
    connection,
    *,
    owner_id: UUID,
    category: str,
    code: str,
    entity_type: str,
    entity_id: UUID,
    dedupe_key: str,
    title: str,
    detail: str,
    recommended_action: str,
    severity: str = "MEDIUM",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = await connection.fetchrow(
        """
        insert into tcg.action_required_items(
            owner_id,category,code,severity,entity_type,entity_id,dedupe_key,
            title,detail,recommended_action,status,metadata
        ) values(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'OPEN',$11::jsonb
        )
        on conflict(owner_id,dedupe_key)
        do update set
            category=excluded.category,
            code=excluded.code,
            severity=excluded.severity,
            entity_type=excluded.entity_type,
            entity_id=excluded.entity_id,
            title=excluded.title,
            detail=excluded.detail,
            recommended_action=excluded.recommended_action,
            status='OPEN',
            metadata=excluded.metadata,
            last_seen_at=clock_timestamp(),
            resolved_at=null,
            resolved_by_user_id=null,
            updated_at=clock_timestamp(),
            version=tcg.action_required_items.version+1
        returning *
        """,
        owner_id,
        category,
        code,
        severity,
        entity_type,
        entity_id,
        dedupe_key,
        title,
        detail,
        recommended_action,
        json.dumps(metadata or {}),
    )
    return dict(row)


async def resolve_action_required(
    connection,
    *,
    owner_id: UUID,
    dedupe_key: str,
    actor_user_id: UUID,
    status: str = "RESOLVED",
) -> dict[str, Any] | None:
    if status not in {"RESOLVED", "DISMISSED"}:
        raise ValueError("Unsupported action-required resolution status")
    row = await connection.fetchrow(
        """
        update tcg.action_required_items
        set status=$4,
            resolved_at=clock_timestamp(),
            resolved_by_user_id=$3,
            updated_at=clock_timestamp(),
            version=version+1
        where owner_id=$1
          and dedupe_key=$2
          and status='OPEN'
        returning *
        """,
        owner_id,
        dedupe_key,
        actor_user_id,
        status,
    )
    return dict(row) if row is not None else None


@router.get("")
async def list_action_required(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    category: str | None = Query(default=None, max_length=40),
    status: str = Query(default="OPEN", max_length=20),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    status_value = status.strip().upper()
    if status_value not in {"OPEN", "RESOLVED", "DISMISSED", "ALL"}:
        raise HTTPException(status_code=422, detail="Unsupported Action Required status")
    category_value = (category or "").strip().upper()

    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        params: list[object] = [owner["id"]]
        filters = ["owner_id=$1"]
        if status_value != "ALL":
            params.append(status_value)
            filters.append(f"status=${len(params)}")
        if category_value:
            params.append(category_value)
            filters.append(f"category=${len(params)}")
        where = " and ".join(filters)
        total = await connection.fetchval(
            f"select count(*)::int from tcg.action_required_items where {where}",
            *params,
        )
        params.extend([limit, offset])
        rows = await connection.fetch(
            f"""
            select id,category,code,severity,entity_type,entity_id,dedupe_key,
                   title,detail,recommended_action,status,metadata,first_seen_at,
                   last_seen_at,resolved_at,version
            from tcg.action_required_items
            where {where}
            order by
              case severity
                when 'CRITICAL' then 0
                when 'HIGH' then 1
                when 'MEDIUM' then 2
                else 3
              end,
              last_seen_at desc,
              id
            limit ${len(params)-1} offset ${len(params)}
            """,
            *params,
        )

    return jsonable_encoder(
        {
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
        }
    )


@router.get("/summary")
async def action_required_summary(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        rows = await connection.fetch(
            """
            select category,severity,count(*)::int as count
            from tcg.action_required_items
            where owner_id=$1 and status='OPEN'
            group by category,severity
            order by category,severity
            """,
            owner["id"],
        )
    return jsonable_encoder({"items": [dict(row) for row in rows]})


@router.post("/{item_id}/decision")
async def action_required_decision(
    item_id: UUID,
    payload: ActionRequiredDecision,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        owner = await _owner(connection)
        status = "RESOLVED" if payload.decision == "RESOLVE" else "DISMISSED"
        row = await connection.fetchrow(
            """
            update tcg.action_required_items
            set status=$5,
                resolved_at=clock_timestamp(),
                resolved_by_user_id=$3,
                updated_at=clock_timestamp(),
                version=version+1
            where id=$1
              and owner_id=$2
              and version=$4
              and status='OPEN'
            returning *
            """,
            item_id,
            owner["id"],
            user.user_id,
            payload.version,
            status,
        )
        if row is None:
            current = await connection.fetchrow(
                "select id,status,version from tcg.action_required_items where id=$1 and owner_id=$2",
                item_id,
                owner["id"],
            )
            if current is None:
                raise HTTPException(status_code=404, detail="Action Required item not found")
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Action Required item changed",
                    "status": current["status"],
                    "version": current["version"],
                },
            )
    return jsonable_encoder({"item": dict(row)})
