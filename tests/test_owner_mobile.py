from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import owner_mobile as mobile
from app.access_control import require_owner_portal_request
from app.auth import require_user


def test_catalogue_filters_keep_input_in_parameters():
    sql, values = mobile.catalogue_filters("x%' OR true --", "Pokemon", "Japanese")
    assert "OR true" not in sql
    assert values == ["%x\\%' OR true --%", "Pokemon", "Japanese"]
    assert "p.game=$2" in sql and "p.language=$3" in sql


def test_browse_without_query_and_literal_underscore():
    sql, values = mobile.catalogue_filters("", "One Piece", "")
    assert values == ["One Piece"] and "p.game=$1" in sql
    assert mobile.catalogue_filters("a_b", "", "")[1] == ["%a\\_b%"]


@pytest.mark.asyncio
async def test_pagination_and_authenticated_context(monkeypatch):
    actor = uuid4()
    calls = []
    class Connection:
        async def fetch(self, sql, *params):
            calls.append((sql, params))
            return [{"id": str(i), "name": f"Card {i}"} for i in range(3)]
    @asynccontextmanager
    async def connection(pool, user_id, request_id):
        assert user_id == actor
        yield Connection()
    monkeypatch.setattr(mobile, "user_connection", connection)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=None)), state=SimpleNamespace(request_id="test"))
    result = await mobile.catalogue(request, SimpleNamespace(user_id=actor), {"owner_id": uuid4()}, q="", game="Pokemon", language="Japanese", offset=2, limit=2)
    assert len(result["items"]) == 2 and result["has_more"] is True
    sql, params = calls[0]
    assert params == ("Pokemon", "Japanese", 3, 2)
    assert "m.rights_status='VERIFIED'" in sql
    assert "m.inventory_id is null" in sql


def test_role_guard_runs_before_mobile_reads():
    app = FastAPI()
    app.include_router(mobile.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(user_id=uuid4())
    def denied(): raise HTTPException(403, "Owner portal access required")
    app.dependency_overrides[require_owner_portal_request] = denied
    client = TestClient(app)
    for path in ["/api/v1/owner/mobile/games", "/api/v1/owner/mobile/catalogue"]:
        assert client.get(path).status_code == 403


def test_mobile_query_limits_reject_invalid_pages():
    app = FastAPI(); app.include_router(mobile.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(user_id=uuid4())
    app.dependency_overrides[require_owner_portal_request] = lambda: {"owner_id": uuid4()}
    client = TestClient(app)
    for query in ["limit=500", "offset=-1", "q=" + "x"*81]:
        assert client.get("/api/v1/owner/mobile/catalogue?" + query).status_code == 422
