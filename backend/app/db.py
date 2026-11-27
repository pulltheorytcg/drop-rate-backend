from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar
from uuid import UUID

import asyncpg
from asyncpg import Connection, Pool

from .settings import Settings


_T = TypeVar("_T")
_DB_RETRY_DELAYS = (1, 2, 4)
_RETRYABLE_CONNECT_ERRORS = (
    TimeoutError,
    OSError,
    asyncpg.PostgresConnectionError,
    asyncpg.CannotConnectNowError,
)
_log = logging.getLogger(__name__)


async def retry_database_connection(
    connect: Callable[[], Awaitable[_T]], *, context: str
) -> _T:
    """Retry only transient connection failures; never mask auth or SQL errors.

    The bounded retries protect new Railway instances and short-lived cron
    workers from intermittent Supabase IPv6 TCP handshake timeouts. All
    financial and readiness checks still run and fail closed after retries.
    """
    for attempt, delay in enumerate((*_DB_RETRY_DELAYS, None), start=1):
        try:
            return await connect()
        except _RETRYABLE_CONNECT_ERRORS as exc:
            if delay is None:
                raise
            _log.warning(
                "DB_CONNECT_RETRY context=%s attempt=%d error=%s next_delay=%ds",
                context,
                attempt,
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)
    raise AssertionError("Unreachable database retry state")


DATABASE_WRITE_READY_SQL = """
select not (
    pg_is_in_recovery()
    or current_setting('transaction_read_only')::boolean
    or current_setting('default_transaction_read_only')::boolean
)
"""


def _encode_json(value: Any) -> str:
    """Encode JSON values without double-encoding existing serialized payloads."""

    if isinstance(value, str):
        return value
    return json.dumps(value)


async def _init_connection(connection: Connection) -> None:
    """Make json/jsonb behavior deterministic across every asyncpg connection."""

    for type_name in ("json", "jsonb"):
        await connection.set_type_codec(
            type_name,
            schema="pg_catalog",
            encoder=_encode_json,
            decoder=json.loads,
            format="text",
        )


def server_settings(application_name: str) -> dict[str, str]:
    """Session settings shared by the API pool, job pool and job lock session."""

    return {
        "application_name": application_name,
        "search_path": "pg_catalog,tcg",
        "statement_timeout": "15000",
        "idle_in_transaction_session_timeout": "10000",
    }


async def create_pool(
    settings: Settings,
    *,
    min_size: int | None = None,
    max_size: int | None = None,
    application_name: str | None = None,
    context: str = "api_pool",
) -> Pool:
    """Create an asyncpg pool; the defaults are the API request pool.

    Background jobs must not use the API pool (DR-OPS-1): they receive a
    ``job_database.JobDatabase`` built with the overrides here.
    """

    return await retry_database_connection(
        lambda: asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=settings.db_pool_min if min_size is None else min_size,
            max_size=settings.db_pool_max if max_size is None else max_size,
            timeout=15,
            command_timeout=15,
            max_inactive_connection_lifetime=300,
            init=_init_connection,
            server_settings=server_settings(
                application_name or f"drop-rate-api:{settings.environment}"
            ),
        ),
        context=context,
    )


@asynccontextmanager
async def user_connection(
    pool: Pool,
    user_id: UUID,
    request_id: str,
    *,
    readonly_snapshot: bool = False,
) -> AsyncIterator[Connection]:
    async with pool.acquire() as connection:
        options = {"isolation": "repeatable_read", "readonly": True} if readonly_snapshot else {}
        async with connection.transaction(**options):
            await connection.execute(
                "select set_config('tcg.user_id', $1, true)",
                str(user_id),
            )
            await connection.execute(
                "select set_config('tcg.request_id', $1, true)",
                request_id,
            )
            yield connection
