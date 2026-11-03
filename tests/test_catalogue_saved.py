"""Account separation and exact-reference contracts for Saved catalogue items."""
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app import catalogue_saved as saved
from app.auth import require_user


CARD = "c:00000000-0000-4000-8000-000000000001"
OTHER = "r:" + "a" * 32
MISSING = "s:" + "f" * 32


@pytest.fixture
def api(monkeypatch):
    user_a, user_b, owner = uuid4(), uuid4(), uuid4()
    actor = {"id": user_a, "access": True, "schema": True}
    records, queries = {}, []

    class Connection:
        async def fetchval(self, sql, *args):
            return actor["schema"]

        async def fetch(self, sql, *args):
            queries.append((sql, args))
            if "from tcg.owner_memberships m" in sql:
                return [{"user_id": actor["id"], "owner_id": owner, "role": "OWNER",
                         "founder_authorized": False, "display_name": "Collector",
                         "owner_type": "CONSIGNOR", "founder_slot": None}] if actor["access"] else []
            if "select key from entries" in sql:
                assert args[0] == owner
                return [{"key": key} for key in args[1] if key in {CARD, OTHER}]
            assert "where user_id=$1" in sql and args[0] == actor["id"]
            return [{"reference_key": key} for key in sorted(records.get(args[0], set()))]

        async def execute(self, sql, *args):
            queries.append((sql, args))
            if "pg_advisory_xact_lock" in sql:
                assert args[0] == str(actor["id"])
                return
            assert args[0] == actor["id"]
            target = records.setdefault(args[0], set())
            if sql.startswith("insert"):
                target.update(args[1])
            elif sql.startswith("delete"):
                target.discard(args[1])
            else:
                raise AssertionError(sql)

    @asynccontextmanager
    async def connection(pool, user_id, request_id):
        assert user_id == actor["id"]
        yield Connection()

    monkeypatch.setattr(saved, "user_connection", connection)
    app = FastAPI()
    app.state.db_pool = object()
    app.include_router(saved.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(user_id=actor["id"])

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = "saved-test"
        return await call_next(request)

    return app, actor, records, queries, user_a, user_b


@pytest.mark.asyncio
async def test_saved_references_are_account_bound_idempotent_and_not_inventory(api):
    app, actor, records, queries, user_a, user_b = api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            response = await client.put("/api/v1/catalogue-browser/saved", json={"key": CARD})
            assert response.status_code == 200 and response.json()["keys"] == [CARD]
        assert records[user_a] == {CARD}
        actor["id"] = user_b
        assert (await client.get("/api/v1/catalogue-browser/saved")).json()["keys"] == []
        await client.delete("/api/v1/catalogue-browser/saved/" + CARD)
        assert records[user_a] == {CARD}
        response = await client.put("/api/v1/catalogue-browser/saved", json={"key": CARD, "user_id": str(user_a)})
        assert response.status_code == 422
        actor["id"] = user_a
        await client.delete("/api/v1/catalogue-browser/saved/" + CARD)
        assert (await client.get("/api/v1/catalogue-browser/saved")).json()["keys"] == []
    writes = [sql for sql, _ in queries if sql.startswith(("insert", "delete", "update"))]
    assert writes and all("tcg.catalogue_saved_references" in sql for sql in writes)


@pytest.mark.asyncio
async def test_import_requires_explicit_confirmation_and_only_imports_available_keys(api):
    app, _, records, _, user_a, _ = api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for payload in ({"keys": [CARD]}, {"keys": [CARD], "confirmed": False}):
            assert (await client.post("/api/v1/catalogue-browser/saved/import", json=payload)).status_code == 422
        assert not records
        response = await client.post("/api/v1/catalogue-browser/saved/import", json={"keys": [CARD, CARD, OTHER, MISSING], "confirmed": True})
        assert response.status_code == 200
        assert response.json()["imported_count"] == 2
        assert response.json()["unavailable_keys"] == [MISSING]
        assert records[user_a] == {CARD, OTHER}
        response = await client.post("/api/v1/catalogue-browser/saved/import", json={"keys": [CARD, OTHER], "confirmed": True})
        assert response.json()["imported_count"] == 0


@pytest.mark.asyncio
async def test_validation_access_and_missing_migration_fail_closed(api):
    app, actor, records, queries, _, _ = api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.put("/api/v1/catalogue-browser/saved", json={"key": "c:bad OR true"})).status_code == 422
        assert (await client.put("/api/v1/catalogue-browser/saved", json={"key": MISSING})).status_code == 404
        actor["access"] = False
        queries.clear()
        assert (await client.get("/api/v1/catalogue-browser/saved")).status_code == 403
        assert all("owner_memberships" in sql for sql, _ in queries)
        actor["access"] = True
        actor["schema"] = False
        assert (await client.put("/api/v1/catalogue-browser/saved", json={"key": CARD})).status_code == 503
        assert not records
        app.dependency_overrides.clear()
        assert (await client.get("/api/v1/catalogue-browser/saved")).status_code == 401


@pytest.mark.asyncio
async def test_account_limit_is_checked_under_transaction_lock(api):
    app, _, records, queries, user_a, _ = api
    records[user_a] = {"r:" + format(index, "032x") for index in range(100)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/api/v1/catalogue-browser/saved", json={"key": CARD})
        assert response.status_code == 409
    assert len(records[user_a]) == 100
    lock = next(index for index, (sql, _) in enumerate(queries) if "pg_advisory_xact_lock" in sql)
    read = next(index for index, (sql, _) in enumerate(queries) if "select reference_key" in sql)
    assert lock < read


def test_saved_migration_has_only_owner_policies_and_no_public_write_path():
    migration = (Path(__file__).parents[1] / "database/migrations/20261103143718_catalogue_saved_references.sql").read_text()
    assert "force row level security" in migration
    assert "grant select, insert, delete" in migration
    assert "revoke all" in migration and "authenticated, service_role, tcg_api" in migration
    assert migration.count("user_id = (select tcg.current_user_id())") == 3
    assert "security definer" not in migration.lower()
    assert "grant update" not in migration.lower()
    assert "primary key (user_id, reference_key)" in migration
