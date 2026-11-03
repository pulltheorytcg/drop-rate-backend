"""Manually archive both live reference price tables to private R2 without SQL changes.

Local restore proof is the default. --apply also needs an explicit Railway
environment opt-in and a configured, existing platform-administrator actor.
The command never removes a price, quote, card, history row or inventory item.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import UUID

from app.db import create_pool
from app.object_storage import ObjectStorageError
from app.reference_quote_source_backup import backup_reference_quote_sources
from app.settings import get_settings


async def run(*, apply: bool) -> dict:
    if apply and os.getenv("TCG_REFERENCE_QUOTE_R2_BACKUP_ENABLED", "false").lower() != "true":
        raise ObjectStorageError("Reference quote R2 shadow upload is not enabled")
    settings = get_settings()
    if not settings.catalogue_maintenance_actor_user_id:
        raise ObjectStorageError("A configured platform-administrator actor is required")
    actor = UUID(settings.catalogue_maintenance_actor_user_id)
    pool = await create_pool(settings)
    try:
        return await backup_reference_quote_sources(pool, actor, upload=apply)
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Upload privately to R2; verify downloaded bytes and typed restore")
    options = parser.parse_args()
    print(json.dumps(asyncio.run(run(apply=options.apply)), sort_keys=True))
