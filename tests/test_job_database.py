"""DR-OPS-1 unit checks for the background-job database handle (no network)."""
import asyncio
from pathlib import Path

import pytest

from app.job_database import JobDatabase, _parse_lock_sql, lock_session

ROOT = Path(__file__).parents[1] / "backend" / "app"
TRY = "select pg_try_advisory_lock($1)"
UNLOCK = "select pg_advisory_unlock($1)"


class FakeSession:
    def __init__(self, busy=()):
        self.calls = []
        self.closed = False
        self.busy = set(busy)  # held by "another replica"

    def is_closed(self):
        return self.closed

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return not ("try_advisory" in sql and (args[0] if args else sql) in self.busy)

    async def close(self):
        self.closed = True


class FakePool:
    def __init__(self):
        self.timeouts = []
        self.closed = False

    def acquire(self, *, timeout=None):
        self.timeouts.append(timeout)
        return "ctx"

    def get_max_size(self):
        return 4

    async def close(self):
        self.closed = True


def job_db(sessions, busy=()):
    async def connect():
        session = FakeSession(busy)
        sessions.append(session)
        return session
    return JobDatabase(FakePool(), lock_connect=connect, acquire_timeout=30.0)


def lock_sql(session):
    return [sql for sql, _ in session.calls]


@pytest.mark.asyncio
async def test_one_lock_session_serves_every_job_and_refuses_local_duplicates():
    sessions = []
    db = job_db(sessions)
    async with lock_session(db) as first, lock_session(db) as second, lock_session(db) as third:
        assert await first.fetchval(TRY, 847220092) is True
        # Session locks are re-entrant in PostgreSQL; a second local job must
        # still be refused, exactly as a second pooled session used to be.
        assert await second.fetchval(TRY, 847220092) is False
        assert await third.fetchval(TRY, 847220093) is True
        await first.execute(UNLOCK, 847220092)
        assert await second.fetchval(TRY, 847220092) is True
    assert len(sessions) == 1
    assert lock_sql(sessions[0]).count(TRY) == 3
    # second (847220092) and third (847220093) released on block exit.
    assert lock_sql(sessions[0]).count(UNLOCK) == 3
    assert db._held == set()


@pytest.mark.asyncio
async def test_literal_and_parameter_keys_are_the_same_lock():
    sessions = []
    db = job_db(sessions)
    async with lock_session(db) as a, lock_session(db) as b:
        assert await a.fetchval("select pg_try_advisory_lock(847220121)") is True
        assert await b.fetchval(TRY, 847220121) is False
        await a.execute("select pg_advisory_unlock(847220121)")
    assert _parse_lock_sql("SELECT pg_try_advisory_lock(hashtextextended($1,0))", ("k",))[1] == (
        "hashtextextended($1,0)", ("k",))


@pytest.mark.asyncio
async def test_lock_held_by_another_replica_is_reported_and_never_unlocked_here():
    sessions = []
    db = job_db(sessions, busy={7})
    async with lock_session(db) as lock:
        assert await lock.fetchval(TRY, 7) is False
        assert await lock.fetchval(UNLOCK, 7) is False
    assert (UNLOCK, (7,)) not in sessions[0].calls


@pytest.mark.asyncio
async def test_lock_handle_rejects_ordinary_queries():
    db = job_db([])
    async with lock_session(db) as lock:
        with pytest.raises(TypeError):
            await lock.fetchval("select pg_database_size(current_database())")


@pytest.mark.asyncio
async def test_lost_lock_session_reconnects_and_forgets_released_locks():
    sessions = []
    db = job_db(sessions)
    async with lock_session(db) as daily:
        assert await daily.fetchval(TRY, 1)
        sessions[0].closed = True  # server dropped the session: lock released
        async with lock_session(db) as other:
            assert await other.fetchval(TRY, 2) is True
    assert len(sessions) == 2
    async with lock_session(db) as again:
        assert await again.fetchval(TRY, 1) is True


@pytest.mark.asyncio
async def test_cancelled_job_still_releases_its_lock():
    sessions = []
    db = job_db(sessions)
    started = asyncio.Event()

    async def job():
        async with lock_session(db) as lock:
            assert await lock.fetchval(TRY, 5)
            started.set()
            await asyncio.sleep(60)  # provider call

    task = asyncio.create_task(job())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert db._held == set()
    assert (UNLOCK, (5,)) in sessions[0].calls


@pytest.mark.asyncio
async def test_acquire_is_bounded_and_close_releases_everything():
    sessions = []
    db = job_db(sessions)
    db.acquire()
    db.acquire(timeout=1)
    assert db._pool.timeouts == [30.0, 1]
    assert db.get_max_size() == 4
    async with lock_session(db) as lock:
        await lock.fetchval(TRY, 1)
    await db.close()
    assert sessions[0].closed and db._pool.closed


@pytest.mark.asyncio
async def test_plain_pool_keeps_the_previous_connection_behaviour():
    seen = []

    class Acquire:
        async def __aenter__(self):
            return "pooled-connection"

        async def __aexit__(self, *exc):
            return False

    class Pool:
        def acquire(self, **kwargs):
            seen.append(kwargs)
            return Acquire()

    async with lock_session(Pool()) as lock:
        assert lock == "pooled-connection"
    async with lock_session(Pool(), timeout=15) as lock:
        assert lock == "pooled-connection"
    assert seen == [{}, {"timeout": 15}]


def test_startup_background_tasks_never_receive_the_api_pool():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    lifespan = main[main.index("async def lifespan"):main.index("            yield")]
    job_section = lifespan[lifespan.index("JobDatabase.open"):]
    assert "app.state.db_pool" not in job_section
    for job in ("r2_first_service.prewarm(", "r2_first_import.run_loop(", "catalogue_r2_live.prewarm(",
                "catalogue_r2_market.prewarm(", "run_shopify_waitlist_sync(", "run_reference_mirror_loop(",
                "run_loop(job_db", "run_live_market_refresh(job_db", "run_shopify_catalogue_bootstrap(job_db",
                "run_linked_draft_reconciliation(job_db"):
        assert job in job_section, job


@pytest.mark.parametrize("module", [
    "catalogue_maintenance.py", "catalogue_r2_live.py", "catalogue_r2_market.py",
    "live_market_refresh.py", "r2_first_import.py", "r2_reference_images.py",
    "reference_history_archive.py",
])
def test_background_job_locks_use_the_shared_lock_session(module):
    source = (ROOT / module).read_text(encoding="utf-8")
    assert "lock_session(pool" in source
    assert "pool.acquire() as lock" not in source
    assert "pool.acquire(timeout=15) as lock" not in source
