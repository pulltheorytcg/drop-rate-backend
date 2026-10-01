from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from .db import create_pool, user_connection
from .ownership import current_owner
from .recognition_provider_reference_index import (
    _eligible_provider_reference_rows,
    fingerprint_provider_reference_rows,
    provider_reference_index_status,
    rebuild_provider_reference_index,
)
from .settings import get_settings


async def _run(system_code: str, language: str, limit: int) -> None:
    settings = get_settings()
    actor_raw = settings.shopify_catalogue_bootstrap_actor_user_id
    if not actor_raw:
        raise RuntimeError(
            "TCG_SHOPIFY_CATALOGUE_BOOTSTRAP_ACTOR_USER_ID is required for the admin backfill"
        )
    actor_user_id = UUID(actor_raw)
    pool = await create_pool(settings)
    try:
        async with user_connection(
            pool,
            actor_user_id,
            "provider-reference-index-backfill",
        ) as connection:
            owner = await current_owner(connection)
            if owner["role"] != "PLATFORM_ADMIN":
                raise RuntimeError("Provider reference index backfill requires PLATFORM_ADMIN")
            rows = await _eligible_provider_reference_rows(
                connection,
                limit=limit,
                system_code=system_code,
                language=language,
            )

        prepared = await fingerprint_provider_reference_rows(rows)

        async with user_connection(
            pool,
            actor_user_id,
            "provider-reference-index-backfill",
        ) as connection:
            result = await rebuild_provider_reference_index(
                connection,
                actor_user_id=actor_user_id,
                limit=limit,
                system_code=system_code,
                language=language,
                prepared=prepared,
            )
            result["status"] = await provider_reference_index_status(connection)
        print(json.dumps(result, default=str, sort_keys=True))
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill governed provider-reference visual fingerprints."
    )
    parser.add_argument("--system-code", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")
    asyncio.run(_run(args.system_code.strip(), args.language.strip(), args.limit))


if __name__ == "__main__":
    main()
