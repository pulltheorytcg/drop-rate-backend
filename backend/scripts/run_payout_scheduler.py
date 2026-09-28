from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime

print(
    json.dumps(
        {
            "event": "PAYOUT_SCHEDULER_PROCESS_START",
            "python": sys.version.split()[0],
            "database_url_configured": bool(os.getenv("TCG_DATABASE_URL", "").strip()),
        },
        sort_keys=True,
    ),
    flush=True,
)

try:
    import asyncpg

    from app.payout_scheduler import queue_due_payouts
except Exception as exc:
    print(
        json.dumps(
            {
                "event": "PAYOUT_SCHEDULER_IMPORT_FAILED",
                "error_code": type(exc).__name__,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )
    raise


async def _finish_run(
    connection: asyncpg.Connection,
    run_id,
    *,
    status: str,
    summary: dict | None = None,
    error_code: str | None = None,
) -> None:
    data = summary or {}
    run_at = data.get("run_at")
    run_at_value = datetime.fromisoformat(run_at) if isinstance(run_at, str) else run_at
    errors = data.get("errors") or []
    await connection.fetchval(
        """
        select tcg.finish_payout_scheduler_run(
          $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13
        )
        """,
        run_id,
        status,
        int(data.get("checked") or 0),
        int(data.get("created") or 0),
        int(data.get("duplicate") or 0),
        int(data.get("no_balance") or 0),
        int(data.get("stripe_not_ready") or 0),
        int(data.get("owner_inactive") or 0),
        int(data.get("preference_changed") or 0),
        int(data.get("not_yet_due") or 0),
        len(errors),
        error_code,
        run_at_value,
    )


async def _run() -> int:
    database_url = os.getenv("TCG_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("TCG_DATABASE_URL is required")

    print(
        json.dumps(
            {"event": "PAYOUT_SCHEDULER_DB_CONNECT_START"},
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        connection = await asyncpg.connect(
            dsn=database_url,
            timeout=15,
            command_timeout=20,
            server_settings={
                "application_name": "drop-rate-payout-scheduler",
                "search_path": "pg_catalog,tcg",
                "statement_timeout": "20000",
                "idle_in_transaction_session_timeout": "10000",
            },
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "event": "PAYOUT_SCHEDULER_DB_CONNECT_FAILED",
                    "error_code": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        raise

    print(
        json.dumps(
            {"event": "PAYOUT_SCHEDULER_DB_CONNECTED"},
            sort_keys=True,
        ),
        flush=True,
    )

    run_id = None
    try:
        print(
            json.dumps(
                {"event": "PAYOUT_SCHEDULER_RUN_STARTING"},
                sort_keys=True,
            ),
            flush=True,
        )
        await connection.fetchval(
            "select tcg.fail_stale_payout_scheduler_runs(interval '30 minutes')"
        )
        run_id = await connection.fetchval("select tcg.start_payout_scheduler_run()")
        print(
            json.dumps(
                {
                    "event": "PAYOUT_SCHEDULER_RUN_STARTED",
                    "scheduler_run_id": str(run_id),
                },
                sort_keys=True,
            ),
            flush=True,
        )

        try:
            summary = await queue_due_payouts(connection)
            status = "SUCCESS" if summary["ok"] else "FAILED"
            error_code = None
            if summary.get("errors"):
                error_code = str(summary["errors"][0].get("code") or "SCHEDULER_ERROR")[:120]
            await _finish_run(
                connection,
                run_id,
                status=status,
                summary=summary,
                error_code=error_code,
            )
            print(json.dumps({**summary, "scheduler_run_id": str(run_id)}, sort_keys=True))
            return 0 if summary["ok"] else 1
        except Exception as exc:
            try:
                await _finish_run(
                    connection,
                    run_id,
                    status="FAILED",
                    error_code=type(exc).__name__,
                )
            except Exception:
                pass
            raise
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
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
