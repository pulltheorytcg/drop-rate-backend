from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta

import asyncpg


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


def _threshold_seconds() -> int:
    raw = os.getenv("TCG_AUTOMATION_DISPATCHER_HEARTBEAT_THRESHOLD_SECONDS", "90").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            "TCG_AUTOMATION_DISPATCHER_HEARTBEAT_THRESHOLD_SECONDS must be an integer"
        ) from exc
    if value < 30 or value > 900:
        raise RuntimeError(
            "TCG_AUTOMATION_DISPATCHER_HEARTBEAT_THRESHOLD_SECONDS must be between 30 and 900"
        )
    return value


async def _run() -> int:
    database_url = os.getenv("TCG_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("TCG_DATABASE_URL is required")

    alert_enabled = _enabled("TCG_AUTOMATION_DISPATCHER_ALERTS_ENABLED", False)
    threshold_seconds = _threshold_seconds()

    connection = await asyncpg.connect(
        dsn=database_url,
        timeout=15,
        command_timeout=20,
        server_settings={
            "application_name": "drop-rate-automation-dispatcher-heartbeat",
            "search_path": "pg_catalog,tcg",
            "statement_timeout": "20000",
            "idle_in_transaction_session_timeout": "10000",
        },
    )
    try:
        installed = bool(
            await connection.fetchval(
                """
                select to_regprocedure(
                  'tcg.check_automation_dispatcher_heartbeat(boolean,interval)'
                ) is not null
                """
            )
        )
        if not installed:
            if alert_enabled:
                raise RuntimeError(
                    "Automation dispatcher heartbeat migration is not installed"
                )
            print(
                json.dumps(
                    {
                        "event": "AUTOMATION_DISPATCHER_HEARTBEAT_NOT_INSTALLED_DORMANT",
                        "alert_enabled": False,
                        "threshold_seconds": threshold_seconds,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            return 0

        row = await connection.fetchrow(
            """
            select *
            from tcg.check_automation_dispatcher_heartbeat($1,$2::interval)
            """,
            alert_enabled,
            timedelta(seconds=threshold_seconds),
        )
    finally:
        await connection.close()

    if row is None:
        raise RuntimeError("Automation dispatcher heartbeat check returned no result")

    payload = {
        "healthy": bool(row["healthy"]),
        "alert_enabled": bool(row["alert_enabled"]),
        "last_seen_at": (
            row["last_seen_at"].isoformat()
            if row["last_seen_at"] is not None
            else None
        ),
        "instance_id": row["instance_id"],
        "component_version": row["component_version"],
        "age_seconds": (
            int(row["age_seconds"]) if row["age_seconds"] is not None else None
        ),
        "alerted_founders": int(row["alerted_founders"] or 0),
        "resolved_founders": int(row["resolved_founders"] or 0),
        "threshold_seconds": threshold_seconds,
    }

    if not alert_enabled:
        print(
            json.dumps(
                {"event": "AUTOMATION_DISPATCHER_HEARTBEAT_OBSERVED_DORMANT", **payload},
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    if payload["healthy"]:
        print(
            json.dumps(
                {"event": "AUTOMATION_DISPATCHER_HEARTBEAT_HEALTHY", **payload},
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    print(
        json.dumps(
            {"event": "AUTOMATION_DISPATCHER_HEARTBEAT_UNHEALTHY", **payload},
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
                    "event": "AUTOMATION_DISPATCHER_HEARTBEAT_FATAL",
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
