"""Per-original-game release imports behind existing owner-safe catalogue maintenance.

No new provider adapters, URL scraping, pricing, stock, or Shopify writes.
Existing catalogue source importer remains authority and retains the 400 MB
capacity limit until an independently verified R2/D1 migration is deployed.
Riftbound uses a separate permission-needed sentinel: no Riot content is fetched.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from types import MappingProxyType
from uuid import UUID, uuid4

from .access_control import require_platform_admin
from .catalogue_maintenance import SOURCE_REVISIONS, SOURCES, due, sync_source
from .database_capacity import check_database_capacity
from .db import user_connection

log = logging.getLogger(__name__)
LEGACY_GAMES = MappingProxyType({
    "POKEMON": ("tcgdex",),
    "ONE_PIECE": ("punk", "one_piece_official"),
    "DRAGON_BALL": ("dragon_ball_masters", "dragon_ball_fusion"),
    "NARUTO": ("naruto_kayou", "naruto_bandai"),
})
RIFTBOUND = "RIFTBOUND"
LOCK_KEY = 847220092  # exact same session-level lock as catalogue_maintenance.daily_pass


async def check_game(pool, actor: str, game: str) -> dict:
    """One game's due imports, never a second implementation of provider logic.

    The initial positive/complete checks remain PostgreSQL-bound; any source
    cardinality or drift in expected feeds is fail-closed.
    """
    if game == RIFTBOUND:
        return {
            "game": game, "status": "AWAITING_RIOT_APP_APPROVAL",
            "source_count": 0, "sources_checked": 0,
            "source_imports": 0, "metadata_updated": False,
            "artwork_published": False,
            "approval_url": "https://developer.riotgames.com/docs/riftbound",
        }
    targets = LEGACY_GAMES.get(game)
    if targets is None or not targets or not set(targets).issubset(SOURCES):
        raise ValueError("Unknown or unreviewed legacy card game")
    actor = UUID(str(actor))
    async with pool.acquire() as lock:
        acquired = await lock.fetchval("select pg_try_advisory_lock($1)", LOCK_KEY)
        if not acquired:
            return {
                "game": game, "status": "ALREADY_RUNNING",
                "source_count": len(targets), "sources_checked": 0,
                "source_imports": 0, "metadata_updated": False,
                "artwork_published": False,
            }
        try:
            # Capacity and admin review before any network, provider or DB write.
            async with user_connection(pool, actor, str(uuid4()), readonly_snapshot=True) as connection:
                await require_platform_admin(connection)
                capacity = await check_database_capacity(connection)
                if not capacity.refresh_allowed:
                    return {
                        "game": game, "status": "DEFERRED_CAPACITY",
                        "capacity_reason": capacity.reason,
                        "source_count": len(targets), "sources_checked": 0,
                        "source_imports": 0, "metadata_updated": False,
                        "artwork_published": False,
                    }
                previous = await connection.fetch("""
                    select distinct on(source) source,started_at,status,report
                    from tcg.reference_sync_runs
                    where source = any($1::text[])
                    order by source,started_at desc
                """, list(targets))
            last = {r["source"]: r for r in previous}
            now = datetime.now(timezone.utc)
            applied, examined = [], 0
            for target in targets:
                if not due(last.get(target), now, revision=SOURCE_REVISIONS.get(target, 1)):
                    continue
                examined += 1
                result = await sync_source(pool, actor, target, None)
                if result.get("status") != "COMPLETE":
                    # sync_source owns durable per-source receipts and retries.
                    # A partial source cannot make another provider look current.
                    return {
                        "game": game, "status": "INCOMPLETE",
                        "source_count": len(targets), "sources_checked": examined,
                        "source_imports": len(applied),
                        "completed_sources": applied,
                        "incomplete_source": target,
                        "metadata_updated": bool(applied),
                        "artwork_published": False,
                    }
                applied.append(target)
            log.warning("DR97_LEGACY_RELEASE_SCOUT game=%s status=%s imported=%s",
                        game, "COMPLETE" if applied else "CURRENT", len(applied))
            return {
                "game": game, "status": "COMPLETE" if applied else "CURRENT",
                "source_count": len(targets), "sources_checked": examined,
                "source_imports": len(applied),
                "completed_sources": applied,
                "metadata_updated": bool(applied),
                "artwork_published": False,
            }
        finally:
            await lock.execute("select pg_advisory_unlock($1)", LOCK_KEY)
