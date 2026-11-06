"""Offline protected Magic D1 writer proof. All Cloudflare interfaces are fake."""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
import sqlite3
from pathlib import Path
import sys
from uuid import UUID

import httpx
import pytest

from app import r2_first_catalogue as source_codec

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import d1_magic_shadow as magic  # noqa: E402
from d1_r2_real_shadow import MigrationGuard  # noqa: E402


YGO_UUID="12345678-1234-1234-1234-1234567890ab"
MAGIC_UUID="87654321-4321-4321-4321-ba0987654321"
SOURCE_URL="https://mtgjson.com/api/v5/AllPrintings.json.xz"


class FakeD1:
    ygo_present=True
    ygo_count=8000
    ygo_pointer=False
    ygo_receipt=False
    other_databases=[]
    new_count=0
    db=None
    updates=0
    ygo_generation_present=True
    page_count=1200

    def __init__(self,account,token):
        assert account==magic.ACCOUNT_ID
        assert token=="scoped-test-token"
        self.path="/accounts/"+account+"/d1/database"

    def list_databases(self):
        result=([{"name":magic.YGO_DATABASE_NAME,"uuid":YGO_UUID}]
                if self.ygo_present else [])
        result += [dict(x) for x in self.other_databases]
        if self.db is not None:
            result.append({"name":magic.EXACT_DATABASE_NAME,"uuid":MAGIC_UUID})
        return result

    def call(self,method,path,data=None):
        assert method=="POST" and path==self.path
        assert data=={"name":magic.EXACT_DATABASE_NAME}
        assert self.db is None
        type(self).db=sqlite3.connect(":memory:",isolation_level=None)
        type(self).db.row_factory=sqlite3.Row
        type(self).db.execute("pragma foreign_keys=on")
        type(self).new_count+=1
        return {"name":magic.EXACT_DATABASE_NAME,"uuid":MAGIC_UUID},0

    def query(self,uid,sql,params=()):
        assert uid in (YGO_UUID,MAGIC_UUID)
        if sql=="pragma page_count":
            return {"results":[{"page_count":self.page_count}]},0
        if sql=="pragma page_size":
            return {"results":[{"page_size":4096}]},0
        if uid==YGO_UUID:
            if "select count(*) as n from shadow_cards" in sql:
                assert params==(magic.YGO_MANIFEST_SHA,)
                data=[{"n":self.ygo_count}]
            elif "from shadow_active_partitions" in sql:
                assert params==magic.YGO_SCOPE
                data=[{"manifest_sha":magic.YGO_MANIFEST_SHA}] if self.ygo_pointer else []
            elif "from shadow_generations" in sql:
                data=([{"expected_rows":45418,"projection_sha":"a"*64}]
                      if self.ygo_generation_present else [])
            elif "shadow_daily_write_budget" in sql:
                data=[{"n":1 if self.ygo_receipt else 0}]
            else:
                raise AssertionError("Unexpected YGO SQL: "+sql[:80])
            return {"results":data},0
        assert self.db is not None
        cursor=self.db.execute(sql,params)
        if sql.lstrip().lower().startswith("insert"):
            type(self).updates+=1
        return {"results":[dict(r) for r in cursor.fetchall()] if cursor.description else []},0

    def batch(self,uid,queries):
        assert uid==MAGIC_UUID and 1<=len(queries)<=12
        for stmt in queries:
            assert len(stmt["params"])<=100
            self.query(uid,stmt["sql"],stmt["params"])
        return [{"results":[],"success":True} for _ in queries]


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    FakeD1.ygo_present=True
    FakeD1.ygo_count=8000
    FakeD1.ygo_pointer=False
    FakeD1.ygo_receipt=False
    FakeD1.other_databases=[]
    FakeD1.new_count=0
    FakeD1.updates=0
    FakeD1.ygo_generation_present=True
    FakeD1.page_count=1200
    FakeD1.db=None
    monkeypatch.setattr(magic,"D1Client",FakeD1)
    monkeypatch.setattr(magic,"_oidc_token",lambda:"signed-fixture-oidc")
    monkeypatch.setattr(magic,"EXPECTED_RECORDS",23)
    monkeypatch.setattr(magic,"DAILY_NEW_ROWS",7)
    yield
    if FakeD1.db is not None:
        FakeD1.db.close()


def fixture(*,tamper=False, altered=False):
    rows=[]
    for i in range(23):
        rows.append({
            "provider":"mtgjson","system_code":"MAGIC_THE_GATHERING",
            "language":"English",
            "provider_id":f"mtgjson:11111111-1111-5111-8111-{i:012d}:nonfoil",
            "product_type":"CARD","name":f"Magic {'Changed' if altered else 'Fixture'} {i}",
            "set_id":"SYN","set_name":"Synthetic Test","card_number":str(i+1),
            "rarity":"rare","finish":"nonfoil",
            "release_date":"2026-01-01","source_url":SOURCE_URL,
            "details":{"cardmarket_product_id":str(i+1200)},
        })
    bundle=source_codec.prepare_catalogue(
        rows, provider="mtgjson",system_code="MAGIC_THE_GATHERING",language="English",
        source_url=SOURCE_URL,source_revision="synthetic",
        permission_ref="https://mtgjson.com/license/")
    raw=bundle._manifest_bytes
    sha=hashlib.sha256(raw).hexdigest()
    objects=list(bundle.parts)
    def transport(req:httpx.Request):
        assert req.url.host=="drop-rate-api-live-production.up.railway.app"
        assert req.headers.get("authorization")=="Bearer signed-fixture-oidc"
        if req.url.path==magic.SOURCE_PATH_MAGIC+"/manifest":
            return httpx.Response(200,content=raw)
        if req.url.path.startswith(magic.SOURCE_PATH_MAGIC+"/part/"):
            n=int(req.url.path.rsplit("/",1)[-1])
            if n>=len(objects):return httpx.Response(404)
            part=objects[n]
            if tamper and n==0:part=part[:-1]+b"!"
            return httpx.Response(200,content=part)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(transport),
                         follow_redirects=False),sha


def today(day):
    return datetime(2026,11,day,tzinfo=timezone.utc)


def test_gate_waits_for_full_yugioh_without_reading_magic_source():
    client,_=fixture()
    with client:
        waiting=magic.run(magic.ACCOUNT_ID,"scoped-test-token","101","1",client=client,now=today(7))
    assert waiting["status"]=="MAGIC_WAITING_FOR_YUGIOH_D1_PARITY"
    assert waiting["yugioh_staged_rows"]==8000
    assert waiting["source_rows"]==23
    assert FakeD1.new_count==0
    assert FakeD1.db is None


def test_full_yugioh_on_same_utc_day_does_not_compete_with_d1_quota():
    FakeD1.ygo_count=45418
    FakeD1.ygo_pointer=True
    FakeD1.ygo_receipt=True
    client,_=fixture()
    with client:
        waiting=magic.run(magic.ACCOUNT_ID,"scoped-test-token","102","1",
                          client=client,now=today(7))
    assert waiting["status"]=="MAGIC_WAITING_FOR_YUGIOH_DAILY_BUDGET"
    assert FakeD1.db is None


def test_magic_can_stage_incrementally_only_after_ygo_and_verify_full_sha(monkeypatch):
    FakeD1.ygo_count=45418
    FakeD1.ygo_pointer=True
    client,sha=fixture()
    monkeypatch.setattr(magic,"EXPECTED_MANIFEST_SHA",sha)
    with client:
        for day,expected in [(7,7),(7,7),(8,14),(9,21),(10,23)]:
            result=magic.run(magic.ACCOUNT_ID,"scoped-test-token","103","1",
                             client=client,now=today(day))
            assert result.get("d1_staged_rows",result.get("d1_verified_rows"))==expected
            assert result["source_rows"]==23
            assert result["market_value_writes"]==0
            assert result["owner_and_settlement_writes"]==0
            assert result["no_public_catalogue_cutover"] is True
            live=FakeD1.db.execute("select count(*) from shadow_live_cards").fetchone()[0]
            assert live==(23 if expected==23 else 0)
        assert result["status"]=="REAL_R2_MAGIC_TO_ISOLATED_D1_VERIFIED"
        assert FakeD1.new_count==1
        assert FakeD1.db.execute("select count(*) from shadow_daily_write_budget").fetchone()[0]==4


def test_wrong_magic_source_generation_fails_before_new_d1():
    FakeD1.ygo_count=45418
    FakeD1.ygo_pointer=True
    client,sha=fixture(altered=True)
    with client,pytest.raises(MigrationGuard,match="generation"):
        magic.run(magic.ACCOUNT_ID,"scoped-test-token","105","1",client=client,now=today(7))
    assert FakeD1.db is None


def test_bad_magic_r2_part_fails_without_d1_creation(monkeypatch):
    FakeD1.ygo_count=45418
    FakeD1.ygo_pointer=True
    client,sha=fixture(tamper=True)
    monkeypatch.setattr(magic,"EXPECTED_MANIFEST_SHA",sha)
    with client,pytest.raises((MigrationGuard,ValueError)):
        magic.run(magic.ACCOUNT_ID,"scoped-test-token","106","1",client=client,now=today(7))
    assert FakeD1.new_count==0


def test_partial_magic_d1_row_tamper_is_never_repaired_silently(monkeypatch):
    FakeD1.ygo_count=45418
    FakeD1.ygo_pointer=True
    client,sha=fixture()
    monkeypatch.setattr(magic,"EXPECTED_MANIFEST_SHA",sha)
    with client:
        magic.run(magic.ACCOUNT_ID,"scoped-test-token","107","1",
                  client=client,now=today(7))
        FakeD1.db.execute("update shadow_cards set name='TAMPERED' where "
                          "card_key=(select card_key from shadow_cards limit 1)")
        with pytest.raises(MigrationGuard,match="prefix"):
            magic.run(magic.ACCOUNT_ID,"scoped-test-token","107","1",
                      client=client,now=today(8))
    assert FakeD1.db.execute("select count(*) from shadow_live_cards").fetchone()[0]==0


def test_disk_guard_and_wrong_account_fail_closed():
    FakeD1.page_count=100_000
    client,_=fixture()
    with client:
        waiting=magic.run(magic.ACCOUNT_ID,"scoped-test-token","108","1",
                          client=client,now=today(8))
    assert waiting["status"]=="MAGIC_WAITING_FOR_D1_DISK_HEADROOM"
    assert FakeD1.db is None
    with pytest.raises(MigrationGuard,match="account"):
        magic.run("0"*32,"scoped-test-token","109","1",client=client,now=today(8))


def test_no_more_d1_slots_guards_database_creation():
    FakeD1.ygo_count=45418
    FakeD1.ygo_pointer=True
    FakeD1.other_databases=[
        {"name":f"unrelated-{i}","uuid":f"11111111-1111-4111-8111-{i:012d}"}
        for i in range(7)]
    client,_=fixture()
    with client:
        waiting=magic.run(magic.ACCOUNT_ID,"scoped-test-token","110","1",
                          client=client,now=today(8))
    assert waiting["status"]=="MAGIC_WAITING_FOR_D1_DATABASE_CAPACITY"
    assert FakeD1.db is None


def test_workflow_credentials_are_not_escaped_and_only_main_can_stage():
    workflow=(Path(__file__).resolve().parents[1]
              /".github/workflows/d1-magic-r2-shadow.yml").read_text()
    assert (chr(92)+"${{") not in workflow
    assert "CLOUDFARE_D1_PILOT_TOKEN: "+"${{ secrets.CLOUDFARE_D1_PILOT_TOKEN }}" in workflow
    assert "GITHUB_STATUS_TOKEN: "+"${{ github.token }}" in workflow
    assert "refs/heads/main" in workflow
    assert "id-token: write" in workflow
    assert "cron: '43 5 * * *'" in workflow
    assert "153662" in workflow
