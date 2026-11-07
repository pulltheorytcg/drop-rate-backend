from contextlib import asynccontextmanager

import httpx
import pytest


@pytest.fixture
def application(monkeypatch):
    from app.main import create_app
    from app.settings import get_settings

    for key, value in {
        "TCG_AUTH_ISSUER": "https://example.supabase.co/auth/v1",
        "TCG_DATABASE_URL": "postgresql://test:test@localhost/test",
        "TCG_AUTH_AUDIENCE": "authenticated",
        "TCG_SUPABASE_PUBLISHABLE_KEY": "test-only",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        yield create_app()
    finally:
        get_settings.cache_clear()


class Pool:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    @asynccontextmanager
    async def acquire(self):
        yield self

    async def fetchval(self, query):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result,status,body",
    [
        (True, 200, {"status": "ready", "database": "connected"}),
        (False, 503, {"status": "not_ready", "database": "read_only"}),
        (None, 503, {"status": "not_ready", "database": "unavailable"}),
        (RuntimeError("private connection details"), 503,
         {"status": "not_ready", "database": "unavailable"}),
    ],
)
async def test_write_readiness_http_response(application, result, status, body):
    application.state.db_pool = Pool(result)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")
    assert response.status_code == status
    assert response.json() == body


@pytest.mark.asyncio
async def test_liveness_still_reports_running_during_database_failure(application):
    pool = Pool(RuntimeError("unavailable"))
    application.state.db_pool = pool
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert pool.calls == 0
