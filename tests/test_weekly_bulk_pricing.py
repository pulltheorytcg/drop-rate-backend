"""Weekly bulk pricing while daily source sync, individual search, Shopify stay separate."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app import catalogue_maintenance as jobs
from app.database_capacity import assess_capacity


def complete(at, revision=1):
    return {"status": "COMPLETE", "started_at": at, "report": {"importer_revision": revision}}


def test_monday_03_uk_weekly_slot_and_bst_switch():
    assert jobs.weekly_price_slot(datetime(2026,10,16,8,tzinfo=timezone.utc)) == datetime(2026,10,12,2,tzinfo=timezone.utc)
    assert jobs.weekly_price_slot(datetime(2026,10,19,1,59,tzinfo=timezone.utc)) == datetime(2026,10,12,2,tzinfo=timezone.utc)
    assert jobs.weekly_price_slot(datetime(2026,10,19,2,tzinfo=timezone.utc)) == datetime(2026,10,19,2,tzinfo=timezone.utc)
    assert jobs.weekly_price_slot(datetime(2026,10,26,2,59,tzinfo=timezone.utc)) == datetime(2026,10,19,2,tzinfo=timezone.utc)
    assert jobs.weekly_price_slot(datetime(2026,10,26,3,tzinfo=timezone.utc)) == datetime(2026,10,26,3,tzinfo=timezone.utc)
    assert jobs.weekly_price_slot(datetime(2027,3,29,2,tzinfo=timezone.utc)) == datetime(2027,3,29,2,tzinfo=timezone.utc)


@pytest.mark.parametrize("now,is_due", [
    (datetime(2026,10,16,8,tzinfo=timezone.utc), False),
    (datetime(2026,10,18,15,tzinfo=timezone.utc), False),
    (datetime(2026,10,19,1,59,tzinfo=timezone.utc), False),
    (datetime(2026,10,19,2,tzinfo=timezone.utc), True),
    (datetime(2026,10,20,12,tzinfo=timezone.utc), True),
])
def test_completed_bulk_reference_job_only_renews_after_next_monday(now,is_due):
    last=complete(datetime(2026,10,15,2,40,tzinfo=timezone.utc),22)
    assert jobs.weekly_price_due(last,now,revision=22) is is_due
    # A source-mapping code change does not force another heavy price refresh
    # off-schedule when we already priced within this weekly slot.
    if not is_due:
        assert not jobs.weekly_price_due(last,now,revision=23)


def test_successful_current_monday_does_not_repeat_until_following_week():
    first=datetime(2026,10,19,2,10,tzinfo=timezone.utc)
    assert not jobs.weekly_price_due(complete(first,4),
                                    first+timedelta(minutes=7), revision=5)
    assert not jobs.weekly_price_due(complete(first,4),
                                    first+timedelta(days=6), revision=5)
    assert jobs.weekly_price_due(complete(first,4),
                                 datetime(2026,10,26,3,tzinfo=timezone.utc), revision=5)


def test_interrupted_and_first_time_work_are_not_abandoned():
    now=datetime(2026,10,16,10,tzinfo=timezone.utc)
    assert jobs.weekly_price_due(None,now)
    assert not jobs.weekly_price_due(
        {"status":"RUNNING","started_at":now-timedelta(minutes=20),"report":{}}, now)
    assert jobs.weekly_price_due(
        {"status":"FAILED","started_at":now-timedelta(hours=2),"report":{}}, now)
    progress={"status":"INCOMPLETE","started_at":now,
              "report":{"more_due_at_start":True,"provider_failures":0,
                        "pokemon_catalogue":{"provider_failures":0},
                        "one_piece":{"provider_failures":0},
                        "dragon_ball":{"provider_failures":0}}}
    assert jobs.weekly_price_due(progress,now)


@pytest.mark.asyncio
@pytest.mark.parametrize("monday", [False,True])
async def test_railway_loop_only_runs_market_price_jobs_once_weekly_and_keeps_daily_source_separate(monkeypatch,monday):
    now=(datetime(2026,10,19,2,5,tzinfo=timezone.utc)
         if monday else datetime(2026,10,16,10,tzinfo=timezone.utc))
    last=datetime(2026,10,15,2,30,tzinfo=timezone.utc)
    events=[]

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is not None else now.replace(tzinfo=None)

    class Lock:
        async def fetchval(self,sql,*args):
            assert "pg_try_advisory_lock" in sql
            return True
        async def execute(self,sql,*args):
            assert "pg_advisory_unlock" in sql
            events.append("unlock")

    class Pool:
        @asynccontextmanager
        async def acquire(self):yield Lock()

    class Connection:
        async def fetch(self,sql):
            if "reference_sync_runs" in sql:
                # Source references are current, not due for a daily sync.
                return [
                    {"source":source,"started_at":now,"status":"COMPLETE",
                     "report":{"importer_revision":jobs.SOURCE_REVISIONS.get(source,1)}}
                    for source in jobs.SOURCES
                ]
            assert "catalogue_job_runs" in sql
            revisions={
                "REFERENCE_PRICES":jobs.REFERENCE_JOB_REVISION,
                "SEALED_REFERENCE_PRICES":jobs.SEALED_MARKET_REVISION,
                "CATALOGUE_VALUES":jobs.CATALOGUE_VALUE_REVISION,
                "CARDMARKET_VALUES":jobs.CARDMARKET_VALUE_REVISION,
                "CATALOGUE_COVERAGE":1,
            }
            return [
                {"job":job,"started_at":(last if job!="CATALOGUE_COVERAGE" else now),
                 "status":"COMPLETE","report":{"importer_revision":revision}}
                for job,revision in revisions.items()
            ]

    @asynccontextmanager
    async def connect(*args):
        yield Connection()

    async def authorized(*args):pass
    async def safe_capacity(_):
        events.append("capacity")
        return assess_capacity(321_334_419,"off")
    def record(label):
        async def fn(*args,**kwargs):
            events.append(label)
        return fn

    monkeypatch.setattr(jobs,"datetime",FrozenDatetime)
    monkeypatch.setattr(jobs,"user_connection",connect)
    monkeypatch.setattr(jobs,"require_platform_admin",authorized)
    monkeypatch.setattr(jobs,"check_database_capacity",safe_capacity)
    monkeypatch.setattr(jobs,"refresh_catalogue_values",record("catalogue"))
    monkeypatch.setattr(jobs,"refresh_cardmarket_values",record("cardmarket"))
    monkeypatch.setattr(jobs,"refresh_sealed_prices",record("sealed"))
    monkeypatch.setattr(jobs,"warm_prices",record("reference"))
    monkeypatch.setattr(jobs,"record_coverage",record("coverage"))
    monkeypatch.setattr(jobs,"sync_source",record("source"))

    await jobs.daily_pass(Pool(),SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()), catalogue_price_refresh_limit=20000))
    assert events[0]=="capacity" and events[-1]=="unlock"
    if not monday:
        assert events==["capacity","unlock"],"A Friday loop must not rewrite bulk price history"
    else:
        assert events==["capacity","catalogue","cardmarket","sealed","coverage",
                        "reference","cardmarket","coverage","unlock"]


@pytest.mark.asyncio
async def test_no_chance_of_price_refresh_during_full_database_capacity_pause(monkeypatch):
    events=[]
    class Lock:
        async def fetchval(self,sql,*args):return True
        async def execute(self,sql,*args):events.append("unlock")
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield Lock()
    class Connection:
        async def fetch(self,*args):raise AssertionError("Blocked before any bulk work")
    @asynccontextmanager
    async def connect(*args):yield Connection()
    async def good(*args):return
    async def over_capacity(*args):
        return assess_capacity(405_499_027,"off")
    async def forbidden(*args,**kwargs):
        raise AssertionError("No bulk price/Shopify/history writes with Free database above 400MB")
    monkeypatch.setattr(jobs,"user_connection",connect)
    monkeypatch.setattr(jobs,"require_platform_admin",good)
    monkeypatch.setattr(jobs,"check_database_capacity",over_capacity)
    for fn in ("refresh_catalogue_values","refresh_cardmarket_values","sync_source",
               "refresh_sealed_prices","warm_prices","record_coverage"):
        monkeypatch.setattr(jobs,fn,forbidden)
    await jobs.daily_pass(Pool(),SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4())))
    assert events==["unlock"]
