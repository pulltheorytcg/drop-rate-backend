"""Free Supabase quota safety: preserve stock and cached prices on all failures."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.database_capacity import (
    FREE_DATABASE_LIMIT_BYTES, REFRESH_PAUSE_BYTES, URGENT_ALERT_BYTES,
    CAPACITY_SQL, assess_capacity, check_database_capacity,
)


@pytest.mark.parametrize("size,expected,refresh", [
    (0, "OK", True),
    (321_334_419, "OK", True),
    (REFRESH_PAUSE_BYTES - 1, "OK", True),
    (REFRESH_PAUSE_BYTES, "WARNING", False),
    (405_499_027, "WARNING", False),
    (URGENT_ALERT_BYTES - 1, "WARNING", False),
    (URGENT_ALERT_BYTES, "CRITICAL", False),
    (FREE_DATABASE_LIMIT_BYTES, "CRITICAL", False),
    (600_000_000, "CRITICAL", False),
])
def test_exact_free_database_guard_limits(size, expected, refresh):
    state=assess_capacity(size,"off")
    assert state.severity==expected and state.refresh_allowed is refresh
    assert state.report()["database_bytes"]==size
    assert state.report()["remaining_bytes"]==max(0,FREE_DATABASE_LIMIT_BYTES-size)


def test_read_only_overrides_nominal_free_capacity():
    state=assess_capacity(100_000_000,"on")
    assert state.severity=="CRITICAL" and not state.refresh_allowed
    assert state.reason=="DATABASE_READ_ONLY"


@pytest.mark.parametrize("size,mode", [(None,"off"),(-1,"off"),(1.1,"off"),(True,"off"),(100,"bogus")])
def test_invalid_probe_fails_closed(size,mode):
    with pytest.raises(ValueError):assess_capacity(size,mode)


@pytest.mark.asyncio
async def test_real_capacity_sql_does_not_write_or_read_accounts():
    class Conn:
        async def fetchrow(self,sql):
            assert sql==CAPACITY_SQL
            assert "pg_database_size(current_database())" in sql
            assert "current_setting('default_transaction_read_only')" in sql
            assert all(word not in sql.lower() for word in ("insert ","delete ","update ","truncate ","inventory_items","owner_id"))
            return {"database_bytes":405_499_027,"default_read_only":"off"}
    state=await check_database_capacity(Conn())
    assert state.reason=="BULK_REFRESH_DEFERRED_CAPACITY"
    assert not state.refresh_allowed


@pytest.mark.asyncio
async def test_unattended_daily_catalogue_skips_all_imports_over_guard_without_mutating_prices(monkeypatch):
    from app import catalogue_maintenance as jobs
    calls=[]
    class Lock:
        async def fetchval(self,query,*args):
            calls.append(("lock",query));return True
        async def execute(self,query,*args):calls.append(("unlock",query))
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield Lock()
    class Conn:
        async def fetchrow(self,sql):
            assert sql==CAPACITY_SQL
            calls.append(("capacity",sql))
            return {"database_bytes":405_499_027,"default_read_only":"off"}
        async def fetch(self,*args,**kwargs):
            raise AssertionError("No catalogue ingestion or price history writes at 405 MB")
    @asynccontextmanager
    async def fake_user_connection(*args):
        yield Conn()
    async def authorized(*args):
        calls.append(("auth","ok"))
    async def forbidden(*args,**kwargs):
        raise AssertionError("Capacity skip must not start catalogue imports or pricing")
    monkeypatch.setattr(jobs,"user_connection",fake_user_connection)
    monkeypatch.setattr(jobs,"require_platform_admin",authorized)
    for name in ("refresh_catalogue_values","refresh_cardmarket_values",
                 "refresh_sealed_prices","refresh_one_piece_prices",
                 "refresh_dragon_ball_prices","refresh_pokemon_catalogue_prices",
                 "sync_source","warm_prices","record_coverage"):
        monkeypatch.setattr(jobs,name,forbidden)
    await jobs.daily_pass(Pool(),SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4())))
    assert [name for name,_ in calls]==["lock","auth","capacity","unlock"]


def test_operations_monitor_always_includes_capacity_result(monkeypatch,capfd):
    from scripts import run_operations_monitor as monitor
    seen=[]
    def run(filename):
        seen.append(filename)
        return 2 if filename=="check_database_capacity.py" else 0
    monkeypatch.setattr(monitor,"_run_script",run)
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    assert exc.value.code==1
    assert seen[-1]=="check_database_capacity.py"
    assert len(seen)==6
    assert '"capacity_code": 2' in capfd.readouterr().err
