"""Railway-only, one-shot private R2 checkpoint for reviewed Supabase tables.

Default: no R2 writes. --apply needs service-specific explicit opt-in.
Never copies Auth, payment secrets, Shopify customer details or D1 data.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from uuid import UUID

from app.cloudflare_exit_source_archive import backup_operational_sources
from app.db import create_pool
from app.object_storage import ObjectStorageError
from app.settings import get_settings


async def run(*, apply: bool) -> dict:
    if apply and os.getenv("TCG_FULL_EXIT_PRIVATE_R2_BACKUP_ENABLED", "false").lower() != "true":
        raise ObjectStorageError("Production R2 private full-exit backup is not explicitly enabled")
    settings = get_settings()
    if not settings.catalogue_maintenance_actor_user_id:
        raise ObjectStorageError("Configured maintenance administrator required")
    actor = UUID(settings.catalogue_maintenance_actor_user_id)
    pool = await create_pool(settings)
    try:
        # A hung upstream source/R2 request must not leave an endless half-job.\n        # An aborted job never reports a completed manifest or D1 cutover.\n        return await asyncio.wait_for(\n            backup_operational_sources(pool,actor,upload=apply),timeout=1200)
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true",
                        help="R2 upload and full typed source readback; never delete SQL")
    args = parser.parse_args()
    result = asyncio.run(run(apply=args.apply))
    print(json.dumps(result,sort_keys=True))
