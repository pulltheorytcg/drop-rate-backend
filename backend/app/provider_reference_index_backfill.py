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


async def _run(
    system_code: str,
    language: str,
    limit: int,
    max_batches: int,
) -> None:
    settings = get_settings()
    actor_raw = settings.shopify_catalogue_bootstrap_actor_user_id
    if not actor_raw:
        raise RuntimeError(
            "TCG_SHOPIFY_CATALOGUE_BOOTSTRAP_ACTOR_USER_ID is required for the admin backfill"
        )
    actor_user_id = UUID(actor_raw)
    pool = await create_pool(settings)
    lock_name = f"provider-reference-index-backfill:{system_code}:{language}"
    try:
        async with pool.acquire() as lock_connection:
            locked = await lock_connection.fetchval(
                "select pg_try_advisory_lock(hashtextextended($1,0))",
                lock_name,
            )
            if not locked:
                print(
                    json.dumps(
                        {
                            "event": "provider_reference_index_backfill",
                            "executed": False,
                            "reason": "ALREADY_RUNNING",
                            "system_code": system_code,
                            "language": language,
                        },
                        sort_keys=True,
                    )
                )
                return

            try:
                async with user_connection(
                    pool,
                    actor_user_id,
                    "provider-reference-index-backfill",
                ) as connection:
                    owner = await current_owner(connection)
                    if owner["role"] != "PLATFORM_ADMIN":
                        raise RuntimeError(
                            "Provider reference index backfill requires PLATFORM_ADMIN"
                        )

                total_eligible = 0
                total_indexed = 0
                total_skipped_unavailable = 0
                completed_batches = 0
                skipped_offset = 0
                drained = False

                for batch_number in range(1, max_batches + 1):
                    async with user_connection(
                        pool,
                        actor_user_id,
                        "provider-reference-index-backfill",
                    ) as connection:
                        rows = await _eligible_provider_reference_rows(
                            connection,
                            limit=limit,
                            system_code=system_code,
                            language=language,
                            offset=skipped_offset,
                        )

                    if not rows:
                        drained = True
                        break

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

                    completed_batches += 1
                    batch_eligible = int(result["eligible"])
                    batch_indexed = int(result["indexed"])
                    batch_skipped = int(result["skipped_unavailable"])
                    total_eligible += batch_eligible
                    total_indexed += batch_indexed
                    total_skipped_unavailable += batch_skipped
                    skipped_offset += batch_skipped

                    print(
                        json.dumps(
                            {
                                "event": "provider_reference_index_batch",
                                "batch": batch_number,
                                "eligible": batch_eligible,
                                "indexed": batch_indexed,
                                "skipped_unavailable": batch_skipped,
                                "skip_offset": skipped_offset,
                                "fingerprint_version": result["fingerprint_version"],
                            },
                            sort_keys=True,
                        )
                    )

                    # Successful rows disappear from the eligible query. A cumulative
                    # OFFSET skips only rows that were unavailable earlier in this run,
                    # so one broken image cannot pin every later batch.
                    if batch_eligible < limit and batch_skipped == 0:
                        drained = True
                        break

                async with user_connection(
                    pool,
                    actor_user_id,
                    "provider-reference-index-backfill",
                ) as connection:
                    status = await provider_reference_index_status(connection)

                print(
                    json.dumps(
                        {
                            "event": "provider_reference_index_backfill",
                            "executed": True,
                            "system_code": system_code,
                            "language": language,
                            "limit": limit,
                            "max_batches": max_batches,
                            "completed_batches": completed_batches,
                            "eligible_processed": total_eligible,
                            "indexed": total_indexed,
                            "skipped_unavailable": total_skipped_unavailable,
                            "drained": drained,
                            "fingerprint_version": status["fingerprint_version"],
                            "status": status,
                        },
                        default=str,
                        sort_keys=True,
                    )
                )
            finally:
                await lock_connection.execute(
                    "select pg_advisory_unlock(hashtextextended($1,0))",
                    lock_name,
                )
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill governed provider-reference visual fingerprints."
    )
    parser.add_argument("--system-code", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--max-batches", type=int, default=1)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")
    if args.max_batches < 1 or args.max_batches > 100:
        parser.error("--max-batches must be between 1 and 100")
    asyncio.run(
        _run(
            args.system_code.strip(),
            args.language.strip(),
            args.limit,
            args.max_batches,
        )
    )


if __name__ == "__main__":
    main()
