"""Bounded operator orchestration for the reviewed Hidden Fates price fill."""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from .access_control import require_platform_admin
from .database_capacity import check_database_capacity
from .db import user_connection
from .pokemon_catalogue_market import refresh_pokemon_catalogue_prices

VERSION = 'HIDDEN_FATES_CATALOGUE_PRICE_FILL_V1'
MAINTENANCE_LOCK = 847220092


async def refresh_hidden_fates(pool, actor, cardtrader_client, fx, *, apply=False, max_seconds=120):
    if not isinstance(actor, UUID) or type(apply) is not bool:
        raise ValueError('A UUID administrator and boolean apply are required')
    if type(max_seconds) is not int or not 1 <= max_seconds <= 240:
        raise ValueError('Time budget must be between 1 and 240 seconds')
    report = {'version': VERSION, 'apply': apply, 'reference_set_id': 'sma',
              'status': 'NOT_STARTED', 'written': 0, 'max_seconds': max_seconds}
    request_id = str(uuid4())
    async with pool.acquire() as lock:
        if not await lock.fetchval('select pg_try_advisory_lock($1)', MAINTENANCE_LOCK):
            report['status'] = 'BUSY'
            return report
        run_id = None
        try:
            async with user_connection(pool, actor, request_id) as connection:
                await require_platform_admin(connection)
                capacity = await check_database_capacity(connection)
                report['capacity'] = capacity.report()
                if not capacity.refresh_allowed:
                    report['status'] = 'CAPACITY_BLOCKED'
                    return report
                if apply:
                    run_id = await connection.fetchval("""insert into tcg.reference_sync_runs(source,status)
                        values('hidden_fates_catalogue_prices','RUNNING') returning id""")
            try:
                result = await asyncio.wait_for(refresh_pokemon_catalogue_prices(
                    pool, actor, fx, cardtrader_client=cardtrader_client,
                    reference_set_id='sma', dry_run=not apply), timeout=max_seconds)
                report.update(result)
                failed = bool(result.get('provider_failures'))
                incomplete = apply and result.get('written', 0) != result.get('priced', 0)
                report['status'] = ('INCOMPLETE' if failed or incomplete else
                                    'COMPLETE' if apply else 'VERIFIED')
            except TimeoutError:
                # A timeout around commit can leave its outcome uncertain.
                # Report that explicitly; the operator must use DB readback.
                report.update(status='INTERRUPTED', error_type='TimeoutError',
                              written=None if apply else 0, write_outcome_unknown=apply)
            except Exception as exc:
                report.update(status='FAILED', error_type=type(exc).__name__,
                              written=None if apply else 0, write_outcome_unknown=apply)
            finally:
                if run_id is not None:
                    async with user_connection(pool, actor, request_id) as connection:
                        await require_platform_admin(connection)
                        await connection.execute("""update tcg.reference_sync_runs
                            set status=$2,finished_at=now(),sets_loaded=1,cards_loaded=$3,
                                report=$4::jsonb where id=$1""", run_id,
                            'COMPLETE' if report['status']=='COMPLETE' else 'INCOMPLETE',
                            report.get('written') or 0,
                            {key: value for key, value in report.items() if key != 'preview'})
            return report
        finally:
            await lock.fetchval('select pg_advisory_unlock($1)', MAINTENANCE_LOCK)
