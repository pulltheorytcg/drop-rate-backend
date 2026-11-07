"""Manual, lossless R2 backup of the full reference-card source table.

Dry-run is the default. --apply needs an explicit environment opt-in and the
existing maintenance administrator. Neither mode deletes or updates any row.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import UUID

from app.db import create_pool
from app.object_storage import ObjectStorageError
from app.reference_source_backup import backup_reference_cards
from app.settings import get_settings


async def run(*, apply: bool) -> dict:
    if apply and os.getenv("TCG_REFERENCE_SOURCE_R2_BACKUP_ENABLED", "false").lower() != "true":
        raise ObjectStorageError("R2 reference source upload is not enabled")
    settings = get_settings()
    if not settings.catalogue_maintenance_actor_user_id:
        raise ObjectStorageError("A configured platform-administrator actor is required")
    actor = UUID(settings.catalogue_maintenance_actor_user_id)
    pool = await create_pool(settings)
    try:
        return await backup_reference_cards(pool, actor, upload=apply)
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Upload to private R2 and restore-verify")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(apply=args.apply)), sort_keys=True))
