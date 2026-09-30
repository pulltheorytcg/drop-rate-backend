from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, require_user


router = APIRouter(
    prefix="/api/v1/automation/operations",
    tags=["automation-operations"],
)


class ReplayAutomationEventRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)


@router.get("/events")
async def list_automation_events(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    status: str | None = Query(default=None, max_length=20),
    event_type: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    del user
    async with request.app.state.db_pool.acquire() as connection:
        rows = await connection.fetch(
            """
            select *
            from tcg.list_automation_outbox_events($1,$2,$3)
            """,
            status,
            event_type,
            limit,
        )

    return jsonable_encoder(
        {
            "items": [dict(row) for row in rows],
            "count": len(rows),
            "limit": limit,
        }
    )


@router.post("/events/{event_id}/replay")
async def replay_automation_event(
    event_id: UUID,
    payload: ReplayAutomationEventRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with request.app.state.db_pool.acquire() as connection:
        result = await connection.fetchval(
            """
            select tcg.replay_dead_letter_automation_event($1,$2,$3,$4)
            """,
            event_id,
            user.user_id,
            payload.reason,
            request.state.request_id,
        )

    return jsonable_encoder({"event": result})
