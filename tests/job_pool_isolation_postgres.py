"""DR-OPS-1: refresh jobs must not starve the API of database connections.

Real PostgreSQL. Refuses remote/nonempty databases; every record is a disposable
fixture. Reproduces the 27 Nov 2026 incident shape (bulk hold lifted, jobs
holding connections across slow provider calls, more job demand than
connections) and proves:

1. the real ``daily_pass`` runs on the JobDatabase, never on the API pool;
2. while jobs run and the job pool is saturated, an API-style request
   (``user_connection`` on the API pool, as routes and the n8n heartbeat use)
   gets a connection within 1 s;
3. the advisory lock is a real server lock held by the dedicated lock session
   (another replica cannot take it; no pooled connection is pinned);
4. job-pool contention fails with a bounded TimeoutError, never a hang;
5. only one pass ran and its receipt is intact; the lock is released after;
6. negative control: the same job load on the API pool does starve it.
"""
import asyncio
import os
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg

os.environ["DROP_RATE_CATALOGUE_BULK_HOLD"] = "false"  # the incident condition

from app import catalogue_maintenance as maintenance  # noqa: E402
from app.db import create_pool, user_connection  # noqa: E402
from app.job_database import JobDatabase  # noqa: E402
from app.settings import Settings  # noqa: E402

ACTOR = UUID("00000000-0000-0000-0000-000000000001")
DAILY_LOCK = 847220092
API_DEADLINE_SECONDS = 1.0


def settings_for(dsn: str) -> Settings:
    return Settings(
        database_url=dsn,
        auth_issuer="https://example.supabase.co/auth/v1",
        auth_audience="authenticated",
        jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="publishable-test-key",
        environment="jobtest",
        db_pool_min=1,
        db_pool_max=5,  # production API pool size on 27 Nov 2026
        parse_api_key=None,
        ebay_client_id=None,
        ebay_client_secret=None,
        ebay_marketplace_id="EBAY_GB",
        db_job_pool_max=4,
        db_job_acquire_timeout_seconds=5.0,
        catalogue_daily_refresh_enabled=True,
        catalogue_maintenance_actor_user_id=str(ACTOR),
        catalogue_price_refresh_limit=10,
    )


SCHEMA = """
create schema tcg;
create function tcg.current_user_id() returns uuid language sql stable as
  $$select nullif(current_setting('tcg.user_id',true),'')::uuid$$;
create function tcg.is_platform_admin() returns boolean language sql stable as
  $$select tcg.current_user_id()='00000000-0000-0000-0000-000000000001'::uuid$$;
create table tcg.owners(id uuid primary key,display_name text,owner_type text,founder_slot int,active boolean);
create table tcg.owner_memberships(id uuid,user_id uuid,owner_id uuid,role text,active boolean,
  created_at timestamptz default now());
create table tcg.catalogue_job_runs(id uuid primary key default gen_random_uuid(),job text,actor_user_id uuid,
  status text,report jsonb,started_at timestamptz default now(),finished_at timestamptz);
create table tcg.reference_sync_runs(id uuid primary key default gen_random_uuid(),source text,status text,
  sets_loaded int default 0,cards_loaded int default 0,report jsonb,started_at timestamptz default now(),
  finished_at timestamptz);
insert into tcg.owners values('00000000-0000-0000-0000-000000000001','Fixture','FOUNDER',1,true);
insert into tcg.owner_memberships(id,user_id,owner_id,role,active) values(
  '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001','PLATFORM_ADMIN',true);
"""


async def api_request(api_pool, timeout=API_DEADLINE_SECONDS) -> float:
    """What a signed-in catalogue request / n8n heartbeat does: one RLS-scoped tx."""
    started = time.monotonic()
    async with asyncio.timeout(timeout):
        async with user_connection(api_pool, ACTOR, str(uuid4())) as connection:
            await connection.fetchval("select count(*) from tcg.catalogue_job_runs")
    return time.monotonic() - started


async def hog(pool, seconds, outcomes):
    """Worst-case job behaviour: hold a pooled connection across a slow provider call."""
    try:
        async with pool.acquire() as connection:
            await connection.execute("select 1")
            await asyncio.sleep(seconds)
        outcomes.append("held")
    except asyncio.TimeoutError:
        outcomes.append("timeout")


async def main():
    dsn = os.environ["JOB_POOL_TEST_DSN"]
    url = urlsplit(dsn)
    assert url.hostname in {"localhost", "127.0.0.1"} and url.path == "/job_pool_test"
    admin = await asyncpg.connect(dsn)
    assert not await admin.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
    await admin.execute(SCHEMA)
    settings = settings_for(dsn)
    api_pool = await create_pool(settings)
    job_db = await JobDatabase.open(settings)
    pools_seen = []

    async def simulated_refresh(pool, actor, *args, **kwargs):
        # Same shape as the real refreshers: receipt, short DB writes between
        # provider calls that hold no connection, final receipt.
        pools_seen.append(pool)
        run = await maintenance.receipt(pool, actor, "CATALOGUE_VALUES", "RUNNING", {})
        for _ in range(3):
            await asyncio.sleep(0.5)  # provider HTTP
            async with user_connection(pool, actor, str(uuid4())) as connection:
                await connection.execute("select 1")
        await maintenance.receipt(pool, actor, "CATALOGUE_VALUES", "COMPLETE", {"simulated": True}, run)

    async def noop(pool, *args, **kwargs):
        pools_seen.append(pool)
        return {"status": "COMPLETE", "sets": 0, "records": 0}

    maintenance.refresh_catalogue_values = simulated_refresh
    maintenance.refresh_cardmarket_values = noop
    maintenance.sync_source = noop
    maintenance.refresh_sealed_prices = noop
    maintenance.record_coverage = noop
    maintenance.warm_prices = noop
    other_replica = await asyncpg.connect(dsn)
    try:
        # --- Phase 1: real daily_pass x2 + saturating hogs on the job database.
        hog_outcomes = []
        jobs = [
            asyncio.create_task(maintenance.daily_pass(job_db, settings)),
            asyncio.create_task(maintenance.daily_pass(job_db, settings)),
        ]
        await asyncio.sleep(0.2)
        hogs = [asyncio.create_task(hog(job_db, 2.5, hog_outcomes))
                for _ in range(settings.db_job_pool_max + 2)]
        await asyncio.sleep(0.3)

        # Another replica cannot take the daily lock while the pass runs, and
        # the lock is held by the lock session rather than a pooled connection.
        assert await other_replica.fetchval("select pg_try_advisory_lock($1)", DAILY_LOCK) is False
        lock_apps = await admin.fetch(
            """select a.application_name from pg_locks l join pg_stat_activity a using(pid)
               where l.locktype='advisory' and l.objid=$1 and l.granted""", DAILY_LOCK)
        assert [r["application_name"] for r in lock_apps] == ["drop-rate-jobs:jobtest:locks"], lock_apps

        # Job pool is saturated: a further job acquire fails, bounded.
        try:
            async with job_db.acquire(timeout=0.5):
                raise AssertionError("job pool should be saturated by hogs")
        except asyncio.TimeoutError:
            pass

        latencies = []
        while not all(task.done() for task in jobs):
            latencies.append(await api_request(api_pool))
            await asyncio.sleep(0.1)
        await asyncio.gather(*hogs)
        results = await asyncio.gather(*jobs)

        assert len(latencies) >= 5, latencies
        assert max(latencies) < API_DEADLINE_SECONDS, latencies
        assert results == [None, None]
        assert pools_seen and all(pool is job_db for pool in pools_seen)
        assert hog_outcomes.count("held") >= settings.db_job_pool_max
        job_connections = await admin.fetchval(
            "select count(*) from pg_stat_activity where application_name like 'drop-rate-jobs:jobtest%'")
        assert job_connections <= settings.db_job_pool_max + 1, job_connections
        # Exactly one pass ran (the duplicate was refused by the lock) and
        # its receipt is intact.
        receipts = await admin.fetch("select status from tcg.catalogue_job_runs where job='CATALOGUE_VALUES'")
        assert [r["status"] for r in receipts] == ["COMPLETE"], receipts
        # Lock released after the pass.
        assert await other_replica.fetchval("select pg_try_advisory_lock($1)", DAILY_LOCK) is True
        await other_replica.execute("select pg_advisory_unlock($1)", DAILY_LOCK)

        # --- Phase 2 (negative control): the same load on the API pool
        # reproduces the incident: the API cannot get a connection in time.
        api_hogs = [asyncio.create_task(hog(api_pool, 2.0, [])) for _ in range(settings.db_pool_max)]
        await asyncio.sleep(0.3)
        try:
            await api_request(api_pool)
            raise AssertionError("negative control: a shared pool should have starved the API")
        except TimeoutError:
            pass
        await asyncio.gather(*api_hogs)
        assert await api_request(api_pool) < API_DEADLINE_SECONDS
        print(f"job pool isolation ok: {len(latencies)} API requests during refresh, "
              f"max {max(latencies) * 1000:.0f} ms")
    finally:
        await other_replica.close()
        await job_db.close()
        await api_pool.close()
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
