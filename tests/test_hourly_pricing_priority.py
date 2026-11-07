"""Execute the real scheduling body with immediate fakes; no network or event loop."""
import ast
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.tcgcsv_market import JOB as TCGCSV_JOB

NOW = datetime(2026, 10, 26, 21, 10, tzinfo=timezone.utc)
HOURLY_JOBS = {
    'one_piece': 'POKEWALLET_PRICES',
    'dragon_ball': 'POKEWALLET_DBS_PRICES',
    'pokemon': 'POKEWALLET_POKEMON_PRICES',
}


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def scheduler(*, allowed=True, recent=False, bulk_error=False, sources=(), hourly_reports=None):
    """Compile source bodies, not a test copy of the ordering implementation."""
    path = Path(__file__).parents[1] / 'backend/app/catalogue_maintenance.py'
    source = ast.parse(path.read_text(encoding='utf-8'))
    functions = {'daily_pass', 'daily_slot', 'hourly_slot', 'weekly_price_slot',
                 'weekly_price_due', 'due', 'coverage_lags_pricing', 'unapplied_trial_cursor'}
    constants = {'POKEWALLET_JOB_REVISION', 'POKEWALLET_DBS_JOB_REVISION',
                 'POKEWALLET_POKEMON_JOB_REVISION', 'ONE_PIECE_HOURLY_REQUEST_BUDGET',
                 'DBS_HOURLY_REQUEST_BUDGET', 'POKEMON_HOURLY_REQUEST_BUDGET',
                 'REFERENCE_JOB_REVISION'}
    nodes = [node for node in source.body if
             isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions
             or isinstance(node, ast.Assign) and any(
                 isinstance(target, ast.Name) and target.id in constants for target in node.targets)]
    module = ModuleType('actual_catalogue_scheduler')
    module.__dict__.update(datetime=Clock, timedelta=timedelta, timezone=timezone,
                           ZoneInfo=ZoneInfo, UUID=UUID, uuid4=uuid4, json=json,
                           log=logging.getLogger(__name__), SOURCES=sources, SOURCE_REVISIONS={},
                           CATALOGUE_VALUE_REVISION=1, CARDMARKET_VALUE_REVISION=1,
                           SEALED_MARKET_REVISION=1, TCGCSV_JOB=TCGCSV_JOB)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), module.__dict__)
    events = []
    jobs = []
    if recent:
        for name, revision in [('POKEWALLET_PRICES', module.POKEWALLET_JOB_REVISION),
                               ('POKEWALLET_DBS_PRICES', module.POKEWALLET_DBS_JOB_REVISION),
                               ('POKEWALLET_POKEMON_PRICES', module.POKEWALLET_POKEMON_JOB_REVISION)]:
            jobs.append(dict(job=name, status='COMPLETE', started_at=NOW,
                             report={'importer_revision':revision * 10 + 1, 'cursor':'old'}))

    class Connection:
        async def fetchval(self, sql, *args):
            events.append(('lock', args))
            return True

        async def execute(self, sql, *args):
            events.append(('unlock', args))

        async def fetch(self, sql, *args):
            if 'order by started_at desc limit 8' in sql:
                return [job for job in jobs if job['status'] == 'COMPLETE'
                        and f"job='{job['job']}'" in sql]
            return jobs if 'catalogue_job_runs' in sql else []

    connection = Connection()

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield connection

    @asynccontextmanager
    async def user_connection(*args):
        yield connection

    async def admin(*args):
        events.append(('admin', {}))

    async def capacity(*args):
        events.append(('capacity', {}))
        return SimpleNamespace(refresh_allowed=allowed, report=lambda: {'refresh_allowed':allowed})

    def record(name, response=None):
        async def call(*args, **kwargs):
            events.append((name, kwargs))
            if hourly_reports is not None and name in hourly_reports:
                return dict(hourly_reports[name])
            return response if response is not None else {'writes_attempted':1, 'cursor':'new'}
        return call

    async def metadata(pool, actor, source, settings):
        events.append(('metadata', {'source':source}))

    async def wait_for(coroutine, *, timeout):
        assert timeout == 600
        return await coroutine

    async def bulk(*args, **kwargs):
        events.append(('bulk', {}))
        if bulk_error:
            raise RuntimeError('bulk provider failed')

    async def receipt(pool, actor, job, status, report):
        events.append(('receipt', {'job':job, 'status':status, 'report':report}))
        jobs[:] = [prior for prior in jobs if prior['job'] != job]
        jobs.append(dict(job=job, status=status, started_at=module.datetime.now(timezone.utc),
                         report=dict(report)))

    module.__dict__.update(user_connection=user_connection, require_platform_admin=admin,
        check_database_capacity=capacity, EcbHistoricalFxProvider=lambda **kwargs: object(),
        refresh_catalogue_values=record('catalogue_values'),
        refresh_cardmarket_values=record('cardmarket_values'),
        refresh_sealed_prices=record('sealed'), record_coverage=record('coverage'),
        refresh_pokewallet_one_piece=record('one_piece'),
        refresh_pokewallet_dragon_ball=record('dragon_ball'),
        refresh_pokewallet_pokemon=record('pokemon'), receipt=receipt, warm_prices=bulk,
        sync_source=metadata, refresh_exports=record('tcgcsv'),
        asyncio=SimpleNamespace(wait_for=wait_for, TimeoutError=TimeoutError))
    settings = SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()),
        catalogue_price_refresh_limit=40, cardtrader_api_token='test', pokewallet_api_key='fixture',
        pokewallet_pricing_apply_enabled=True, pokewallet_dragon_ball_enabled=True,
        pokewallet_dragon_ball_apply_enabled=True, pokewallet_pokemon_enabled=True,
        pokewallet_pokemon_apply_enabled=True, pokewallet_pricing_request_limit=999,
        pokewallet_dragon_ball_request_limit=999, tcgcsv_free_enabled=False)
    return module, Pool(), settings, events


def complete(coroutine):
    # All fake awaits finish immediately. Any unintended I/O yield fails the test.
    try:
        coroutine.send(None)
    except StopIteration:
        return
    finally:
        coroutine.close()
    raise AssertionError('Scheduler unexpectedly attempted real asynchronous I/O')


def test_hourly_quotes_and_receipts_run_before_bulk_with_unchanged_budget():
    module, pool, settings, events = scheduler()
    complete(module.daily_pass(pool, settings))
    names = [name for name, _ in events]
    for name in ('one_piece', 'dragon_ball', 'pokemon'):
        assert names.index(name) < names.index('bulk')
    assert [(name, data['request_limit']) for name, data in events
            if name in {'one_piece','dragon_ball','pokemon'}] == [
                ('one_piece',10), ('dragon_ball',18), ('pokemon',7)]
    receipts = [(index,data) for index,(name,data) in enumerate(events) if name=='receipt']
    assert len(receipts) == 3
    assert all(index < names.index('bulk') for index,_ in receipts)
    assert all(data['status']=='COMPLETE' for _,data in receipts)
    assert names[-1] == 'unlock'
    assert names.count('coverage') >= 3


def test_long_bulk_failure_does_not_prevent_earlier_hourly_quotes_and_unlocks():
    module, pool, settings, events = scheduler(bulk_error=True)
    with pytest.raises(RuntimeError, match='bulk provider failed'):
        complete(module.daily_pass(pool, settings))
    names = [name for name,_ in events]
    assert names.count('receipt') == 3
    assert names.index('pokemon') < names.index('bulk')
    assert names[-1] == 'unlock'


def test_capacity_guard_still_prevents_every_provider_call():
    module, pool, settings, events = scheduler(allowed=False, sources=('TCGdex',))
    settings.tcgcsv_free_enabled = True
    complete(module.daily_pass(pool, settings))
    assert [name for name,_ in events] == ['lock','admin','capacity','unlock']


def test_completed_current_hour_receipts_prevent_additional_quota_use():
    module, pool, settings, events = scheduler(recent=True)
    complete(module.daily_pass(pool, settings))
    names = [name for name,_ in events]
    assert not {'one_piece','dragon_ball','pokemon','receipt'}.intersection(names)
    assert 'bulk' in names
    assert names[-1] == 'unlock'


@pytest.mark.parametrize('provider', HOURLY_JOBS)
@pytest.mark.parametrize('failure', [
    {'provider_failures':1},
    {'provider_failures':0, 'reason':'SHARED_QUOTA_LOW'},
])
def test_hourly_provider_failures_and_stop_reasons_have_incomplete_receipts(provider, failure):
    report = {'writes_attempted':0, 'cursor':'resume-after-failure', **failure}
    module, pool, settings, events = scheduler(hourly_reports={provider:report})
    complete(module.daily_pass(pool, settings))
    receipts = {data['job']:data for name,data in events if name == 'receipt'}
    failed = receipts[HOURLY_JOBS[provider]]
    assert failed['status'] == 'INCOMPLETE'
    assert all(failed['report'][key] == value for key,value in report.items())
    assert all(data['status'] == 'COMPLETE' for job,data in receipts.items()
               if job != HOURLY_JOBS[provider])
    names = [name for name,_ in events]
    assert set(HOURLY_JOBS).issubset(names)
    assert names.index(provider) < names.index('bulk')
    assert names[-1] == 'unlock'


def test_due_daily_metadata_waits_until_all_hourly_jobs_and_receipts_finish():
    sources = ('TCGdex', 'Bandai Official')
    module, pool, settings, events = scheduler(sources=sources)
    complete(module.daily_pass(pool, settings))
    metadata = [(index,data['source']) for index,(name,data) in enumerate(events)
                if name == 'metadata']
    assert [source for _,source in metadata] == list(sources)
    first_metadata = metadata[0][0]
    hourly = [index for index,(name,_) in enumerate(events) if name in HOURLY_JOBS]
    receipts = [index for index,(name,_) in enumerate(events) if name == 'receipt']
    assert len(hourly) == len(receipts) == 3
    assert max(hourly + receipts) < first_metadata


def test_disabled_tcgcsv_does_not_request_exports_while_other_work_runs():
    module, pool, settings, events = scheduler(sources=('TCGdex',))
    complete(module.daily_pass(pool, settings))
    names = [name for name,_ in events]
    assert 'tcgcsv' not in names
    assert set(HOURLY_JOBS).issubset(names)
    assert 'metadata' in names and 'bulk' in names


@pytest.mark.parametrize('provider', HOURLY_JOBS)
def test_incomplete_hour_waits_for_next_slot_and_resumes_its_saved_cursor(provider):
    report = {'writes_attempted':0, 'provider_failures':1, 'reason':'SHARED_QUOTA_LOW',
              'cursor':'preserved-cursor'}
    module, pool, settings, events = scheduler(hourly_reports={provider:report})
    complete(module.daily_pass(pool, settings))
    events.clear()
    complete(module.daily_pass(pool, settings))
    assert not set(HOURLY_JOBS).intersection(name for name,_ in events)
    assert not any(name == 'receipt' for name,_ in events)

    class NextHourClock(Clock):
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(hours=1)

    module.datetime = NextHourClock
    events.clear()
    complete(module.daily_pass(pool, settings))
    calls = [data for name,data in events if name == provider]
    assert len(calls) == 1
    assert calls[0]['previous_cursor'] == 'preserved-cursor'
    assert len([name for name,_ in events if name in HOURLY_JOBS]) == 3


def test_lower_operator_request_limits_remain_below_hourly_caps():
    module, pool, settings, events = scheduler()
    settings.pokewallet_pricing_request_limit = 4
    settings.pokewallet_dragon_ball_request_limit = 6
    complete(module.daily_pass(pool, settings))
    assert [(name,data['request_limit']) for name,data in events if name in HOURLY_JOBS] == [
        ('one_piece',4), ('dragon_ball',6), ('pokemon',7)]
