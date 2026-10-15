"""Read-only Free database quota probe, run by the existing operations monitor."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import asyncpg

from app.database_capacity import CAPACITY_SQL, assess_capacity


async def check() -> dict:
    dsn = os.getenv("TCG_DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("TCG_DATABASE_URL is required")
    connection = await asyncpg.connect(
        dsn=dsn,
        timeout=15,
        command_timeout=20,
        server_settings={
            "application_name": "drop-rate-database-capacity-watch",
            "statement_timeout": "20000",
            "idle_in_transaction_session_timeout": "10000",
        },
    )
    try:
        row = await connection.fetchrow(CAPACITY_SQL)
        if row is None:
            raise RuntimeError("Empty database capacity response")
        return assess_capacity(row["database_bytes"], row["default_read_only"]).report()
    finally:
        await connection.close()


def main() -> None:
    try:
        report = asyncio.run(check())
    except Exception as exc:
        print(json.dumps({"event": "DATABASE_CAPACITY_PROBE_FAILED",
                          "error_code": type(exc).__name__}, sort_keys=True),
              file=sys.stderr, flush=True)
        raise SystemExit(1) from exc

    event = {
        "OK": "DATABASE_CAPACITY_HEALTHY",
        "WARNING": "DATABASE_CAPACITY_WARNING",
        "CRITICAL": "DATABASE_CAPACITY_URGENT",
    }[report["severity"]]
    print(json.dumps({"event": event, **report}, sort_keys=True),
          file=sys.stderr if report["severity"] == "CRITICAL" else sys.stdout,
          flush=True)
    raise SystemExit(2 if report["severity"] == "CRITICAL" else 0)


if __name__ == "__main__":
    main()
