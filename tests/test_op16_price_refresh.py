from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app import op16_price_refresh as operator


class Pool:
    def __init__(self, available=True):
        self.available = available
        self.lock_calls = []

    @asynccontextmanager
    async def acquire(self):
        yield self

    async def fetchval(self, sql, *args):
        assert args == (847220092,)
        self.lock_calls.append(sql)
        return self.available


def arrange(monkeypatch, *, allowed=True, committed=(), result=None, failure=None):
    state = {"receipts": [], "updates": [], "refresh": [], "admin": 0, "reads": []}

    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetchval(self, sql):
                assert "reference_sync_runs" in sql and "'op16_catalogue_prices'" in sql
                state["receipts"].append(sql)
                return 123

            async def fetch(self, sql, *params):
                assert sql == operator.READBACK_SQL
                assert params[0] == operator.SOURCE
                state["reads"].append(params)
                return list(committed)

            async def execute(self, sql, *params):
                assert "update tcg.reference_sync_runs" in sql
                state["updates"].append(params)
        yield Conn()

    async def admin(connection):
        state["admin"] += 1

    async def capacity(connection):
        class Capacity:
            refresh_allowed = allowed

            def report(self):
                return {"refresh_allowed": allowed}
        return Capacity()

    async def refresh(*args, **kwargs):
        state["refresh"].append(kwargs)
        if failure:
            raise failure
        return result or {"eligible_quotes": 2, "writes_attempted": 2,
                          "provider_failures": 0, "preview": [{"provider_id": "OP16-001"}]}

    monkeypatch.setattr(operator, "user_connection", connection)
    monkeypatch.setattr(operator, "require_platform_admin", admin)
    monkeypatch.setattr(operator, "check_database_capacity", capacity)
    monkeypatch.setattr(operator, "refresh_pokewallet_one_piece", refresh)
    return state


@pytest.mark.asyncio
async def test_dry_run_is_default_and_has_no_receipt_or_price_write(monkeypatch):
    state = arrange(monkeypatch)
    pool = Pool()
    report = await operator.refresh_op16(pool, uuid4(), object(), "fixture")
    assert report["status"] == "VERIFIED" and report["written"] == 0
    assert not state["receipts"] and not state["reads"] and not state["updates"]
    assert state["refresh"][0]["dry_run"] is True
    assert state["refresh"][0]["request_limit"] == 10
    assert state["refresh"][0]["reference_set_id"] == "569116"
    assert pool.lock_calls[-1] == "select pg_advisory_unlock($1)"


@pytest.mark.asyncio
async def test_apply_counts_committed_rows_not_attempts_and_records_receipt(monkeypatch):
    state = arrange(monkeypatch, committed=[{"provider_id": "OP16-001", "market_value_minor": 100}])
    report = await operator.refresh_op16(Pool(), uuid4(), object(), "fixture", apply=True)
    assert report["status"] == "INCOMPLETE"  # one of two attempted rows survived the SQL guards
    assert report["written"] == 1 and report["writes_attempted"] == 2
    assert report["readback_verified"] and not report["write_outcome_unknown"]
    assert report["receipt_finalized"] and report["receipt_id"] == "123"
    assert state["reads"][0][1] == state["refresh"][0]["operator_run_id"]
    assert state["updates"][0][:3] == (123, "INCOMPLETE", 1)
    assert state["updates"][0][3]["written"] == 1


@pytest.mark.asyncio
async def test_complete_apply_requires_committed_readback(monkeypatch):
    state = arrange(monkeypatch, committed=[{"provider_id": "OP16-001"}, {"provider_id": "OP16-002"}])
    report = await operator.refresh_op16(Pool(), uuid4(), object(), "fixture", apply=True)
    assert report["status"] == "COMPLETE" and report["written"] == 2
    assert state["updates"][0][:3] == (123, "COMPLETE", 2)


@pytest.mark.asyncio
async def test_interruption_reads_back_partial_commits_and_keeps_incomplete_receipt(monkeypatch):
    state = arrange(monkeypatch, committed=[{"provider_id": "OP16-001"}], failure=TimeoutError())
    pool = Pool()
    report = await operator.refresh_op16(pool, uuid4(), object(), "fixture", apply=True)
    assert report["status"] == "INTERRUPTED" and report["written"] == 1
    assert report["readback_verified"] and report["receipt_finalized"]
    assert state["updates"][0][:3] == (123, "INCOMPLETE", 1)
    assert pool.lock_calls[-1] == "select pg_advisory_unlock($1)"


@pytest.mark.asyncio
@pytest.mark.parametrize("available,allowed,status",[(False,True,"BUSY"),(True,False,"CAPACITY_BLOCKED")])
async def test_global_lock_and_capacity_block_provider_requests(monkeypatch,available,allowed,status):
    state = arrange(monkeypatch, allowed=allowed)
    report = await operator.refresh_op16(Pool(available), uuid4(), object(), "fixture", apply=True)
    assert report["status"] == status
    assert not state["refresh"] and not state["receipts"]
