from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .ownership import current_owner as _owner


router = APIRouter(prefix="/api/v1/payout-preferences")
LONDON = ZoneInfo("Europe/London")
SCHEDULE_TIME = time(hour=9)

Cadence = Literal["MANUAL", "DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY"]


class PayoutPreferenceUpdate(BaseModel):
    cadence: Cadence
    weekday: int | None = Field(default=None, ge=0, le=6)
    monthly_day: int | None = Field(default=None, ge=1, le=31)
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_cadence_fields(self) -> "PayoutPreferenceUpdate":
        if self.cadence in {"MANUAL", "DAILY"}:
            if self.weekday is not None or self.monthly_day is not None:
                raise ValueError("Manual and daily payout schedules do not take a day selector")
        elif self.cadence in {"WEEKLY", "FORTNIGHTLY"}:
            if self.weekday is None or self.monthly_day is not None:
                raise ValueError("Weekly and fortnightly payout schedules require a weekday")
        elif self.cadence == "MONTHLY":
            if self.monthly_day is None or self.weekday is not None:
                raise ValueError("Monthly payout schedules require a day of month")
        return self


def _next_weekday(start: date, weekday: int) -> date:
    days = (weekday - start.weekday()) % 7
    if days == 0:
        days = 7
    return start + timedelta(days=days)


def _monthly_date(year: int, month: int, requested_day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(requested_day, last_day))


def next_scheduled_at(
    *,
    cadence: Cadence,
    weekday: int | None,
    monthly_day: int | None,
    fortnightly_anchor_date: date | None,
    now: datetime | None = None,
) -> datetime | None:
    current = (now or datetime.now(LONDON)).astimezone(LONDON)

    if cadence == "MANUAL":
        return None
    if cadence == "DAILY":
        target = current.date() + timedelta(days=1)
        return datetime.combine(target, SCHEDULE_TIME, tzinfo=LONDON)
    if cadence == "WEEKLY":
        if weekday is None:
            raise ValueError("Weekly payout schedule requires weekday")
        target = _next_weekday(current.date(), weekday)
        return datetime.combine(target, SCHEDULE_TIME, tzinfo=LONDON)
    if cadence == "FORTNIGHTLY":
        if weekday is None or fortnightly_anchor_date is None:
            raise ValueError("Fortnightly payout schedule requires weekday and anchor date")
        target = fortnightly_anchor_date
        while datetime.combine(target, SCHEDULE_TIME, tzinfo=LONDON) <= current:
            target += timedelta(days=14)
        return datetime.combine(target, SCHEDULE_TIME, tzinfo=LONDON)
    if cadence == "MONTHLY":
        if monthly_day is None:
            raise ValueError("Monthly payout schedule requires monthly day")
        candidate = _monthly_date(current.year, current.month, monthly_day)
        candidate_at = datetime.combine(candidate, SCHEDULE_TIME, tzinfo=LONDON)
        if candidate_at <= current:
            if current.month == 12:
                candidate = _monthly_date(current.year + 1, 1, monthly_day)
            else:
                candidate = _monthly_date(current.year, current.month + 1, monthly_day)
            candidate_at = datetime.combine(candidate, SCHEDULE_TIME, tzinfo=LONDON)
        return candidate_at
    raise ValueError("Unsupported payout cadence")


def _default_preference() -> dict:
    return {
        "cadence": "MANUAL",
        "weekday": None,
        "monthly_day": None,
        "fortnightly_anchor_date": None,
        "timezone": "Europe/London",
        "version": 0,
        "configured": False,
    }


def _serialize_preference(row: asyncpg.Record | dict | None) -> dict:
    data = dict(row) if row is not None else _default_preference()
    cadence = str(data["cadence"])
    next_at = next_scheduled_at(
        cadence=cadence,  # type: ignore[arg-type]
        weekday=data.get("weekday"),
        monthly_day=data.get("monthly_day"),
        fortnightly_anchor_date=data.get("fortnightly_anchor_date"),
    )
    data["configured"] = row is not None
    data["next_scheduled_at"] = next_at.isoformat() if next_at else None
    data["timezone"] = "Europe/London"
    return data


@router.get("")
async def get_payout_preference(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
):
    async with user_connection(
        request.app.state.db_pool, user.id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        row = await connection.fetchrow(
            "select * from tcg.payout_preferences where owner_id=$1",
            owner["id"],
        )
        return jsonable_encoder({"preference": _serialize_preference(row)})


@router.put("")
async def update_payout_preference(
    payload: PayoutPreferenceUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
):
    async with user_connection(
        request.app.state.db_pool, user.id, request.state.request_id
    ) as connection:
        owner = await _owner(connection)
        existing = await connection.fetchrow(
            "select * from tcg.payout_preferences where owner_id=$1 for update",
            owner["id"],
        )

        if existing is None:
            if payload.version != 0:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Payout preference changed; refresh and try again",
                        "current_version": 0,
                    },
                )
        elif int(existing["version"]) != payload.version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Payout preference changed; refresh and try again",
                    "current_version": int(existing["version"]),
                },
            )

        anchor: date | None = None
        if payload.cadence == "FORTNIGHTLY":
            if payload.weekday is None:
                raise HTTPException(
                    status_code=422,
                    detail="Fortnightly schedule requires weekday",
                )
            anchor = _next_weekday(datetime.now(LONDON).date(), payload.weekday)

        if existing is None:
            row = await connection.fetchrow(
                """
                insert into tcg.payout_preferences(
                    owner_id,cadence,weekday,monthly_day,fortnightly_anchor_date,
                    timezone,updated_by_user_id
                )
                values($1,$2,$3,$4,$5,'Europe/London',$6)
                returning *
                """,
                owner["id"],
                payload.cadence,
                payload.weekday,
                payload.monthly_day,
                anchor,
                user.id,
            )
        else:
            row = await connection.fetchrow(
                """
                update tcg.payout_preferences
                set cadence=$2,
                    weekday=$3,
                    monthly_day=$4,
                    fortnightly_anchor_date=$5,
                    updated_by_user_id=$6,
                    version=version+1,
                    updated_at=clock_timestamp()
                where owner_id=$1
                returning *
                """,
                owner["id"],
                payload.cadence,
                payload.weekday,
                payload.monthly_day,
                anchor,
                user.id,
            )

        if row is None:
            raise HTTPException(status_code=409, detail="Payout preference was not saved")

        return jsonable_encoder({"preference": _serialize_preference(row)})
