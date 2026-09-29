from __future__ import annotations

import asyncio
import json
import os
import sys

print(
    json.dumps(
        {
            "event": "PAYOUT_SCHEDULER_HEARTBEAT_PROCESS_START",
            "database_url_configured": bool(os.getenv("TCG_DATABASE_URL", "").strip()),
        },
        sort_keys=True,
    ),
    flush=True,
)

try:
    import asyncpg

    from app.payout_scheduler import check_scheduler_heartbeat
except Exception as exc:
    print(
        json.dumps(
            {
                "event": "PAYOUT_SCHEDULER_HEARTBEAT_IMPORT_FAILED",
                "error_code": type(exc).__name__,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )
    raise


async def _run() -> int:
    database_url = os.getenv("TCG_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("TCG_DATABASE_URL is required")

    try:
        connection = await asyncpg.connect(
            dsn=database_url,
            timeout=15,
            command_timeout=20,
            server_settings={
                "application_name": "drop-rate-payout-heartbeat",
                "search_path": "pg_catalog,tcg",
                "statement_timeout": "20000",
                "idle_in_transaction_session_timeout": "10000",
            },
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "event": "PAYOUT_SCHEDULER_HEARTBEAT_DB_CONNECT_FAILED",
                    "error_code": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        raise

    try:
        result = await check_scheduler_heartbeat(connection)
    finally:
        await connection.close()

    payload = {
        "healthy": result["healthy"],
        "last_completed_at": (
            result["last_completed_at"].isoformat()
            if result["last_completed_at"] is not None
            else None
        ),
        "last_status": result["last_status"],
        "alerted_founders": result["alerted_founders"],
        "resolved_founders": result["resolved_founders"],
    }

    if result["healthy"]:
        print(
            json.dumps(
                {"event": "PAYOUT_SCHEDULER_HEARTBEAT_HEALTHY", **payload},
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    print(
        json.dumps(
            {"event": "PAYOUT_SCHEDULER_HEARTBEAT_UNHEALTHY", **payload},
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
                    "event": "PAYOUT_SCHEDULER_HEARTBEAT_FATAL",
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
