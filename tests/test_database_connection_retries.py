"""Bounded Railway/Supabase connection retries, without bypassing safety gates."""

import asyncio
from types import SimpleNamespace

import asyncpg
import pytest

from app import db


def test_transient_connect_timeouts_retry_then_return(monkeypatch, caplog):
    calls = 0
    waits = []

    async def connect():
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise TimeoutError("sensitive internal network address")
        return "connected"

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    result = asyncio.run(db.retry_database_connection(connect, context="test_job"))

    assert result == "connected"
    assert calls == 3
    assert waits == [1, 2]
    assert "DB_CONNECT_RETRY context=test_job" in caplog.text
    assert "TimeoutError" in caplog.text
    assert "sensitive internal network address" not in caplog.text


def test_exhausted_connect_retries_fail_closed(monkeypatch):
    calls = 0
    waits = []

    async def connect():
        nonlocal calls
        calls += 1
        raise ConnectionRefusedError("blocked")

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    with pytest.raises(ConnectionRefusedError, match="blocked"):
        asyncio.run(db.retry_database_connection(connect, context="test_job"))

    assert calls == 4
    assert waits == [1, 2, 4]


def test_credentials_and_nontransient_sql_errors_are_not_retried(monkeypatch):
    calls = 0

    async def connect():
        nonlocal calls
        calls += 1
        raise asyncpg.InvalidPasswordError("invalid password")

    async def unexpected_sleep(_seconds):
        raise AssertionError("not retryable")

    monkeypatch.setattr(db.asyncio, "sleep", unexpected_sleep)
    with pytest.raises(asyncpg.InvalidPasswordError):
        asyncio.run(db.retry_database_connection(connect, context="test_job"))
    assert calls == 1


def test_api_pool_retries_connection_without_changing_security_settings(monkeypatch):
    attempts = []

    async def fake_pool(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise TimeoutError("initial IPv6 route unavailable")
        return "pool"

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(db.asyncpg, "create_pool", fake_pool)
    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    settings = SimpleNamespace(
        database_url="postgres://tcg_api:secret@example.test/postgres",
        db_pool_min=1,
        db_pool_max=5,
        environment="production",
    )
    result = asyncio.run(db.create_pool(settings))

    assert result == "pool"
    assert len(attempts) == 2
    assert all(params["timeout"] == 15 for params in attempts)
    assert all(params["server_settings"]["statement_timeout"] == "15000" for params in attempts)
    assert all(params["server_settings"]["search_path"] == "pg_catalog,tcg" for params in attempts)
    assert all(params["dsn"] == settings.database_url for params in attempts)
