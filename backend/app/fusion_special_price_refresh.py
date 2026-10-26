"""Bounded operator for the reviewed Fusion SB01/ST01 base-printing guide fill."""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from .access_control import require_platform_admin
from .database_capacity import check_database_capacity
from .db import user_connection
from .pokewallet_dragon_ball_market import refresh_pokewallet_dragon_ball, SOURCES

VERSION = "FUSION_SPECIAL_CATALOGUE_PRICE_FILL_V1"
MAINTENANCE_LOCK = 847220092
READBACK_SQL = """select p.provider_id,r.name,r.card_number,p.market_value_minor,
 p.quotes->0->>'source_card_id' as source_card_id,
 p.quotes->0->>'source_product_url' as source_product_url
 from tcg.reference_catalogue_prices p
 join tcg.reference_cards r using(provider,system_code,language,provider_id)
 where p.provider='Bandai Official' and p.system_code='DRAGON_BALL_SUPER_FUSION_WORLD'
 and p.language='English' and r.set_id=$3
 and p.provider_id=r.set_id||':'||r.card_number and p.market_value_minor>0
 and p.quotes->0->>'source'=any($1::text[]) and p.quotes->0->>'operator_run_id'=$2
 order by p.provider_id"""


async def refresh_fusion_special(pool, actor, fx, api_key, *, reference_set_id,
                                 apply=False, max_seconds=90):
    if reference_set_id not in {'583201', '583301'}:
        raise ValueError('UNREVIEWED_REFERENCE_SET')
    if not isinstance(actor, UUID) or type(apply) is not bool:
        raise ValueError("A UUID administrator and boolean apply are required")
    if type(max_seconds) is not int or not 1 <= max_seconds <= 90:
        raise ValueError("Time budget must be between 1 and 90 seconds")
    operation_id = str(uuid4())
    report = {"version": VERSION, "apply": apply, "reference_set_id": reference_set_id,
              "operator_run_id": operation_id, "status": "NOT_STARTED",
              "written": 0, "readback_verified": False, "max_seconds": max_seconds}
    async with pool.acquire() as lock:
        if not await lock.fetchval("select pg_try_advisory_lock($1)", MAINTENANCE_LOCK):
            report["status"] = "BUSY"
            return report
        run_id = None
        try:
            async with user_connection(pool, actor, operation_id) as connection:
                await require_platform_admin(connection)
                capacity = await check_database_capacity(connection)
                report["capacity"] = capacity.report()
                if not capacity.refresh_allowed:
                    report["status"] = "CAPACITY_BLOCKED"
                    return report
                if apply:
                    run_id = await connection.fetchval("""insert into tcg.reference_sync_runs
                        (source,status) values('fusion_special_catalogue_prices','RUNNING') returning id""")
                    report["receipt_id"] = str(run_id)
            try:
                result = await asyncio.wait_for(refresh_pokewallet_dragon_ball(
                    pool, actor, fx, api_key, dry_run=not apply, request_limit=8,
                    reference_set_id=reference_set_id, operator_run_id=operation_id),
                    timeout=max_seconds)
                report.update(result)
                report["status"] = ("INCOMPLETE" if (result.get("provider_failures") or result.get("invalid_queries") or
                                        result.get("deferred_queries")) else
                                    "COMPLETE" if apply else "VERIFIED")
            except TimeoutError:
                report.update(status="INTERRUPTED", error_type="TimeoutError")
            except Exception as exc:
                report.update(status="FAILED", error_type=type(exc).__name__)
            if apply:
                # Count persisted rows bearing this invocation's UUID, including
                # after cancellation. Never equate executemany attempts to commits.
                try:
                    async with user_connection(pool, actor, operation_id) as connection:
                        await require_platform_admin(connection)
                        rows = [dict(row) for row in await connection.fetch(
                            READBACK_SQL, sorted(SOURCES), operation_id, reference_set_id)]
                    report.update(written=len(rows), committed=rows,
                                  readback_verified=True, write_outcome_unknown=False)
                    if (report["status"] == "COMPLETE" and
                            len(rows) != report.get("eligible_quotes", 0)):
                        report["status"] = "INCOMPLETE"
                except Exception as exc:
                    report.update(status="INCOMPLETE", written=None,
                                  readback_error_type=type(exc).__name__,
                                  write_outcome_unknown=True)
            if run_id is not None:
                try:
                    async with user_connection(pool, actor, operation_id) as connection:
                        await require_platform_admin(connection)
                        await connection.execute("""update tcg.reference_sync_runs
                            set status=$2,finished_at=now(),sets_loaded=1,cards_loaded=$3,
                                report=$4::jsonb where id=$1""", run_id,
                            "COMPLETE" if report["status"] == "COMPLETE" else "INCOMPLETE",
                            report.get("written") or 0,
                            {key: value for key, value in report.items() if key != "preview"})
                    report["receipt_finalized"] = True
                except Exception as exc:
                    report.update(status="INCOMPLETE", receipt_finalized=False,
                                  receipt_error_type=type(exc).__name__)
            return report
        finally:
            await lock.fetchval("select pg_advisory_unlock($1)", MAINTENANCE_LOCK)
