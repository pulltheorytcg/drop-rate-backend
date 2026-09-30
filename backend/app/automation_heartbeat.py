from __future__ import annotations

from datetime import timedelta
from typing import Any

import asyncpg


async def check_n8n_workflow_heartbeat(
    connection: asyncpg.Connection,
    *,
    alert_enabled: bool = False,
    threshold: timedelta = timedelta(minutes=15),
) -> dict[str, Any]:
    if threshold < timedelta(minutes=10):
        raise ValueError("n8n workflow heartbeat threshold must be at least 10 minutes")
    if threshold > timedelta(hours=6):
        raise ValueError("n8n workflow heartbeat threshold must be at most 6 hours")

    row = await connection.fetchrow(
        "select * from tcg.check_n8n_workflow_heartbeat($1,$2::interval)",
        alert_enabled,
        threshold,
    )
    if row is None:
        raise RuntimeError("n8n workflow heartbeat check returned no result")

    return {
        "healthy": bool(row["healthy"]),
        "alert_enabled": bool(row["alert_enabled"]),
        "last_succeeded_at": row["last_succeeded_at"],
        "age_seconds": (
            int(row["age_seconds"]) if row["age_seconds"] is not None else None
        ),
        "alerted_founders": int(row["alerted_founders"] or 0),
        "resolved_founders": int(row["resolved_founders"] or 0),
    }
