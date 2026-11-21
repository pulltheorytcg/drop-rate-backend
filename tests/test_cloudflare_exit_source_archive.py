"""Guarded private R2 operational archive contract; no live credentials."""
from __future__ import annotations

import gzip
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from app import cloudflare_exit_source_archive as arc
from app.object_storage import ObjectStorageError

H = "a" * 64


def record(**kwargs):
    return json.dumps(kwargs,separators=(",",":"))


def test_reviewed_tables_are_exact_not_credentials():
    assert len(arc.TABLE_PKS) == 11
    assert set(arc.APPROVED_COLUMNS) == set(arc.TABLE_PKS)
    assert {"owners","owner_memberships","inventory_items","orders","order_items",
            "financial_ledger_entries","refund_events","shopify_webhook_events",
            "reference_image_mirrors"}.issubset(arc.TABLE_PKS)
    for forbidden in ("users","refresh_tokens","stripe_connected_accounts",
                      "ebay_seller_connections","oauth_clients","payout_preferences",
                      "market_observations","audit_events"):
        assert forbidden not in arc.TABLE_PKS
        with pytest.raises(ObjectStorageError):
            arc._source_select(forbidden)


def test_duplicate_or_wrong_source_fields_rejected():
    first=record(id="item-1",value="safe").encode()
    assert arc._identity(first,"inventory_items",["id","value"])==("item-1",)
    with pytest.raises(ObjectStorageError):
        arc._identity(first,"inventory_items",["value","id"])
    with pytest.raises(ObjectStorageError):
        arc._identity(b'{"id":"a","unknown":"secret"}',"inventory_items",["id","value"])
    with pytest.raises(ObjectStorageError):
        arc._identity(b'{"id":null,"value":"safe"}',"inventory_items",["id","value"])
    with pytest.raises(ObjectStorageError):
        arc._identity(b'{}',"auth.users",[])


def test_approved_four_part_reference_mirror_key():
    key=dict(provider="tcg",system_code="POKEMON",language="English",provider_id="base-4")
    assert arc._identity(record(**key).encode(),"reference_image_mirrors",list(key))==tuple(key.values())


class Conn:
    def __init__(self,rows):
        self.rows=rows
        self.commands=[]
    @asynccontextmanager
    async def transaction(self,**kwargs):
        assert kwargs.get("readonly") is True
        assert kwargs.get("isolation")=="repeatable_read"
        yield self
    async def execute(self,*args):
        self.commands.append(args[0])
    async def fetch(self,query,*params):
        if "pg_attribute" in query:
            name=params[0].split(".")[1]
            columns = list(self.rows[name][0]) if self.rows[name] else list(arc.TABLE_PKS[name])
            return [{"attname":k,"data_type":"text"} for k in columns]
        if "json_populate_recordset" in query:
            return [{"canonical_row":json.dumps(item,separators=(",",":"))}
                    for item in json.loads(params[0])]
        raise AssertionError("Unexpected query "+query)
    async def fetchval(self,query):
        name=query.split('tcg."')[1].split('"')[0]
        return len(self.rows[name])
    def cursor(self,query,prefetch=100):
        name=query.split('tcg."')[1].split('"')[0]
        async def iterate():
            for item in self.rows[name]:
                yield {"canonical_row":json.dumps(item,separators=(",",":"))}
        return iterate()


class Pool:
    def __init__(self,rows): self.conn=Conn(rows)
    @asynccontextmanager
    async def acquire(self,timeout=15):
        yield self.conn
    async def close(self): pass


class PrivateR2:
    def __init__(self):
        self.objects={}
        self.changed=False
    def put_verified_file(self,path,*,category,content_type):
        assert category=="exports"
        data=path.read_bytes()
        digest=hashlib.sha256(data).hexdigest()
        suffix="".join(path.suffixes)
        key=f"private/exports/{digest}{suffix}"
        self.objects[key]=data
        return {"key":key,"sha256":digest,"size_bytes":len(data),"verified":True}
    def download_verified_file(self,key,target,*,expected_sha256,expected_size):
        content=self.objects[key]
        if self.changed:
            content=content+b"tamper"
        if len(content)!=expected_size or hashlib.sha256(content).hexdigest()!=expected_sha256:
            raise ObjectStorageError("R2 byte-level checksum failed")
        target.write_bytes(content)


@pytest.fixture()
def rows(monkeypatch):
    out={}
    for name,pks in arc.TABLE_PKS.items():
        if len(pks)==1:
            out[name]=[{"id":name+"-001","value":"source"}]
        else:
            out[name]=[{"provider":"source","system_code":"POKEMON",
                        "language":"English","provider_id":"4"}]
    monkeypatch.setattr(arc,"MIN_ROWS",{name:0 for name in arc.TABLE_PKS})
    monkeypatch.setattr(arc,"APPROVED_COLUMNS",{
        name:[{"name":k,"type":"text"} for k in entries[0]]
        for name,entries in out.items()})
    return out


@pytest.fixture(autouse=True)
def admin(monkeypatch):
    async def require_admin(conn): return {"role":"PLATFORM_ADMIN"}
    monkeypatch.setattr(arc,"require_platform_admin",require_admin)


@pytest.mark.asyncio
async def test_full_snapshot_archive_and_verified_typed_readback(rows):
    storage=PrivateR2()
    pool=Pool(rows)
    result=await arc.backup_operational_sources(pool,uuid4(),upload=True,storage=storage)
    assert result["status"]=="PRIVATE_OPERATIONAL_R2_SOURCE_RESTORE_PROVEN"
    assert result["verified_relations"]==11
    assert result["r2_uploaded"] is True
    assert len(result["manifest_sha256"]) == 64
    assert result["manifest_size_bytes"] > 0
    assert result["postgres_writes"]==0
    assert result["auth_sessions_exported"] is False
    assert result["customer_data_imported_to_d1"] is False
    assert len(storage.objects)==12   # 11 immutable archives + 1 verified manifest
    assert len(set(result["source_sha256"].values()))==11
    assert result["source_counts"]["owners"]==1
    assert result["source_counts"]["reference_image_mirrors"]==1
    assert all("DROP " not in cmd.upper() and "DELETE " not in cmd.upper()
               for cmd in pool.conn.commands)


@pytest.mark.asyncio
async def test_dry_run_never_stores_a_byte(rows):
    pool=Pool(rows)
    result=await arc.backup_operational_sources(pool,uuid4(),upload=False)
    assert result["status"]=="LOCAL_OPERATIONAL_SOURCE_TYPED_ROUNDTRIP_VERIFIED"
    assert result["r2_uploaded"] is False
    assert result["manifest_sha256"] is None


@pytest.mark.asyncio
async def test_corrupt_download_blocks_completion(rows):
    with pytest.raises(ObjectStorageError,match="checksum"):
        storage=PrivateR2()
        storage.changed=True
        await arc.backup_operational_sources(Pool(rows),uuid4(),upload=True,storage=storage)


@pytest.mark.asyncio
async def test_duplicated_source_identity_fails_before_r2_upload(rows):
    rows["owners"].append(dict(rows["owners"][0]))
    storage=PrivateR2()
    with pytest.raises(ObjectStorageError,match="Duplicate"):
        await arc.backup_operational_sources(Pool(rows),uuid4(),upload=True,storage=storage)
    assert not storage.objects


@pytest.mark.asyncio
async def test_cursor_count_mismatch_fails_closed(rows):
    class Inaccurate(Conn):
        async def fetchval(self,query): return super_count+1
    super_count=1
    pool=Pool(rows)
    pool.conn=Inaccurate(rows)
    with pytest.raises(ObjectStorageError,match="truncated"):
        await arc.backup_operational_sources(pool,uuid4(),upload=False)


@pytest.mark.asyncio
async def test_bad_gzip_detected_even_with_claimed_file_digest(rows,tmp_path):
    path=tmp_path/"bad.ndjson.gz"
    path.write_bytes(b"this-is-not-gzip")
    proof={"table":"owners","source":"tcg.owners",
           "fields":["id","value"],"primary_key":["id"],
           "gzip_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
           "gzip_bytes":len(path.read_bytes())}
    with pytest.raises(ObjectStorageError,match="Compressed"):
        await arc.verify_typed_roundtrip(Pool(rows),uuid4(),path,proof)


@pytest.mark.asyncio
async def test_live_read_floor_prevents_partial_rls_export(rows,monkeypatch):
    monkeypatch.setattr(arc,"MIN_ROWS",{name:2 for name in arc.TABLE_PKS})
    with pytest.raises(ObjectStorageError,match="No complete approved"):
        await arc.backup_operational_sources(Pool(rows),uuid4(),upload=False)


@pytest.mark.asyncio
async def test_partial_rls_visibility_archives_only_complete_tables(rows,monkeypatch):
    minimum = {name:0 for name in arc.TABLE_PKS}
    minimum["owner_memberships"]=2
    monkeypatch.setattr(arc,"MIN_ROWS",minimum)
    store=PrivateR2()
    output=await arc.backup_operational_sources(Pool(rows),uuid4(),upload=True,storage=store)
    assert output["status"]=="PRIVATE_OPERATIONAL_R2_PARTIAL_SOURCE_VERIFIED"
    assert output["verified_relations"]==10
    assert output["expected_relations"]==11
    assert output["complete_approved_scope"] is False
    assert output["blocked_relations"]==[{
        "table":"owner_memberships","visible_rows":1,"minimum_source_rows":2,
        "reason":"RLS_FULL_TABLE_VISIBILITY_NOT_PROVEN",
    }]
    assert "owner_memberships" not in output["source_counts"]
    assert len(store.objects)==11     # 10 complete R2 files plus restricted manifest
    assert output["customer_data_imported_to_d1"] is False


def test_private_archive_heartbeat_contains_only_fixed_stage_table_and_count(capsys):
    arc._progress("SOURCE_READY","owners",6)
    out=capsys.readouterr().out
    assert out=="DROP_RATE_PRIVATE_MIGRATION stage=SOURCE_READY table=owners rows=6\\n"
    assert "password" not in out.lower()
    assert "http" not in out.lower()
    for stage,table,rows in (
        ("unexpected","owners",6),
        ("SOURCE_READY","auth.users",6),
        ("SOURCE_READY","owners",-1),
        ("SOURCE_READY","owners",arc.MAX_ROWS_PER_TABLE+1),
    ):
        with pytest.raises(ObjectStorageError):
            arc._progress(stage,table,rows)
