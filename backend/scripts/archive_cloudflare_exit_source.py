"""Railway-only, one-shot private R2 checkpoint for reviewed Supabase tables.

Default: no R2 writes. --apply needs service-specific explicit opt-in.
Never copies Auth, payment secrets, Shopify customer details or D1 data.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from dataclasses import replace
from uuid import UUID

from app.cloudflare_exit_source_archive import backup_operational_sources, MIN_ROWS
from app.db import create_pool
from app.object_storage import ObjectStorageError
from app.settings import get_settings


EXPORT_ROLE = "drop_rate_exit_export_ro_20261106"


async def verify_export_account(pool) -> None:
    """Never mistake a normal owner-scoped app login for a full-account backup.

    A dedicated time-limited, SELECT-only Postgres role must have BYPASSRLS,
    but NO superuser, CREATEROLE, CREATEDB or replication privileges.
    Its grants are restricted to the 11 reviewed source tables. We check
    actual visibility, while PostgreSQL RLS policies remain unchanged.
    """
    async with pool.acquire(timeout=15) as conn:
        async with conn.transaction(isolation="repeatable_read",readonly=True):
            role = await conn.fetchrow("""
                SELECT current_user AS username,
                  current_setting('default_transaction_read_only') AS default_read_only,
                  r.rolsuper,r.rolcreaterole,r.rolcreatedb,r.rolreplication,
                  r.rolbypassrls
                FROM pg_roles r WHERE r.rolname=current_user
            """)
            if (not role or role["username"] != EXPORT_ROLE
                    or role["default_read_only"] != "on"
                    or not role["rolbypassrls"]
                    or any(role[k] for k in ("rolsuper","rolcreaterole",
                                            "rolcreatedb","rolreplication"))):
                raise ObjectStorageError("Dedicated least-privilege read-only export role required")
            for table,minimum in MIN_ROWS.items():
                visible = await conn.fetchval(f'SELECT count(*) FROM tcg."{table}"')
                if type(visible) is not int or visible < minimum:
                    raise ObjectStorageError(f"Incomplete source table visibility: {table}")


async def run(*, apply: bool) -> dict:
    if apply and os.getenv("TCG_FULL_EXIT_PRIVATE_R2_BACKUP_ENABLED", "false").lower() != "true":
        raise ObjectStorageError("Production R2 private full-exit backup is not explicitly enabled")
    settings = get_settings()
    if not settings.catalogue_maintenance_actor_user_id:
        raise ObjectStorageError("Configured maintenance administrator required")
    actor = UUID(settings.catalogue_maintenance_actor_user_id)
    # Never point the storefront, FastAPI or default TCG_DATABASE_URL at a
    # BYPASSRLS role. This override exists only in the dedicated one-shot job.
    scoped_dsn = os.getenv("TCG_FULL_EXIT_READONLY_DATABASE_URL", "").strip()
    if not scoped_dsn:
        raise ObjectStorageError("Dedicated time-limited export DSN is missing")
    if not scoped_dsn.startswith(("postgresql://","postgres://")):
        raise ObjectStorageError("Invalid private export DSN protocol")
    settings = replace(settings,database_url=scoped_dsn,db_pool_min=1,db_pool_max=2)
    pool = await create_pool(settings)
    try:
        await verify_export_account(pool)
        return await backup_operational_sources(pool,actor,upload=apply)
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true",
                        help="R2 upload and full typed source readback; never delete SQL")
    args = parser.parse_args()
    result = asyncio.run(run(apply=args.apply))
    print(json.dumps(result,sort_keys=True))
