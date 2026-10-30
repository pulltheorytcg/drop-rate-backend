"""Maintenance errors should expose a safe source location, not SQL or tokens."""
import asyncio
from types import SimpleNamespace

import pytest

from app import catalogue_maintenance as jobs


@pytest.mark.asyncio
async def test_worker_exception_logs_safe_stage_without_provider_text(monkeypatch, caplog):
    monkeypatch.setattr(jobs, "archive_check_window", lambda now: None)
    monkeypatch.setattr(jobs.catalogue_r2_live, "enabled", lambda mode: False)

    async def failed_pass(*_args):
        raise RuntimeError("potential-private-provider-token=DO_NOT_LOG")

    monkeypatch.setattr(jobs, "daily_pass", failed_pass)
    settings = SimpleNamespace()
    task = asyncio.create_task(jobs.run_loop(object(), settings))
    try:
        for _ in range(25):
            await asyncio.sleep(0.01)
            if "Catalogue maintenance job=DAILY failed" in caplog.text:
                break
        assert "Catalogue maintenance job=DAILY failed type=RuntimeError" in caplog.text
        assert "location=test_catalogue_worker_safe_error_location.py:failed_pass:" in caplog.text
        assert "DO_NOT_LOG" not in caplog.text
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
