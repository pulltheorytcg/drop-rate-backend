"""Source-scoped legacy game release checks using existing daily maintenance rules.

Do not duplicate providers, bypass database capacity or grant Riftbound rights.
n8n schedules only; legacy PostgreSQL source adapter owns catalogue writes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from . import catalogue_maintenance as maintenance
from .access_control import require_platform_admin
from .database_capacity import check_database_capacity
from .db import user_connection

LEGACY_SOURCES = (
    "tcgdex", "one_piece_official", "punk",
    "dragon_ball_masters", "dragon_ball_fusion",
    "naruto_kayou", "naruto_bandai",
)
RIFTBOUND_SOURCE = "riftbound_riot"
LEGACY_GAMES = {
    "tcgdex": "POKEMON_TCG",
    "one_piece_official": "ONE_PIECE",
    "punk": "ONE_PIECE",
    "dragon_ball_masters": "DRAGON_BALL",
    "dragon_ball_fusion": "DRAGON_BALL",
    "naruto_kayou": "NARUTO",
    "naruto_bandai": "NARUTO",
    RIFTBOUND_SOURCE: "RIFTBOUND",
}
RIOT_POLICY = "https://developer.riotgames.com/docs/riftbound"
LOCK = 847220092  # same lock held by catalogue_maintenance.daily_pass


async def run_legacy_release_scout(pool, actor: str, source: str, settings) -> dict:
    """Run one due source, not all maintenance/pricing/Shopify work.

    Capacity checks happen while holding the *same* advisory lock as the
    production daily catalogue pass, but never hold an SQL transaction across
    provider HTTP or R2 processing.
    """
    if source not in LEGACY_GAMES:
        raise ValueError("Unapproved legacy catalogue source")
    game = LEGACY_GAMES[source]
    if source == RIFTBOUND_SOURCE:
        # Riot's official Digital Tools Policy requires a registered app and
        # approved App-specific key or written license. The public website or
        # an unofficial community export is not equivalent to authorized API.
        return {
            "status": "DEFERRED_RIOT_APPROVAL",
            "source": source, "game": game,
            "reason": "OFFICIAL_APP_KEY_OR_LICENSE_REQUIRED",
            "source_policy": RIOT_POLICY,
            "new_sets": 0,
        }
    if source not in maintenance.SOURCES:
        raise ValueError("Source is not supported by daily catalogue maintenance")
    if not settings.catalogue_daily_refresh_enabled:
        return {
            "status": "DISABLED_BY_POLICY", "source": source, "game": game,
            "new_sets": 0,
        }
    async with pool.acquire() as lock:
        if not await lock.fetchval("select pg_try_advisory_lock($1)", LOCK):
            return {"status": "ALREADY_RUNNING", "source": source, "game": game, "new_sets": 0}
        try:
            async with user_connection(pool, UUID(str(actor)), str(uuid4())) as connection:
                await require_platform_admin(connection)
                capacity = await check_database_capacity(connection)
                if not capacity.refresh_allowed:
                    return {
                        "status": "DEFERRED_CAPACITY", "source": source,
                        "game": game, "new_sets": 0, "reason": capacity.reason,
                    }
                previous = await connection.fetchrow(
                    """select source,started_at,status,report
                       from tcg.reference_sync_runs
                       where source=$1
                       order by started_at desc limit 1""", source,
                )
            if not maintenance.due(
                previous, datetime.now(timezone.utc),
                revision=maintenance.SOURCE_REVISIONS.get(source, 1),
            ):
                return {
                    "status": "CURRENT", "source": source,
                    "game": game, "new_sets": 0,
                }
            report = await maintenance.sync_source(pool, UUID(str(actor)), source, settings)
            if report.get("status") != "COMPLETE":
                return {
                    "status": "SOURCE_INCOMPLETE", "source": source,
                    "game": game, "new_sets": int(report.get("new_sets", 0)),
                    "reason": "UPSTREAM_OR_SOURCE_VERIFICATION_FAILED",
                }
            # The pre-existing importer has a stable three-key return contract.
            # Its committed sync-run report already records new-set discoveries.
            # Re-read that immutable-audited receipt without modifying callers
            # of sync_source or changing the daily maintenance worker.
            if "new_sets" not in report:
                async with user_connection(pool, UUID(str(actor)), str(uuid4())) as connection:
                    await require_platform_admin(connection)
                    written = await connection.fetchrow(
                        """select status,report from tcg.reference_sync_runs
                           where source=$1 order by started_at desc limit 1""", source,
                    )
                if not written or written["status"] != "COMPLETE":
                    return {
                        "status": "SOURCE_INCOMPLETE", "source": source,
                        "game": game, "new_sets": 0,
                        "reason": "VERIFIED_SOURCE_RECEIPT_MISSING",
                    }
                evidence = written["report"] or {}
                if (not isinstance(evidence, dict)
                        or type(evidence.get("new_sets")) is not int
                        or evidence["new_sets"] < 0
                        or not isinstance(evidence.get("new_set_samples", []), list)):
                    return {
                        "status": "SOURCE_INCOMPLETE", "source": source,
                        "game": game, "new_sets": 0,
                        "reason": "VERIFIED_SOURCE_RECEIPT_MALFORMED",
                    }
                report = {**report, "new_sets": evidence["new_sets"],
                          "new_set_samples": evidence.get("new_set_samples", [])}
            return {
                "status": "VERIFIED_SOURCE_REFRESH",
                "source": source, "game": game,
                "sets_checked": report["sets"],
                "records_checked": report["records"],
                "new_sets": int(report.get("new_sets", 0)),
                "new_set_samples": [
                    {k: item.get(k) for k in
                     ("system_code", "language", "set_id", "name", "release_date")}
                    for item in report.get("new_set_samples", [])[:5]
                ],
            }
        finally:
            await lock.execute("select pg_advisory_unlock($1)", LOCK)
