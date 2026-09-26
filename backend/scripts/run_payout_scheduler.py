from __future__ import annotations

import asyncio
import json
import os
import sys

import asyncpg

from app.payout_scheduler import queue_due_payouts


async def _run() -> int:
    database_url = os.getenv("TCG_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("TCG_DATABASE_URL is required")

    connection = await asyncpg.connect(
        dsn=database_url,
        command_timeout=20,
        server_settings={
            "application_name": "drop-rate-payout-scheduler",
            "search_path": "pg_catalog,tcg",
            "statement_timeout": "20000",
            "idle_in_transaction_session_timeout": "10000",
        },
    )
    try:
        summary = await queue_due_payouts(connection)
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["ok"] else 1
    finally:
        await connection.close()


def main() -> None:
    try:
        code = asyncio.run(_run())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "fatal_error": type(exc).__name__,
                    "detail": str(exc)[:300],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
