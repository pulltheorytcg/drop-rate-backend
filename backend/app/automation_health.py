from __future__ import annotations

from datetime import timedelta
from typing import Any

import asyncpg


async def check_automation_outbox_health(
    connection: asyncpg.Connection,
    *,
    alert_enabled: bool = False,
    pending_age_threshold: timedelta = timedelta(minutes=30),
) -> dict[str, Any]:
    if pending_age_threshold < timedelta(minutes=5):
        raise ValueError("Automation pending-age threshold must be at least 5 minutes")
    if pending_age_threshold > timedelta(hours=24):
        raise ValueError("Automation pending-age threshold must be at most 24 hours")

    row = await connection.fetchrow(
        """
        select *
        from tcg.check_automation_outbox_health($1,$2::interval)
        """,
        alert_enabled,
        pending_age_threshold,
    )
    if row is None:
        raise RuntimeError("Automation outbox health check returned no result")

    return {
        "healthy": bool(row["healthy"]),
        "alert_enabled": bool(row["alert_enabled"]),
        "pending_count": int(row["pending_count"] or 0),
        "due_count": int(row["due_count"] or 0),
        "dispatching_count": int(row["dispatching_count"] or 0),
        "dead_letter_count": int(row["dead_letter_count"] or 0),
        "oldest_pending_at": row["oldest_pending_at"],
        "oldest_pending_age_seconds": (
            int(row["oldest_pending_age_seconds"])
            if row["oldest_pending_age_seconds"] is not None
            else None
        ),
        "stale_dispatching_count": int(row["stale_dispatching_count"] or 0),
        "alerted_founders": int(row["alerted_founders"] or 0),
        "resolved_founders": int(row["resolved_founders"] or 0),
    }


async def check_n8n_runtime_heartbeat(
    connection: asyncpg.Connection,
    *,
    alert_enabled: bool = False,
    stale_threshold: timedelta = timedelta(minutes=20),
) -> dict[str, Any]:
    if stale_threshold < timedelta(minutes=10):
        raise ValueError("n8n heartbeat threshold must be at least 10 minutes")
    if stale_threshold > timedelta(hours=24):
        raise ValueError("n8n heartbeat threshold must be at most 24 hours")

    row = await connection.fetchrow(
        """
        select *
        from tcg.check_n8n_runtime_heartbeat($1,$2::interval)
        """,
        alert_enabled,
        stale_threshold,
    )
    if row is None:
        raise RuntimeError("n8n runtime heartbeat health check returned no result")

    return {
        "healthy": bool(row["healthy"]),
        "alert_enabled": bool(row["alert_enabled"]),
        "last_received_at": row["last_received_at"],
        "last_observed_at": row["last_observed_at"],
        "last_workflow_version": row["last_workflow_version"],
        "last_execution_id": row["last_execution_id"],
        "beat_count": int(row["beat_count"] or 0),
        "age_seconds": (
            int(row["age_seconds"]) if row["age_seconds"] is not None else None
        ),
        "alerted_founders": int(row["alerted_founders"] or 0),
        "resolved_founders": int(row["resolved_founders"] or 0),
    }
