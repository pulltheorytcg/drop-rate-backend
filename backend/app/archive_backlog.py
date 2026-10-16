"""Read-only alert for eligible market history surviving the daily archive window.

This does NOT archive, purge, restore or certify a Google Drive backup.
The actual 04:00 UK archival remains an independent fail-closed operation.
Only the existing authenticated catalogue worker performs this check;
no RLS bypass, extra background process or new provider credentials.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from .access_control import require_platform_admin
from .db import user_connection

LONDON = ZoneInfo("Europe/London")
FIRST_ARCHIVE_DAY = (2026, 10, 17)
ARCHIVE_HOUR = 4
GRACE_HOURS = 3

BACKLOG_SQL = """
select count(*)::bigint as pending_rows,
       min(recorded_at) as oldest_pending_at,
       max(recorded_at) as newest_pending_at
from tcg.reference_market_history
"""


def archive_check_window(now: datetime) -> datetime | None:
    """Latest eligible 04:00 UK window *after* the three-hour grace period.

    Return a UTC timestamp, independent of server timezone and BST/GMT
    transitions. No checks before the founder's first scheduled archive.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Archive check needs a timezone-aware timestamp")
    local = now.astimezone(LONDON)
    if local.hour < ARCHIVE_HOUR + GRACE_HOURS:
        date = (local - timedelta(days=1)).date()
    else:
        date = local.date()
    if (date.year, date.month, date.day) < FIRST_ARCHIVE_DAY:
        return None
    return datetime(date.year, date.month, date.day, ARCHIVE_HOUR, tzinfo=LONDON).astimezone(timezone.utc)


def assess_archive_backlog(pending_rows: int, oldest: datetime | None, window: datetime) -> dict:
    """Diagnose a stale backlog; this cannot establish Drive backup integrity."""
    if type(pending_rows) is not int or pending_rows < 0 or window.tzinfo is None:
        raise ValueError("Invalid archive checkpoint")
    if pending_rows == 0:
        if oldest is not None:
            raise ValueError("Inconsistent empty history evidence")
        return {"status": "CLEAR", "eligible_unarchived_rows": 0,
                "pending_rows": 0, "archive_window_utc": window.isoformat()}
    if oldest is None or oldest.tzinfo is None or oldest.utcoffset() is None:
        raise ValueError("Incomplete history timestamp evidence")
    pending = oldest.astimezone(timezone.utc)
    return {"status": "OVERDUE" if pending <= window else "CURRENT",
            "pending_rows": pending_rows, "oldest_pending_at": pending.isoformat(),
            "archive_window_utc": window.isoformat(),
            "note": "Backlog status only; never proof of a verified Google Drive backup"}


async def check_archive_backlog(pool, actor: UUID, window: datetime) -> dict:
    """Use existing platform-admin actor and row-level security; SELECT only."""
    async with user_connection(pool, actor, str(uuid4())) as conn:
        await require_platform_admin(conn)
        row = await conn.fetchrow(BACKLOG_SQL)
        if row is None:
            raise ValueError("Missing reference-history checkpoint")
        return assess_archive_backlog(row["pending_rows"], row["oldest_pending_at"], window)
