"""Fixed-snapshot operator guards and outer-transaction failure semantics."""
import sqlite3
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.book_bulk_import import ImportPaused
from scripts import apply_reviewed_openlibrary_pilot as pilot


def test_operator_uses_only_the_reviewed_sha_and_exact_row_count():
    state=pilot.open_stage(":memory:")
    try:
        report=pilot.stage_reviewed_snapshot(state)
        assert report["statuses"]=={"READY":32}
        assert not state.execute("select 1 from records where status<>'READY'").fetchone()
    finally:
        state.close()


def test_operator_rejects_modified_snapshot_before_database_access(tmp_path,monkeypatch):
    source=tmp_path/"modified.jsonl"
    source.write_bytes(pilot.SNAPSHOT_PATH.read_bytes()+b"\n")
    monkeypatch.setattr(pilot,"SNAPSHOT_PATH",source)
    state=pilot.open_stage(":memory:")
    try:
        with pytest.raises(ImportPaused,match="BOOK_PILOT_SNAPSHOT_MISMATCH"):
            pilot.stage_reviewed_snapshot(state)
        assert not state.execute("select 1 from records").fetchone()
    finally:
        state.close()


def operator_fakes(monkeypatch, *, deny=False, commit_failure=False, capacity=True):
    events=[];states=[]
    original_open=pilot.open_stage
    def open_stage(path):
        assert path==":memory:"
        state=original_open(path);states.append(state);return state
    @asynccontextmanager
    async def connection(pool,actor,request_id):
        events.append("begin")
        try:
            yield SimpleNamespace(fetchval=AsyncMock(return_value="tcg_api"))
            if commit_failure:
                raise RuntimeError("commit failed")
            events.append("commit")
        except BaseException:
            events.append("rollback")
            raise
    async def admin(conn):
        events.append("admin")
        if deny:
            raise HTTPException(403,"denied")
        return {"access_role":"PLATFORM_ADMIN"}
    async def apply(conn,state,*,batch_size,max_batches):
        assert batch_size==32 and max_batches==1
        events.append("apply")
        return {"statuses":{"IMPORTED":32}}
    monkeypatch.setattr(pilot,"open_stage",open_stage)
    monkeypatch.setattr(pilot,"user_connection",connection)
    monkeypatch.setattr(pilot,"require_platform_admin",admin)
    monkeypatch.setattr(pilot,"capacity_plan",AsyncMock(return_value={"whole_stage_fits_reserve":capacity}))
    monkeypatch.setattr(pilot,"apply_stage",apply)
    return events,states


def assert_closed(states):
    assert len(states)==1
    with pytest.raises(sqlite3.ProgrammingError):
        states[0].execute("select 1")


@pytest.mark.asyncio
async def test_dry_run_authorizes_and_checks_capacity_without_applying(monkeypatch):
    events,states=operator_fakes(monkeypatch)
    report=await pilot.run_with_pool(object(),uuid4())
    assert report["dry_run"] is True and report["committed"] is False
    assert events==["begin","admin","commit"]
    assert_closed(states)


@pytest.mark.asyncio
async def test_apply_result_is_returned_only_after_outer_commit(monkeypatch):
    events,states=operator_fakes(monkeypatch)
    report=await pilot.run_with_pool(object(),uuid4(),apply=True)
    assert events==["begin","admin","apply","commit"]
    assert report["committed"] is True and report["result"]["statuses"]=={"IMPORTED":32}
    assert_closed(states)


@pytest.mark.asyncio
async def test_failed_outer_commit_discards_checkpoint_and_emits_no_success(monkeypatch,capsys):
    events,states=operator_fakes(monkeypatch,commit_failure=True)
    with pytest.raises(RuntimeError,match="commit failed"):
        await pilot.run_with_pool(object(),uuid4(),apply=True)
    assert events==["begin","admin","apply","rollback"]
    assert capsys.readouterr().out==""
    assert_closed(states)


@pytest.mark.asyncio
@pytest.mark.parametrize("deny,capacity,error",[(True,True,HTTPException),(False,False,ImportPaused)])
async def test_unauthorized_or_over_capacity_run_never_applies(monkeypatch,deny,capacity,error):
    events,states=operator_fakes(monkeypatch,deny=deny,capacity=capacity)
    with pytest.raises(error):
        await pilot.run_with_pool(object(),uuid4(),apply=True)
    assert "apply" not in events and "commit" not in events
    assert_closed(states)


@pytest.mark.asyncio
async def test_missing_configured_actor_never_opens_database(monkeypatch):
    monkeypatch.setattr(pilot,"get_settings",lambda:SimpleNamespace(catalogue_maintenance_actor_user_id=None))
    pool=AsyncMock();monkeypatch.setattr(pilot,"create_pool",pool)
    with pytest.raises(ImportPaused,match="MAINTENANCE_ACTOR_REQUIRED"):
        await pilot.run(apply=True)
    pool.assert_not_called()

