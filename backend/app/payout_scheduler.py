from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import asyncpg

LONDON = ZoneInfo("Europe/London")
SCHEDULE_TIME = time(hour=9)
Cadence = Literal["DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY"]


@dataclass(frozen=True)
class SchedulerCandidate:
    owner_id: Any
    owner_type: str
    owner_active: bool
    cadence: Cadence
    weekday: int | None
    monthly_day: int | None
    fortnightly_anchor_date: date | None
    timezone: str
    preference_version: int
    stripe_ready: bool
    available_to_withdraw_minor: int


def _monthly_date(year: int, month: int, requested_day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(requested_day, last_day))


def latest_due_at(
    *,
    cadence: Cadence,
    weekday: int | None,
    monthly_day: int | None,
    fortnightly_anchor_date: date | None,
    now: datetime,
) -> datetime:
    current = now.astimezone(LONDON)

    if cadence == "DAILY":
        candidate = datetime.combine(current.date(), SCHEDULE_TIME, tzinfo=LONDON)
        if candidate > current:
            candidate -= timedelta(days=1)
        return candidate

    if cadence == "WEEKLY":
        if weekday is None:
            raise ValueError("Weekly payout schedule requires weekday")
        days_back = (current.weekday() - weekday) % 7
        target = current.date() - timedelta(days=days_back)
        candidate = datetime.combine(target, SCHEDULE_TIME, tzinfo=LONDON)
        if candidate > current:
            candidate -= timedelta(days=7)
        return candidate

    if cadence == "FORTNIGHTLY":
        if weekday is None or fortnightly_anchor_date is None:
            raise ValueError("Fortnightly payout schedule requires weekday and anchor date")
        anchor = datetime.combine(
            fortnightly_anchor_date,
            SCHEDULE_TIME,
            tzinfo=LONDON,
        )
        if current < anchor:
            return anchor
        elapsed_days = (current.date() - fortnightly_anchor_date).days
        cycles = elapsed_days // 14
        candidate = anchor + timedelta(days=cycles * 14)
        if candidate > current:
            candidate -= timedelta(days=14)
        return candidate

    if cadence == "MONTHLY":
        if monthly_day is None:
            raise ValueError("Monthly payout schedule requires monthly day")
        target = _monthly_date(current.year, current.month, monthly_day)
        candidate = datetime.combine(target, SCHEDULE_TIME, tzinfo=LONDON)
        if candidate <= current:
            return candidate
        if current.month == 1:
            target = _monthly_date(current.year - 1, 12, monthly_day)
        else:
            target = _monthly_date(current.year, current.month - 1, monthly_day)
        return datetime.combine(target, SCHEDULE_TIME, tzinfo=LONDON)

    raise ValueError("Unsupported payout cadence")


def cycle_key(scheduled_for: datetime) -> str:
    local = scheduled_for.astimezone(LONDON)
    return f"payout-cycle:{local.isoformat()}"


async def load_candidates(connection: asyncpg.Connection) -> list[SchedulerCandidate]:
    rows = await connection.fetch("select * from tcg.payout_scheduler_candidates()")
    candidates: list[SchedulerCandidate] = []
    for row in rows:
        candidates.append(
            SchedulerCandidate(
                owner_id=row["owner_id"],
                owner_type=str(row["owner_type"]),
                owner_active=bool(row["owner_active"]),
                cadence=str(row["cadence"]),  # type: ignore[arg-type]
                weekday=row["weekday"],
                monthly_day=row["monthly_day"],
                fortnightly_anchor_date=row["fortnightly_anchor_date"],
                timezone=str(row["timezone"]),
                preference_version=int(row["preference_version"]),
                stripe_ready=bool(row["stripe_ready"]),
                available_to_withdraw_minor=int(row["available_to_withdraw_minor"] or 0),
            )
        )
    return candidates


async def queue_due_payouts(
    connection: asyncpg.Connection,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(LONDON)).astimezone(LONDON)
    candidates = await load_candidates(connection)

    summary: dict[str, Any] = {
        "checked": len(candidates),
        "created": 0,
        "duplicate": 0,
        "no_balance": 0,
        "stripe_not_ready": 0,
        "owner_inactive": 0,
        "preference_changed": 0,
        "not_yet_due": 0,
        "errors": [],
        "payouts": [],
    }

    for candidate in candidates:
        if candidate.timezone != "Europe/London":
            summary["errors"].append(
                {
                    "owner_id": str(candidate.owner_id),
                    "code": "UNSUPPORTED_TIMEZONE",
                }
            )
            continue
        if not candidate.owner_active:
            summary["owner_inactive"] += 1
            continue
        if not candidate.stripe_ready:
            summary["stripe_not_ready"] += 1
            continue
        if candidate.available_to_withdraw_minor <= 0:
            summary["no_balance"] += 1
            continue

        scheduled_for = latest_due_at(
            cadence=candidate.cadence,
            weekday=candidate.weekday,
            monthly_day=candidate.monthly_day,
            fortnightly_anchor_date=candidate.fortnightly_anchor_date,
            now=current,
        )
        if scheduled_for > current:
            summary["not_yet_due"] += 1
            continue

        key = cycle_key(scheduled_for)
        try:
            row = await connection.fetchrow(
                """
                select *
                from tcg.create_scheduled_payout_request($1,$2,$3,$4,$5)
                """,
                candidate.owner_id,
                candidate.preference_version,
                key,
                scheduled_for,
                candidate.cadence,
            )
        except Exception as exc:
            summary["errors"].append(
                {
                    "owner_id": str(candidate.owner_id),
                    "code": type(exc).__name__,
                }
            )
            continue

        if row is None:
            summary["errors"].append(
                {
                    "owner_id": str(candidate.owner_id),
                    "code": "EMPTY_CREATE_RESULT",
                }
            )
            continue

        reason = str(row["reason"])
        if bool(row["created"]):
            summary["created"] += 1
            summary["payouts"].append(
                {
                    "owner_id": str(candidate.owner_id),
                    "payout_request_id": str(row["payout_request_id"]),
                    "payout_code": row["payout_code"],
                    "amount_minor": int(row["amount_minor"] or 0),
                    "scheduled_for": scheduled_for.isoformat(),
                }
            )
        elif reason == "DUPLICATE_CYCLE":
            summary["duplicate"] += 1
        elif reason == "NO_AVAILABLE_BALANCE":
            summary["no_balance"] += 1
        elif reason == "STRIPE_NOT_READY":
            summary["stripe_not_ready"] += 1
        elif reason == "OWNER_INACTIVE":
            summary["owner_inactive"] += 1
        elif reason == "PREFERENCE_CHANGED":
            summary["preference_changed"] += 1
        else:
            summary["errors"].append(
                {
                    "owner_id": str(candidate.owner_id),
                    "code": reason,
                }
            )

    summary["ok"] = not summary["errors"]
    summary["run_at"] = current.isoformat()
    return summary


async def check_scheduler_heartbeat(
    connection: asyncpg.Connection,
    *,
    threshold: timedelta = timedelta(minutes=90),
) -> dict[str, Any]:
    """Check the independent scheduler heartbeat and maintain the founder alert."""
    if threshold < timedelta(minutes=30):
        raise ValueError("Payout scheduler heartbeat threshold must be at least 30 minutes")

    row = await connection.fetchrow(
        "select * from tcg.check_payout_scheduler_heartbeat($1::interval)",
        threshold,
    )
    if row is None:
        raise RuntimeError("Payout scheduler heartbeat check returned no result")

    return {
        "healthy": bool(row["healthy"]),
        "last_completed_at": row["last_completed_at"],
        "last_status": row["last_status"],
        "alerted_founders": int(row["alerted_founders"] or 0),
        "resolved_founders": int(row["resolved_founders"] or 0),
    }
