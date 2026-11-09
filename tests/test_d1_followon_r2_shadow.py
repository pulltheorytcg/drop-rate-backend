"""Offline contract for the entire post-Yu-Gi-Oh R2-first D1 queue."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import sqlite3
from pathlib import Path
import sys

import httpx
import pytest

from app import r2_first_catalogue as source_codec

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import d1_followon_r2_shadow as runner  # noqa: E402
from d1_r2_real_shadow import MigrationGuard  # noqa: E402

YGO_UID="11111111-1111-4111-8111-111111111111"
SHARED_UID="22222222-2222-4222-8222-222222222222"
NEW_YGO_SHA="f"*64


class FakeCloud:
    complete=True
    yugioh_day="2026-11-05"
    names=["drop-rate-d1-real-yugioh-shadow"]
    shared=None
    created=0
    writes=0
    new_source=False
    new_source_complete=False
    new_source_active=False

    def __init__(self,account,token):
        assert account==runner.ACCOUNT and token=="scoped-test-token"
        self.path="/accounts/"+account+"/d1/database"

    def list_databases(self):
        return [{"name":name,"uuid":(YGO_UID if name==runner.YGO_DB else SHARED_UID)}
                for name in self.names]

    def call(self,method,path,data=None):
        if method=="GET":
            assert path==self.path+"/"+SHARED_UID
            assert self.shared is not None
            pages=self.shared.execute("pragma page_count").fetchone()[0]
            page_size=self.shared.execute("pragma page_size").fetchone()[0]
            return {"name":runner.DB_NAME,"uuid":SHARED_UID,
                    "file_size":pages*page_size},0
        assert method=="POST" and path==self.path
        assert data=={"name":runner.DB_NAME}
        assert runner.DB_NAME not in self.names
        self.names.append(runner.DB_NAME)
        type(self).shared=sqlite3.connect(":memory:",isolation_level=None)
        self.shared.row_factory=sqlite3.Row
        self.shared.execute("pragma foreign_keys=on")
        type(self).created+=1
        return {"name":runner.DB_NAME,"uuid":SHARED_UID},0

    def query(self,uuid,sql,params=()):
        if uuid==YGO_UID:
            assert sql.startswith("select")
            if "from shadow_generations" in sql:
                values=[{"manifest_sha":runner.YGO_SOURCE_SHA,
                         "expected_rows":runner.YGO_EXPECTED,
                         "projection_sha":"a"*64}]
                if self.new_source:
                    values.append({"manifest_sha":NEW_YGO_SHA,
                                   "expected_rows":runner.YGO_EXPECTED+1,
                                   "projection_sha":"b"*64})
            elif "count(*)" in sql:
                sha=params[0]
                if sha==NEW_YGO_SHA:
                    values=[{"n":runner.YGO_EXPECTED+1 if self.new_source_complete else 16000}]
                elif sha==runner.YGO_SOURCE_SHA:
                    values=[{"n":runner.YGO_EXPECTED if self.complete else 8000}]
                else:
                    raise AssertionError("unexpected YGO generation")
            elif "shadow_active_partitions" in sql:
                values=([{"manifest_sha":NEW_YGO_SHA}]
                        if self.new_source_active else
                        [{"manifest_sha":runner.YGO_SOURCE_SHA}]
                        if self.complete else [])
            elif "max(utc_day)" in sql:
                values=[{"day":self.yugioh_day}]
            else:
                raise AssertionError("unexpected YGO SQL")
            return {"success":True,"results":values},0
        assert uuid==SHARED_UID and self.shared is not None
        c=self.shared.execute(sql,params)
        if sql.lower().lstrip().startswith("insert"):
            type(self).writes+=1
        return {"success":True,
                "results":[dict(r) for r in c.fetchall()] if c.description else []},0

    def batch(self,uuid,statements):
        assert 1<=len(statements)<=12 and uuid==SHARED_UID
        for stmt in statements:
            assert len(stmt["params"])<=100
            self.query(uuid,stmt["sql"],stmt["params"])
        return [{"success":True,"results":[]} for _ in statements]


@pytest.fixture(autouse=True)
def source(monkeypatch):
    FakeCloud.complete=True
    FakeCloud.yugioh_day="2026-11-05"
    FakeCloud.names=[runner.YGO_DB]
    FakeCloud.shared=None
    FakeCloud.created=0
    FakeCloud.writes=0
    FakeCloud.new_source=False
    FakeCloud.new_source_complete=False
    FakeCloud.new_source_active=False
    monkeypatch.setattr(runner,"D1Client",FakeCloud)
    monkeypatch.setattr(runner,"_oidc_token",lambda:"fake-signed-github-oidc")
    monkeypatch.setattr(runner,"DAILY_ROWS",6)
    yield
    if FakeCloud.shared is not None:
        FakeCloud.shared.close()


def fixtures(specs=(("sports",13),("sports-heritage",3))):
    scopes={
        "sports":("cardcollectorcapital","SPORTS_CARDS","English"),
        "sports-heritage":("cardcollectorcapital_heritage","SPORTS_CARDS","English"),
    }
    source_map={}
    pinned=[]
    for code,count in specs:
        scope=scopes[code]
        rows=[]
        for i in range(count):
            rows.append({
                "provider":scope[0],"system_code":scope[1],"language":scope[2],
                "provider_id":scope[0]+f":test-{i:06d}",
                "product_type":"CARD","name":f"Synthetic Sports {count-i}",
                "set_id":"SPORTS","set_name":"Sports Set",
                "card_number":str(i),"rarity":"Base",
                "finish":None,"release_date":"2026-01-01",
                "source_url":"https://example.com/permitted-test",
            })
        data=source_codec.prepare_catalogue(
            rows,provider=scope[0],system_code=scope[1],
            language=scope[2],source_url="https://example.com/permitted-test",
            source_revision="synthetic-pinned",
            permission_ref="https://example.com/permitted-license",
        )
        raw=data._manifest_bytes
        source_map[code]=(raw,list(data.parts))
        pinned.append(runner.Source(
            code,scope,count,hashlib.sha256(raw).hexdigest(),
            300000,20))
    def handler(request:httpx.Request):
        assert request.url.host=="drop-rate-api-live-production.up.railway.app"
        assert request.headers.get("authorization")=="Bearer fake-signed-github-oidc"
        start=runner.SOURCE_PATH+"/followon/"
        assert request.url.path.startswith(start)
        rest=request.url.path[len(start):]
        code,what=rest.split("/",1)
        if code not in source_map:
            return httpx.Response(404)
        raw,parts=source_map[code]
        if what=="manifest":
            return httpx.Response(200,content=raw)
        if what.startswith("part/"):
            i=int(what.split("/")[-1])
            return httpx.Response(200,content=parts[i]) if i<len(parts) else httpx.Response(404)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler),
                        follow_redirects=False),tuple(pinned)


def day(n):
    return datetime(2026,11,n,tzinfo=timezone.utc)


def test_no_ygo_full_parity_means_no_database_creation_or_r2_import():
    FakeCloud.complete=False
    http,pinned=fixtures()
    with http:
        result=runner.run(runner.ACCOUNT,"scoped-test-token","123","1",http=http,now=day(6))
    assert result["status"]=="FOLLOWON_WAITING_FOR_YUGIOH_OR_DAILY_WINDOW"
    assert result["yugioh_staged_rows"]==8000
    assert FakeCloud.created==0 and FakeCloud.writes==0




def test_old_complete_yugioh_does_not_release_queue_when_newer_generation_pending():
    FakeCloud.new_source=True
    FakeCloud.new_source_complete=False
    FakeCloud.new_source_active=False
    http,pinned=fixtures()
    with http:
        report=runner.run(runner.ACCOUNT,"scoped-test-token","123","1",
                          http=http,now=day(6))
    assert report["status"]=="FOLLOWON_WAITING_FOR_YUGIOH_OR_DAILY_WINDOW"
    assert report["reason"]=="YGO_NEWER_GENERATION_PENDING"
    assert report["yugioh_staged_rows"]==16000
    assert report["yugioh_source_rows"]==runner.YGO_EXPECTED+1
    assert FakeCloud.created==0 and FakeCloud.writes==0


def test_latest_yugioh_generation_can_release_queue_when_fully_active(monkeypatch):
    FakeCloud.new_source=True
    FakeCloud.new_source_complete=True
    FakeCloud.new_source_active=True
    http,pinned=fixtures(specs=(("sports",13),))
    monkeypatch.setattr(runner,"SOURCES",pinned)
    with http:
        report=runner.run(runner.ACCOUNT,"scoped-test-token","123","1",
                          http=http,now=day(6))
    assert report["status"]=="FOLLOWON_R2_PARTITION_PARTIAL_STAGED"
    assert report["d1_staged_rows"]==6
    assert FakeCloud.created==1 and FakeCloud.writes>0


def test_new_active_yugioh_pointer_with_partial_rows_blocks():
    FakeCloud.new_source=True
    FakeCloud.new_source_complete=False
    FakeCloud.new_source_active=True
    http,pinned=fixtures()
    with http,pytest.raises(MigrationGuard,match="active pointer is inconsistent"):
        runner.run(runner.ACCOUNT,"scoped-test-token","123","1",http=http,now=day(6))
    assert FakeCloud.created==0 and FakeCloud.writes==0

def test_same_day_as_yugioh_completion_is_always_blocked():
    FakeCloud.yugioh_day="2026-11-06"
    http,pinned=fixtures()
    with http:
        result=runner.run(runner.ACCOUNT,"scoped-test-token","123","1",http=http,now=day(6))
    assert result["reason"]=="YGO_WROTE_TODAY"
    assert FakeCloud.created==0


def test_daily_resume_and_queue_reaches_all_partitions(monkeypatch):
    http,pinned=fixtures()
    monkeypatch.setattr(runner,"SOURCES",pinned)
    with http:
        expected=[
            (6,6,"sports"),
            (6,6,"sports"),
            (7,12,"sports"),
            (8,13,"sports"),
            (9,3,"sports-heritage"),
        ]
        for day_value,count,code in expected:
            output=runner.run(runner.ACCOUNT,"scoped-test-token",
                "1000","1",http=http,now=day(day_value))
            assert output["source"]==code
            assert output["d1_staged_rows"]==count
            assert output["production_reads_switched"] is False
            assert output["market_value_writes"]==0
            assert output["owner_and_settlement_writes"]==0
            public=FakeCloud.shared.execute(
                "select provider,system_code,language,manifest_sha "
                "from shadow_active_partitions order by provider").fetchall()
            assert len(public)== (0 if day_value<8 else 1 if day_value==8 else 2)
        complete=runner.run(runner.ACCOUNT,"scoped-test-token",
            "2000","1",http=http,now=day(10))
        assert complete["status"]=="ALL_FOLLOWON_R2_FIRST_SOURCES_VERIFIED"
        assert complete["verified_d1_rows"]==16
        assert FakeCloud.created==1
        assert FakeCloud.shared.execute("select count(*) from shadow_cards").fetchone()[0]==16


def test_tampered_staged_row_refuses_resume(monkeypatch):
    http,pinned=fixtures(specs=(("sports",13),))
    monkeypatch.setattr(runner,"SOURCES",pinned)
    with http:
        runner.run(runner.ACCOUNT,"scoped-test-token","100","1",http=http,now=day(6))
        FakeCloud.shared.execute(
            "update shadow_cards set name='TAMPER' "
            "where card_key=(select card_key from shadow_cards limit 1)")
        before=FakeCloud.writes
        with pytest.raises(MigrationGuard,match="prefix"):
            runner.run(runner.ACCOUNT,"scoped-test-token","101","1",http=http,now=day(7))
        assert FakeCloud.writes==before
        assert FakeCloud.shared.execute(
            "select count(*) from shadow_active_partitions").fetchone()[0]==0


def test_wrong_immutable_source_sha_never_creates_a_database(monkeypatch):
    http,pinned=fixtures(specs=(("sports",13),))
    monkeypatch.setattr(runner,"SOURCES",(runner.Source(
        pinned[0].code,pinned[0].scope,pinned[0].expected_rows,
        "0"*64,pinned[0].max_bytes,pinned[0].max_parts),))
    with http,pytest.raises(MigrationGuard,match="immutable registry"):
        runner.run(runner.ACCOUNT,"scoped-test-token","110","1",http=http,now=day(6))
    assert FakeCloud.created==0


def test_free_database_count_reserve_protects_operational_slot(monkeypatch):
    FakeCloud.names=[runner.YGO_DB]+[f"synthetic-{i}" for i in range(8)]
    http,pinned=fixtures(specs=(("sports",13),))
    monkeypatch.setattr(runner,"SOURCES",pinned)
    with http,pytest.raises(MigrationGuard,match="slots"):
        runner.run(runner.ACCOUNT,"scoped-test-token","111","1",http=http,now=day(6))
    assert FakeCloud.created==0


def test_unexpected_existing_shared_tables_are_not_repurposed():
    FakeCloud.names=[runner.YGO_DB,runner.DB_NAME]
    FakeCloud.shared=sqlite3.connect(":memory:",isolation_level=None)
    FakeCloud.shared.row_factory=sqlite3.Row
    FakeCloud.shared.execute("create table external_private_data(x integer)")
    cloud=FakeCloud(runner.ACCOUNT,"scoped-test-token")
    with pytest.raises(MigrationGuard,match="Unexpected"):
        runner._get_shadow(cloud,runner._listed(cloud))


def test_invalid_account_fails_before_d1_connection():
    http,pinned=fixtures()
    with http,pytest.raises(MigrationGuard,match="Only approved"):
        runner.run("00000000000000000000000000000000",
                   "scoped-test-token","12","1",http=http,now=day(6))


def test_workflow_has_one_daily_main_writer_and_no_escaped_secrets():
    wf=(Path(__file__).resolve().parents[1]/
        ".github/workflows/d1-followon-r2-shadow.yml").read_text()
    assert "concurrency:" in wf
    assert "cron: '49 3 * * *'" in wf
    assert "CLOUDFARE_D1_PILOT_TOKEN: "+"${{ secrets.CLOUDFARE_D1_PILOT_TOKEN }}" in wf
    assert (chr(92)+"${{") not in wf


def test_d1_capacity_uses_database_detail_not_unsupported_sql_pragmas(monkeypatch):
    cloud=FakeCloud(runner.ACCOUNT,"scoped-test-token")
    cloud.call("POST",cloud.path,{"name":runner.DB_NAME})
    assert runner._disk_used(cloud,SHARED_UID)>=0
    assert FakeCloud.shared.execute("pragma page_count").fetchone()[0]>=0
    def unsupported(_sql):
        raise AssertionError("D1 REST no longer queried for page_count")
    original=cloud.query
    def watch(uuid,sql,params=()):
        assert "pragma page_count" not in sql
        assert "pragma page_size" not in sql
        return original(uuid,sql,params)
    monkeypatch.setattr(cloud,"query",watch)
    assert runner._disk_used(cloud,SHARED_UID)>=0


def test_magic_d1_candidate_is_pinned_to_protected_live_r2_source_and_no_implicit_run():
    magic=next(s for s in runner.SOURCES if s.code=="magic")
    assert magic.scope==("mtgjson","MAGIC_THE_GATHERING","English")
    assert magic.expected_rows==153679
    assert magic.manifest_sha=="e3bda5f54affe0055ec64d7ffb943cb5cae23df8108e74f29e250f7ec63e662a"
    assert sum(source.expected_rows for source in runner.SOURCES)==155505
    wf=(Path(__file__).resolve().parents[1]/
        ".github/workflows/d1-followon-r2-shadow.yml").read_text()
    assert 'doc.get("verified_d1_rows")==155505' in wf
    assert "vars.DR_D1_FOLLOWON_IMPORT_APPROVED_SHA == github.sha" in wf
    assert "vars.DR_D1_FOLLOWON_IMPORT_APPROVED_RUN_ID == github.run_id" in wf


