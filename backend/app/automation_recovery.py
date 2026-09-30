from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .access_control import require_platform_admin
from .auth import AuthenticatedUser, require_user
from .db import user_connection


router = APIRouter(
    prefix="/api/v1/automation/recovery",
    tags=["automation-recovery"],
)


class AutomationReplayRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)

    @model_validator(mode="after")
    def normalize_reason(self) -> "AutomationReplayRequest":
        self.reason = " ".join(self.reason.strip().split())
        if len(self.reason) < 8:
            raise ValueError("Replay reason must contain at least 8 characters")
        return self


@router.get("/dead-letters")
async def list_dead_letters(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await require_platform_admin(connection)
        rows = await connection.fetch(
            "select * from tcg.list_automation_dead_letters($1,$2)",
            limit,
            offset,
        )
    return jsonable_encoder(
        {
            "items": [dict(row) for row in rows],
            "limit": limit,
            "offset": offset,
        }
    )


@router.post("/dead-letters/{event_id}/replay")
async def replay_dead_letter(
    event_id: UUID,
    payload: AutomationReplayRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict:
    async with user_connection(
        request.app.state.db_pool,
        user.user_id,
        request.state.request_id,
    ) as connection:
        await require_platform_admin(connection)
        try:
            result = await connection.fetchval(
                """
                select tcg.replay_dead_letter_automation_event($1,$2,$3,$4)
                """,
                event_id,
                user.user_id,
                payload.reason,
                request.state.request_id,
            )
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            if sqlstate == "P0002":
                raise HTTPException(
                    status_code=404,
                    detail="Automation event not found",
                ) from exc
            if sqlstate == "55000":
                raise HTTPException(
                    status_code=409,
                    detail="Only dead-letter automation events may be replayed",
                ) from exc
            if sqlstate == "42501":
                raise HTTPException(
                    status_code=403,
                    detail="Platform administrator access required",
                ) from exc
            raise

    if result is None:
        raise HTTPException(status_code=500, detail="Automation replay returned no result")
    return jsonable_encoder({"replay": result})
