"""Daily archival backlog warning cannot purge history or confer backup authority."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import archive_backlog as backlog
from app import catalogue_maintenance as maintenance


@pytest.mark.parametrize("now,expected", [
    ("2026-10-16T10:00:00+00:00", None),
    ("2026-10-17T02:59:59+00:00", None),
    ("2026-10-17T05:59:59+00:00", None),
    ("2026-10-17T06:00:00+00:00", "2026-10-17T03:00:00+00:00"),
    ("2026-10-18T05:00:00+00:00", "2026-10-17T03:00:00+00:00"),
    ("2026-10-18T06:00:00+00:00", "2026-10-18T03:00:00+00:00"),
    ("2026-10-25T06:59:59+00:00", "2026-10-24T03:00:00+00:00"),
    ("2026-10-25T07:00:00+00:00", "2026-10-25T04:00:00+00:00"),
    ("2026-10-26T07:00:00+00:00", "2026-10-26T04:00:00+00:00"),
])
def test_verified_archive_watch_window_is_uk_local_and_has_three_hour_grace(now,expected):
    instant = datetime.fromisoformat(now)
    actual = backlog.archive_check_window(instant)
    assert (actual.isoformat() if actual else None) == expected


def test_reject_naive_clock():
    with pytest.raises(ValueError, match="timezone-aware"):
        backlog.archive_check_window(datetime(2026,10,17,8))


def test_overdue_history_is_not_confused_with_a_verified_backup():
    cutoff=datetime.fromisoformat("2026-10-17T03:00:00+00:00")
    old=datetime.fromisoformat("2026-10-15T02:18:49+00:00")
    report=backlog.assess_archive_backlog(50378,old,cutoff)
    assert report["status"]=="OVERDUE" and report["pending_rows"]==50378
    assert "never proof" in report["note"]
    report=backlog.assess_archive_backlog(1,cutoff,cutoff)
    assert report["status"]=="OVERDUE", "Inclusive cutoff must not hide backlog"
    current=backlog.assess_archive_backlog(4,cutoff.replace(day=18),cutoff)
    assert current["status"]=="CURRENT"
    clean=backlog.assess_archive_backlog(0,None,cutoff)
    assert clean["status"]=="CLEAR"


@pytest.mark.parametrize("count,oldest", [
    (-1,None),(True,None),(0,datetime.now(timezone.utc)),
    (1,None),(1,datetime(2026,10,17)),
])
def test_invalid_archive_evidence_fails_closed(count,oldest):
    with pytest.raises(ValueError):
        backlog.assess_archive_backlog(
            count,oldest,datetime(2026,10,17,3,tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_history_probe_is_admin_scoped_select_only(monkeypatch):
    calls=[]
    actor=uuid4()
    class Connection:
        async def fetchrow(self,sql):
            calls.append(sql)
            assert sql==backlog.BACKLOG_SQL
            assert "from tcg.reference_market_history" in sql
            for forbidden in ("update ","delete ","truncate ","insert ","tcg.inventory_items",
                              "tcg.reference_history_archives","pg_read_file"):
                assert forbidden not in sql.lower()
            return {"pending_rows":50378,
                    "oldest_pending_at":datetime(2026,10,15,2,18,tzinfo=timezone.utc),
                    "newest_pending_at":datetime(2026,10,15,2,51,tzinfo=timezone.utc)}
    @asynccontextmanager
    async def fake_connection(_pool,uid,_request_id):
        assert uid==actor
        yield Connection()
    async def admin(_):
        calls.append("authorized")
    monkeypatch.setattr(backlog,"user_connection",fake_connection)
    monkeypatch.setattr(backlog,"require_platform_admin",admin)
    result=await backlog.check_archive_backlog(
        object(),actor,datetime(2026,10,17,3,tzinfo=timezone.utc))
    assert result["status"]=="OVERDUE"
    assert calls[0]=="authorized" and len(calls)==2


@pytest.mark.asyncio
async def test_weekly_pricing_loop_logs_daily_archive_backlog_and_never_runs_cleanup(monkeypatch,caplog):
    events=[]
    archive_window=datetime(2026,10,17,3,tzinfo=timezone.utc)
    monkeypatch.setattr(maintenance,"archive_check_window",lambda _:archive_window)
    async def probe(*args):
        events.append("archive-read")
        return {"status":"OVERDUE","pending_rows":50378}
    async def daily(*args):
        events.append("normal-catalogue-pass")
    async def no_sleep(*args):
        raise asyncio.CancelledError
    monkeypatch.setattr(maintenance,"check_archive_backlog",probe)
    monkeypatch.setattr(maintenance,"daily_pass",daily)
    monkeypatch.setattr(maintenance.asyncio,"sleep",no_sleep)
    settings=SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()))
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(),settings)
    assert events==["archive-read","normal-catalogue-pass"]
    assert "CATALOGUE_ARCHIVE_BACKLOG_OVERDUE" in caplog.text
    assert "50378" in caplog.text


@pytest.mark.asyncio
async def test_failed_archive_probe_does_not_disable_shopify_or_existing_catalogue_guards(monkeypatch,caplog):
    events=[]
    monkeypatch.setattr(maintenance,"archive_check_window",
                        lambda _: datetime(2026,10,17,3,tzinfo=timezone.utc))
    async def probe(*args):
        events.append("archive-probe-failed")
        raise PermissionError("Do not expose DB role in logs")
    async def daily(*args):
        events.append("existing-guarded-pass")
    async def no_sleep(*args):
        raise asyncio.CancelledError
    monkeypatch.setattr(maintenance,"check_archive_backlog",probe)
    monkeypatch.setattr(maintenance,"daily_pass",daily)
    monkeypatch.setattr(maintenance.asyncio,"sleep",no_sleep)
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(),SimpleNamespace(
            catalogue_maintenance_actor_user_id=str(uuid4())))
    assert events==["archive-probe-failed","existing-guarded-pass"]
    assert "CATALOGUE_ARCHIVE_BACKLOG_CHECK_FAILED type=PermissionError" in caplog.text
    assert "Do not expose DB role" not in caplog.text

@pytest.mark.asyncio
async def test_r2_archive_runs_before_capacity_guard_and_only_once_per_hour(monkeypatch):
    events=[]
    async def archive(_pool, actor, *, cleanup):
        events.append(("archive", cleanup))
        return {"status":"BYTES_AND_RESTORE_VERIFIED","row_count":3}
    async def daily(*args):
        events.append(("capacity-guarded-pass", None))
    sleeps=0
    async def no_sleep(*args):
        nonlocal sleeps
        sleeps+=1
        if sleeps==2:
            raise asyncio.CancelledError
    monkeypatch.setattr(maintenance,"archive_reference_history",archive)
    monkeypatch.setattr(maintenance,"daily_pass",daily)
    monkeypatch.setattr(maintenance,"archive_check_window",lambda _:None)
    monkeypatch.setattr(maintenance.asyncio,"sleep",no_sleep)
    settings=SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()),
        history_r2_archive_enabled=True,history_r2_archive_cleanup_enabled=False)
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(),settings)
    assert events==[("archive",False),("capacity-guarded-pass",None),("capacity-guarded-pass",None)]


@pytest.mark.asyncio
async def test_r2_archive_failure_preserves_capacity_guard_and_redacts_error(monkeypatch,caplog):
    events=[]
    async def archive(*args,**kwargs):
        events.append("archive")
        raise RuntimeError("SECRET-credential-host")
    async def daily(*args):
        events.append("guarded-pass")
    async def no_sleep(*args):
        raise asyncio.CancelledError
    monkeypatch.setattr(maintenance,"archive_reference_history",archive)
    monkeypatch.setattr(maintenance,"daily_pass",daily)
    monkeypatch.setattr(maintenance,"archive_check_window",lambda _:None)
    monkeypatch.setattr(maintenance.asyncio,"sleep",no_sleep)
    settings=SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()),
        history_r2_archive_enabled=True,history_r2_archive_cleanup_enabled=True)
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(),settings)
    assert events==["archive","guarded-pass"]
    assert "CATALOGUE_R2_HISTORY_ARCHIVE_FAILED type=RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text


@pytest.mark.asyncio
async def test_shopify_loop_never_runs_r2_archive(monkeypatch):
    async def forbidden(*args,**kwargs):
        pytest.fail("Shopify reconciliation attempted history archival")
    async def shopify(*args):
        pass
    async def no_sleep(*args):
        raise asyncio.CancelledError
    monkeypatch.setattr(maintenance,"archive_reference_history",forbidden)
    monkeypatch.setattr(maintenance,"shopify_pass",shopify)
    monkeypatch.setattr(maintenance.asyncio,"sleep",no_sleep)
    settings=SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()),
        history_r2_archive_enabled=True,history_r2_archive_cleanup_enabled=True)
    with pytest.raises(asyncio.CancelledError):
        await maintenance.run_loop(object(),settings,shopify=True)
