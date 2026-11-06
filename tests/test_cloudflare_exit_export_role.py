"""Privileged full-source export is separated from customer-facing RLS credentials."""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.object_storage import ObjectStorageError
from scripts.archive_cloudflare_exit_source import EXPORT_ROLE,verify_export_account


class ExportConn:
    def __init__(self, *, username=EXPORT_ROLE, read_only="on", bypass=True,
                 superuser=False, all_visible=True):
        self.values={"username":username,"default_read_only":read_only,
                     "rolsuper":superuser,"rolcreaterole":False,"rolcreatedb":False,
                     "rolreplication":False,"rolbypassrls":bypass}
        self.all_visible=all_visible
        self.queries=[]
    @asynccontextmanager
    async def transaction(self, **options):
        assert options=={"isolation":"repeatable_read","readonly":True}
        yield
    async def fetchrow(self,sql):
        assert "pg_roles" in sql
        return self.values
    async def fetchval(self,sql):
        self.queries.append(sql)
        if "owner_memberships" in sql and not self.all_visible:
            return 1
        return 700_000


class Pool:
    def __init__(self,conn): self.conn=conn
    @asynccontextmanager
    async def acquire(self,timeout=15):
        yield self.conn


@pytest.mark.asyncio
async def test_full_table_read_only_role_preflight_passes():
    conn=ExportConn()
    await verify_export_account(Pool(conn))
    assert len(conn.queries)==11
    assert all(sql.startswith("SELECT count(*) FROM tcg.") for sql in conn.queries)


@pytest.mark.asyncio
@pytest.mark.parametrize("override",[
    {"username":"tcg_api"}, {"username":"postgres"}, {"rolbypassrls":False},
    {"default_read_only":"off"}, {"rolsuper":True}, {"rolcreaterole":True},
    {"rolcreatedb":True}, {"rolreplication":True},
])
async def test_any_wrong_role_or_privilege_is_blocked(override):
    conn=ExportConn()
    conn.values.update(override)
    with pytest.raises(ObjectStorageError,match="read-only export role"):
        await verify_export_account(Pool(conn))


@pytest.mark.asyncio
async def test_one_of_six_memberships_is_rejected_not_exported():
    conn=ExportConn(all_visible=False)
    with pytest.raises(ObjectStorageError,match="owner_memberships"):
        await verify_export_account(Pool(conn))


@pytest.mark.asyncio
async def test_missing_role_metadata_rejected():
    conn=ExportConn()
    async def missing(sql): return None
    conn.fetchrow=missing
    with pytest.raises(ObjectStorageError,match="export role"):
        await verify_export_account(Pool(conn))
