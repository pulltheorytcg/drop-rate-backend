from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

import asyncpg
from asyncpg import Connection, Pool

from .settings import Settings


async def create_pool(settings: Settings) -> Pool:
    return await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        command_timeout=15,
        max_inactive_connection_lifetime=300,
        server_settings={
            "application_name": f"drop-rate-api:{settings.environment}",
            "search_path": "pg_catalog,tcg",
            "statement_timeout": "15000",
            "idle_in_transaction_session_timeout": "10000",
        },
    )


@asynccontextmanager
async def user_connection(
    pool: Pool,
    user_id: UUID,
    request_id: str,
) -> AsyncIterator[Connection]:
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "select set_config('tcg.user_id', $1, true)",
                str(user_id),
            )
            await connection.execute(
                "select set_config('tcg.request_id', $1, true)",
                request_id,
            )
            yield connection
