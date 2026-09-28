from __future__ import annotations

import asyncio
import json
import os
import sys
from urllib.parse import urlparse

import asyncpg
import httpx

from app.automation_dispatcher import (
    canonical_event_body,
    classify_http_failure,
    retry_delay_seconds,
    signature_headers,
)


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _webhook_url() -> str:
    value = _required("TCG_N8N_WEBHOOK_URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("TCG_N8N_WEBHOOK_URL must be an HTTPS URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise RuntimeError("TCG_N8N_WEBHOOK_URL contains unsupported URL components")
    return value


async def _configure_connection(connection: asyncpg.Connection) -> None:
    for type_name in ("json", "jsonb"):
        await connection.set_type_codec(
            type_name,
            schema="pg_catalog",
            encoder=json.dumps,
            decoder=json.loads,
            format="text",
        )


async def _ack(
    connection: asyncpg.Connection,
    event_id,
    worker_id: str,
) -> bool:
    return bool(
        await connection.fetchval(
            "select tcg.ack_automation_event($1,$2)",
            event_id,
            worker_id,
        )
    )


async def _fail(
    connection: asyncpg.Connection,
    *,
    event_id,
    worker_id: str,
    error_code: str,
    retry_after_seconds: int,
    force_dead_letter: bool,
) -> str:
    value = await connection.fetchval(
        "select tcg.fail_automation_event($1,$2,$3,$4,$5)",
        event_id,
        worker_id,
        error_code,
        retry_after_seconds,
        force_dead_letter,
    )
    return str(value or "UNKNOWN")


async def _dispatch_one(
    connection: asyncpg.Connection,
    client: httpx.AsyncClient,
    *,
    event: asyncpg.Record,
    worker_id: str,
    webhook_url: str,
    webhook_secret: str,
) -> dict:
    event_id = event["event_id"]
    event_type = str(event["event_type"])
    attempt_count = int(event["attempt_count"])
    retry_after = retry_delay_seconds(attempt_count)

    try:
        body = canonical_event_body(dict(event))
        headers = signature_headers(secret=webhook_secret, body=body)
        headers["X-Drop-Rate-Event-Id"] = str(event_id)
        headers["X-Drop-Rate-Event-Type"] = event_type
        headers["X-Drop-Rate-Schema-Version"] = str(event["schema_version"])

        response = await client.post(
            webhook_url,
            content=body,
            headers=headers,
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        state = await _fail(
            connection,
            event_id=event_id,
            worker_id=worker_id,
            error_code=f"EVENT_CONTRACT_{type(exc).__name__}",
            retry_after_seconds=retry_after,
            force_dead_letter=True,
        )
        return {
            "event_id": str(event_id),
            "event_type": event_type,
            "ok": False,
            "state": state,
            "error_code": "EVENT_CONTRACT_INVALID",
        }
    except httpx.TimeoutException:
        state = await _fail(
            connection,
            event_id=event_id,
            worker_id=worker_id,
            error_code="N8N_TIMEOUT",
            retry_after_seconds=retry_after,
            force_dead_letter=False,
        )
        return {
            "event_id": str(event_id),
            "event_type": event_type,
            "ok": False,
            "state": state,
            "error_code": "N8N_TIMEOUT",
        }
    except httpx.RequestError:
        state = await _fail(
            connection,
            event_id=event_id,
            worker_id=worker_id,
            error_code="N8N_REQUEST_FAILED",
            retry_after_seconds=retry_after,
            force_dead_letter=False,
        )
        return {
            "event_id": str(event_id),
            "event_type": event_type,
            "ok": False,
            "state": state,
            "error_code": "N8N_REQUEST_FAILED",
        }

    if 200 <= response.status_code < 300:
        acknowledged = await _ack(connection, event_id, worker_id)
        return {
            "event_id": str(event_id),
            "event_type": event_type,
            "ok": acknowledged,
            "state": "DELIVERED" if acknowledged else "LEASE_LOST",
            "http_status": response.status_code,
        }

    error_code, force_dead_letter = classify_http_failure(response.status_code)
    state = await _fail(
        connection,
        event_id=event_id,
        worker_id=worker_id,
        error_code=error_code,
        retry_after_seconds=retry_after,
        force_dead_letter=force_dead_letter,
    )
    return {
        "event_id": str(event_id),
        "event_type": event_type,
        "ok": False,
        "state": state,
        "error_code": error_code,
        "http_status": response.status_code,
    }


async def _run() -> None:
    database_url = _required("TCG_DATABASE_URL")
    webhook_url = _webhook_url()
    webhook_secret = _required("TCG_N8N_WEBHOOK_SECRET")
    if len(webhook_secret) < 32:
        raise RuntimeError("TCG_N8N_WEBHOOK_SECRET must be at least 32 characters")

    worker_id = (
        os.getenv("TCG_AUTOMATION_WORKER_ID", "drop-rate-n8n-dispatcher").strip()
        or "drop-rate-n8n-dispatcher"
    )
    if len(worker_id) < 3 or len(worker_id) > 120:
        raise RuntimeError("TCG_AUTOMATION_WORKER_ID must be 3-120 characters")

    poll_seconds = _int_env(
        "TCG_AUTOMATION_POLL_SECONDS",
        2,
        minimum=1,
        maximum=60,
    )
    batch_size = _int_env(
        "TCG_AUTOMATION_BATCH_SIZE",
        20,
        minimum=1,
        maximum=100,
    )
    lease_seconds = _int_env(
        "TCG_AUTOMATION_LEASE_SECONDS",
        120,
        minimum=30,
        maximum=900,
    )
    timeout_seconds = _int_env(
        "TCG_AUTOMATION_HTTP_TIMEOUT_SECONDS",
        20,
        minimum=5,
        maximum=120,
    )
    if lease_seconds <= timeout_seconds + 10:
        raise RuntimeError(
            "TCG_AUTOMATION_LEASE_SECONDS must exceed HTTP timeout by more than 10 seconds"
        )

    connection = await asyncpg.connect(
        dsn=database_url,
        command_timeout=20,
        server_settings={
            "application_name": "drop-rate-n8n-dispatcher",
            "search_path": "pg_catalog,tcg",
            "statement_timeout": "20000",
            "idle_in_transaction_session_timeout": "10000",
        },
    )
    await _configure_connection(connection)

    timeout = httpx.Timeout(timeout_seconds)
    limits = httpx.Limits(max_connections=batch_size, max_keepalive_connections=batch_size)

    try:
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "event": "AUTOMATION_DISPATCHER_STARTED",
                        "worker_id": worker_id,
                        "batch_size": batch_size,
                        "poll_seconds": poll_seconds,
                    },
                    sort_keys=True,
                )
            )
            while True:
                rows = await connection.fetch(
                    "select * from tcg.claim_automation_events($1,$2,$3)",
                    worker_id,
                    batch_size,
                    lease_seconds,
                )

                if not rows:
                    await asyncio.sleep(poll_seconds)
                    continue

                for event in rows:
                    result = await _dispatch_one(
                        connection,
                        client,
                        event=event,
                        worker_id=worker_id,
                        webhook_url=webhook_url,
                        webhook_secret=webhook_secret,
                    )
                    print(json.dumps(result, sort_keys=True))
    finally:
        await connection.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        raise SystemExit(0)
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


if __name__ == "__main__":
    main()
