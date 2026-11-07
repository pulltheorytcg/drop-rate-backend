from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app import founder_accounts
from app.auth import require_user


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["", "/inventory", "/activity"])
@pytest.mark.parametrize("role,authorized,status", [
    ("OWNER", False, 403), ("PLATFORM_ADMIN", False, 403),
    ("PLATFORM_ADMIN", True, 200), (None, False, 403),
])
async def test_founder_data_requires_roster_on_every_endpoint(monkeypatch, path, role, authorized, status):
    account_id = uuid4()
    data_queries = []

    class Connection:
        async def fetch(self, sql, *args):
            if "from tcg.owner_memberships m" in sql:
                if role is None:
                    return []
                return [{"user_id": uuid4(), "owner_id": account_id, "role": role,
                         "display_name": "Test", "owner_type": "FOUNDER", "founder_slot": 1,
                         "founder_authorized": authorized}]
            data_queries.append((sql, args))
            return []

        async def fetchval(self, sql, *args):
            data_queries.append((sql, args))
            return 0

    @asynccontextmanager
    async def connection(*args):
        yield Connection()

    monkeypatch.setattr(founder_accounts, "user_connection", connection)
    app = FastAPI()
    app.state.db_pool = object()
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(user_id=uuid4())
    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = str(uuid4())
        return await call_next(request)
    app.include_router(founder_accounts.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/founder/accounts" + path)
        assert response.status_code == status
        if status == 403:
            assert not data_queries, "Access must be rejected before querying other accounts"
        else:
            assert response.json()["read_only"] is True
            assert data_queries
            if path == "/inventory":
                data_queries.clear()
                response = await client.get("/api/v1/founder/accounts/inventory", params={
                    "owner_id": str(account_id), "search": "%' OR true--", "offset": 40})
                assert response.status_code == 200
                sql, args = data_queries[-1]
                assert "%' OR true--" not in sql
                assert args == (account_id, "%' OR true--", 40, 40)
            assert (await client.post("/api/v1/founder/accounts" + path, json={})).status_code == 405


@pytest.mark.asyncio
async def test_forged_founder_role_cannot_pass_access_context():
    from app.access_control import current_access_context
    from fastapi import HTTPException
    class Connection:
        async def fetch(self, sql):
            return [{"role": "PLATFORM_ADMIN", "founder_authorized": False}]
    with pytest.raises(HTTPException) as error:
        await current_access_context(Connection())
    assert error.value.status_code == 403
