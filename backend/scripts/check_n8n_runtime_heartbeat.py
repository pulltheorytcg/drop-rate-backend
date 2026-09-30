from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta

import asyncpg

from app.automation_health import check_n8n_runtime_heartbeat


def _enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be boolean")


def _threshold_minutes() -> int:
    raw = os.getenv("TCG_N8N_HEARTBEAT_STALE_MINUTES", "20").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("TCG_N8N_HEARTBEAT_STALE_MINUTES must be an integer") from exc
    if value < 10 or value > 1440:
        raise RuntimeError(
            "TCG_N8N_HEARTBEAT_STALE_MINUTES must be between 10 and 1440"
        )
    return value


async def _run() -> int:
    database_url = os.getenv("TCG_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("TCG_DATABASE_URL is required")

    alert_enabled = _enabled("TCG_N8N_HEARTBEAT_ALERTS_ENABLED", False)
    threshold_minutes = _threshold_minutes()

    connection = await asyncpg.connect(
        dsn=database_url,
        timeout=15,
        command_timeout=20,
        server_settings={
            "application_name": "drop-rate-n8n-heartbeat-health",
            "search_path": "pg_catalog,tcg",
            "statement_timeout": "20000",
            "idle_in_transaction_session_timeout": "10000",
        },
    )
    try:
        result = await check_n8n_runtime_heartbeat(
            connection,
            alert_enabled=alert_enabled,
            stale_threshold=timedelta(minutes=threshold_minutes),
        )
    finally:
        await connection.close()

    payload = {
        **result,
        "last_received_at": (
            result["last_received_at"].isoformat()
            if result["last_received_at"] is not None
            else None
        ),
        "last_observed_at": (
            result["last_observed_at"].isoformat()
            if result["last_observed_at"] is not None
            else None
        ),
        "threshold_minutes": threshold_minutes,
    }

    if not alert_enabled:
        print(
            json.dumps(
                {"event": "N8N_RUNTIME_HEARTBEAT_OBSERVED_DORMANT", **payload},
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    if result["healthy"]:
        print(
            json.dumps(
                {"event": "N8N_RUNTIME_HEARTBEAT_HEALTHY", **payload},
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    print(
        json.dumps(
            {"event": "N8N_RUNTIME_HEARTBEAT_STALE", **payload},
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )
    return 2


def main() -> None:
    try:
        code = asyncio.run(_run())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "event": "N8N_RUNTIME_HEARTBEAT_FATAL",
                    "error_code": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
