"""Maintenance must return to pricing after a stalled optional publication."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import catalogue_maintenance as jobs


def configure(monkeypatch):
    monkeypatch.setattr(jobs, "archive_check_window", lambda now: None)
    monkeypatch.setattr(jobs.catalogue_r2_live, "enabled", lambda name: name == "BUILD")
    monkeypatch.setattr(jobs, "R2_PUBLICATION_TIMEOUT_SECONDS", 0.01)
    return SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()))


@pytest.mark.asyncio
async def test_timeout_cleans_up_before_pricing_and_backs_off(monkeypatch, caplog):
    settings = configure(monkeypatch)
    events = []
    real_sleep = asyncio.sleep

    async def pricing(*args):
        events.append("pricing")
        if events.count("pricing") == 3:
            raise asyncio.CancelledError

    async def publish(*args):
        events.append("publish")
        try:
            await asyncio.Future()
        finally:
            await real_sleep(0)
            events.append("cleanup")

    async def sleep(delay):
        assert delay == 300
        assert events.index("cleanup") > events.index("publish")
        await real_sleep(0)

    monkeypatch.setattr(jobs, "daily_pass", pricing)
    monkeypatch.setattr(jobs.catalogue_r2_live, "publish", publish)
    monkeypatch.setattr(jobs.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(jobs.run_loop(object(), settings), timeout=1)
    assert events == ["pricing", "publish", "cleanup", "pricing", "pricing"]
    assert "CATALOGUE_R2_LIVE_PUBLICATION_TIMEOUT" in caplog.text


@pytest.mark.asyncio
async def test_shutdown_cancellation_is_not_converted_to_retry(monkeypatch):
    settings = configure(monkeypatch)
    monkeypatch.setattr(jobs, "R2_PUBLICATION_TIMEOUT_SECONDS", 60)
    entered = asyncio.Event()
    cleaned = asyncio.Event()
    passes = []

    async def pricing(*args):
        passes.append(1)

    async def publish(*args):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cleaned.set()

    monkeypatch.setattr(jobs, "daily_pass", pricing)
    monkeypatch.setattr(jobs.catalogue_r2_live, "publish", publish)
    task = asyncio.create_task(jobs.run_loop(object(), settings))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert cleaned.is_set()
        assert passes == [1]
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_publication_failure_backs_off_but_success_keeps_normal_cadence(monkeypatch):
    settings = configure(monkeypatch)
    real_sleep = asyncio.sleep
    for failed in (False, True):
        events = []

        async def pricing(*args):
            events.append("pricing")
            if events.count("pricing") == 3:
                raise asyncio.CancelledError

        async def publish(*args):
            events.append("publish")
            if failed:
                raise ValueError("invalid publication")
            return {"status": "CURRENT"}

        async def sleep(delay):
            await real_sleep(0)

        monkeypatch.setattr(jobs, "daily_pass", pricing)
        monkeypatch.setattr(jobs.catalogue_r2_live, "publish", publish)
        monkeypatch.setattr(jobs.asyncio, "sleep", sleep)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(jobs.run_loop(object(), settings), timeout=1)
        assert events.count("pricing") == 3
        assert events.count("publish") == (1 if failed else 2)
