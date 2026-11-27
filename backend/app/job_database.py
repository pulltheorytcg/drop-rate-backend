"""Database access for background jobs, kept apart from the API request pool.

DR-OPS-1 (27 Nov 2026): with ``DROP_RATE_CATALOGUE_BULK_HOLD=false`` the refresh
jobs started by the API lifespan acquired all five ``tcg_api`` API-pool
connections at startup and held them, so every DB-backed route hung. Each job
loop pinned one pooled connection idle for its whole pass purely to keep a
session advisory lock, plus further connections for its work.

Background jobs now receive a :class:`JobDatabase` instead of the API pool:

* their own small asyncpg pool (``TCG_DB_JOB_POOL_MAX``), so however many jobs
  run, or however long they wait on providers, API requests keep their pool;
* one dedicated session holding every session advisory lock (``lock_session``),
  so a pass that runs for hours does not pin a pooled connection for its lock;
* a bounded acquire timeout (``TCG_DB_JOB_ACQUIRE_TIMEOUT_SECONDS``), so
  contention between jobs surfaces as an ordinary job failure (existing
  receipts, logs and next-tick retry) instead of an indefinite hang.

Lock keys, receipts, pricing rules and RLS behaviour are unchanged: jobs still
set ``tcg.user_id`` through ``user_connection`` on every transaction.
"""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg

from .db import _init_connection, create_pool, retry_database_connection, server_settings
from .settings import Settings

log = logging.getLogger(__name__)

_LOCK_SQL = re.compile(
    r"^\s*select\s+pg_(try_advisory_lock|advisory_unlock)\s*\((?P<expr>.+)\)\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)

LockKey = tuple[str, tuple[Any, ...]]


def _parse_lock_sql(sql: str, args: tuple[Any, ...]) -> tuple[str, LockKey, str]:
    match = _LOCK_SQL.match(sql)
    if match is None:
        raise TypeError(
            "lock_session only runs pg_try_advisory_lock/pg_advisory_unlock; "
            "use pool.acquire() or user_connection() for queries"
        )
    expr = " ".join(match.group("expr").split())
    if re.fullmatch(r"-?\d+", expr) and not args:
        # pg_try_advisory_lock(847220121) == pg_try_advisory_lock($1) with 847220121
        key: LockKey = ("$1", (int(expr),))
    else:
        key = (expr, tuple(args))
    return match.group(1).lower(), key, f"select pg_advisory_unlock({expr})"


class JobDatabase:
    """Pool-compatible handle for background jobs.

    Pass it anywhere job code expects ``pool``: ``acquire()`` and
    ``user_connection(pool, ...)`` work unchanged. Advisory locks go through
    :func:`lock_session`, which uses the shared lock session.
    """

    def __init__(self, pool: asyncpg.Pool, *, lock_connect, acquire_timeout: float) -> None:
        self._pool = pool
        self._lock_connect = lock_connect
        self._lock_connection: asyncpg.Connection | None = None
        self._lock_guard = asyncio.Lock()
        self._held: set[LockKey] = set()
        self.acquire_timeout = acquire_timeout

    @classmethod
    async def open(cls, settings: Settings) -> "JobDatabase":
        name = f"drop-rate-jobs:{settings.environment}"
        pool = await create_pool(
            settings,
            min_size=0,
            max_size=settings.db_job_pool_max,
            application_name=name,
            context="job_pool",
        )

        async def lock_connect() -> asyncpg.Connection:
            async def connect() -> asyncpg.Connection:
                return await asyncpg.connect(
                    dsn=settings.database_url,
                    timeout=15,
                    command_timeout=15,
                    server_settings=server_settings(f"{name}:locks"),
                )

            connection = await retry_database_connection(connect, context="job_lock_session")
            await _init_connection(connection)
            return connection

        return cls(pool, lock_connect=lock_connect,
                   acquire_timeout=settings.db_job_acquire_timeout_seconds)

    def acquire(self, *, timeout: float | None = None):
        return self._pool.acquire(timeout=self.acquire_timeout if timeout is None else timeout)

    def __getattr__(self, name: str) -> Any:
        # release(), get_size(), get_max_size() etc. behave as on the pool.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._pool, name)

    async def _session(self) -> asyncpg.Connection:
        connection = self._lock_connection
        if connection is None or connection.is_closed():
            if self._held:
                # The server released these locks with the old session. Their
                # jobs keep running; the next pass re-acquires normally.
                log.error("JOB_LOCK_SESSION_LOST held=%d", len(self._held))
                self._held.clear()
            connection = await self._lock_connect()
            self._lock_connection = connection
        return connection

    async def _try_lock(self, key: LockKey, sql: str, args: tuple[Any, ...]) -> bool:
        async with self._lock_guard:
            # PostgreSQL session locks are re-entrant: without this set, two
            # jobs in one process sharing the session would both "acquire".
            if key in self._held:
                return False
            session = await self._session()
            acquired = bool(await session.fetchval(sql, *args))
            if acquired:
                self._held.add(key)
            return acquired

    async def _unlock(self, key: LockKey, sql: str, args: tuple[Any, ...]) -> bool:
        async with self._lock_guard:
            if key not in self._held:
                return False
            self._held.discard(key)
            session = self._lock_connection
            if session is None or session.is_closed():
                return False
            return bool(await session.fetchval(sql, *args))

    async def close(self) -> None:
        async with self._lock_guard:
            connection, self._lock_connection = self._lock_connection, None
            self._held.clear()
        if connection is not None and not connection.is_closed():
            await connection.close()
        await self._pool.close()


class _LockHandle:
    """Stands in for the old ``pool.acquire() as lock`` connection.

    Only advisory lock/unlock statements are accepted; they run on the shared
    lock session. Anything still held when the block exits is released, just
    as asyncpg's pool reset used to release it.
    """

    def __init__(self, db: JobDatabase) -> None:
        self._db = db
        self._held: dict[LockKey, tuple[str, tuple[Any, ...]]] = {}

    async def fetchval(self, sql: str, *args: Any) -> bool:
        return await self._run(sql, args)

    async def execute(self, sql: str, *args: Any) -> str:
        await self._run(sql, args)
        return "SELECT 1"

    async def _run(self, sql: str, args: tuple[Any, ...]) -> bool:
        operation, key, unlock_sql = _parse_lock_sql(sql, args)
        if operation == "advisory_unlock":
            if self._held.pop(key, None) is None:
                return False
            return await _shielded(self._db._unlock(key, sql, args))
        task = asyncio.ensure_future(self._db._try_lock(key, sql, args))
        try:
            acquired = await asyncio.shield(task)
        except asyncio.CancelledError:
            # Never leave a granted lock behind on the shared session.
            def _release(done: asyncio.Future) -> None:
                if not done.cancelled() and done.exception() is None and done.result():
                    asyncio.ensure_future(self._db._unlock(key, unlock_sql, args))
            task.add_done_callback(_release)
            raise
        if acquired:
            self._held[key] = (unlock_sql, args)
        return acquired

    async def release_all(self) -> None:
        held, self._held = self._held, {}
        for key, (unlock_sql, args) in held.items():
            try:
                await _shielded(self._db._unlock(key, unlock_sql, args))
            except Exception as exc:  # the lock dies with the session at worst
                log.error("JOB_LOCK_RELEASE_FAILED type=%s", type(exc).__name__)


async def _shielded(coroutine) -> Any:
    # A cancelled job must still release its lock on the shared session.
    task = asyncio.ensure_future(coroutine)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.wait({task})
        raise


@asynccontextmanager
async def lock_session(pool, *, timeout: float | None = None) -> AsyncIterator[Any]:
    """Replacement for ``async with pool.acquire() as lock`` in job code.

    With a :class:`JobDatabase` this yields a handle on the shared lock session
    (no pooled connection is held). With a plain pool (scripts, n8n-triggered
    API routes, older tests) the previous behaviour is kept exactly.
    """

    if isinstance(pool, JobDatabase):
        handle = _LockHandle(pool)
        try:
            yield handle
        finally:
            await handle.release_all()
        return
    kwargs = {} if timeout is None else {"timeout": timeout}
    async with pool.acquire(**kwargs) as connection:
        yield connection
