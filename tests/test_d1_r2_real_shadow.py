"""Complete real-object transport + D1 parity using private synthetic doubles only."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
import sys

import httpx
import pytest

from app import r2_first_catalogue as codec

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "tools"))
import d1_r2_real_shadow as runner  # noqa: E402


class FakeD1:
    created=0
    last=None
    corrupt=False
    existing=[]

    def __init__(self,account,token):
        assert account=="a"*32
        assert token=="dummy-d1-token"
        self.path="/accounts/" + account + "/d1/database"
        self.connection=sqlite3.connect(":memory:",isolation_level=None)
        self.connection.row_factory=sqlite3.Row
        self.connection.execute("pragma foreign_keys=on")
        type(self).last=self

    def list_databases(self): return list(type(self).existing)

    def call(self,method,path,data=None):
        assert method=="POST" and path==self.path
        assert data["name"].startswith(runner.SHADOW_DB_PREFIX)
        type(self).created+=1
        return {"name":data["name"],"uuid":"12345678-1234-1234-1234-1234567890ab"},0.0

    def query(self,uuid,sql,params=()):
        assert uuid=="12345678-1234-1234-1234-1234567890ab"
        cur=self.connection.execute(sql,params)
        rows=[dict(row) for row in cur.fetchall()] if cur.description else []
        if self.corrupt and "from shadow_cards where manifest_sha=" in sql and "order by card_key" in sql:
            if rows: rows[0]["name"]="tampered"
        return ({"success":True,"results":rows},0.0)

    def batch(self,uuid,queries):
        assert len(queries)<=12
        for item in queries:
            assert len(item["params"])<=100
            self.query(uuid,item["sql"],item["params"])
        return [{"success":True,"results":[]} for _ in queries]


def fixture(count=1002):
    source=[]
    for i in range(count):
        source.append({
            "provider":"lorcast","system_code":"DISNEY_LORCANA","language":"English",
            "provider_id":f"lorcast:pilot-{i:06d}", "product_type":"CARD",
            "name":f"Public Synthetic Example {i:06d}", "set_id":"SET-TEST",
            "set_name":"Source Regression Example", "card_number":str(i),
            "rarity":"common", "finish":None,"release_date":"2026-01-01",
            "source_url":"https://api.lorcast.com/v0/sets",
        })
    bundle=codec.prepare_catalogue(source,provider="lorcast",system_code="DISNEY_LORCANA",
       language="English",source_url="https://api.lorcast.com/v0/sets",
       source_revision="sha256:"+"a"*64,permission_ref="https://lorcast.com/docs/api")
    manifest=bundle.manifest
    return bundle._manifest_bytes,list(bundle.parts),manifest


def http_client(manifest_bytes, parts, *, tamper=False):
    def request_handler(req: httpx.Request):
        assert req.headers.get("authorization")=="Bearer fake-oidc"
        if req.url.path.endswith("/manifest"):
            return httpx.Response(200,content=manifest_bytes)
        if req.url.path.startswith(runner.SOURCE_PATH + "/part/"):
            index=int(req.url.path.rsplit("/",1)[-1])
            raw=parts[index]
            if tamper and index==0:
                raw=raw[:-1]+b"!"
            return httpx.Response(200,content=raw)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(request_handler),follow_redirects=False)


def test_full_real_r2_to_isolated_d1_readback(monkeypatch):
    FakeD1.created=0;FakeD1.corrupt=False;FakeD1.existing=[]
    monkeypatch.setattr(runner,"D1Client",FakeD1)
    monkeypatch.setattr(runner,"_oidc_token",lambda:"fake-oidc")
    manifest_bytes,parts,manifest=fixture()
    with http_client(manifest_bytes,parts) as client:
        result=runner.import_real_lorcana("a"*32,"dummy-d1-token","12345","1",client=client)
    assert result["status"]=="REAL_R2_LORCANA_TO_ISOLATED_D1_VERIFIED"
    assert result["source_rows"]==result["d1_verified_rows"]==1002
    assert result["r2_source_manifest_sha"]==hashlib.sha256(manifest_bytes).hexdigest()
    assert result["production_money_or_owner_writes"]==0
    assert result["production_market_value_writes"]==0
    assert result["main_catalogue_reads_switched"] is False
    assert FakeD1.created==1
    assert FakeD1.last.connection.execute("select count(*) from shadow_live_cards").fetchone()[0]==1002
    FakeD1.last.connection.close()


def test_corrupted_verified_part_refused_before_d1_creation(monkeypatch):
    FakeD1.created=0;FakeD1.existing=[]
    monkeypatch.setattr(runner,"D1Client",FakeD1)
    monkeypatch.setattr(runner,"_oidc_token",lambda:"fake-oidc")
    raw,parts,_=fixture()
    with http_client(raw,parts,tamper=True) as client:
        with pytest.raises(ValueError):
            runner.import_real_lorcana("a"*32,"dummy-d1-token","12346","1",client=client)
    assert FakeD1.created==0


def test_d1_readback_tampering_blocks_publication(monkeypatch):
    FakeD1.created=0;FakeD1.corrupt=True;FakeD1.existing=[]
    monkeypatch.setattr(runner,"D1Client",FakeD1)
    monkeypatch.setattr(runner,"_oidc_token",lambda:"fake-oidc")
    raw,parts,_=fixture()
    with http_client(raw,parts) as client:
        with pytest.raises(runner.MigrationGuard,match="parity"):
            runner.import_real_lorcana("a"*32,"dummy-d1-token","12347","1",client=client)
    assert FakeD1.created==1
    assert FakeD1.last.connection.execute(
        "select count(*) from shadow_active_partitions").fetchone()[0]==0
    FakeD1.last.connection.close()
    FakeD1.corrupt=False


def test_duplicate_real_shadow_name_blocks_reimport(monkeypatch):
    FakeD1.existing=[{"name":runner.SHADOW_DB_PREFIX+"some-prior-run"}]
    FakeD1.created=0
    with pytest.raises(runner.MigrationGuard,match="earlier real"):
        runner._new_isolated_real_shadow(FakeD1("a"*32,"dummy-d1-token"),"333","1")
    assert FakeD1.created==0
    FakeD1.existing=[]


@pytest.mark.parametrize("host,allowed", [
    ("vstoken.actions.githubusercontent.com", True),
    ("pipelines.actions.githubusercontent.com", True),
    ("token.actions.githubusercontent.com", True),
    ("pipelinesghubeus2a1.actions.githubusercontent.com", True),
    ("vstoken.actions.githubusercontent.com.evil.test", False),
    ("localhost", False),
    ("vstoken.actions.githubusercontent.com:444", False),
])
def test_github_oidc_token_endpoint_exact_host_restriction(monkeypatch,host,allowed):
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_URL",
                       "https://" + host + "/_apis/task/oidc?request=123")
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "mock-runner-token")
    class Response:
        status_code=200
        is_redirect=False
        def json(self): return {"value":"z"*200}
    class Client:
        def __init__(self,**kwargs):
            assert kwargs.get("follow_redirects") is False
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,headers):
            assert headers["Authorization"]=="Bearer mock-runner-token"
            assert "audience=drop-rate-readonly-r2-d1-shadow-20261106" in url
            return Response()
    monkeypatch.setattr(runner.httpx,"Client",Client)
    if allowed:
        assert runner._oidc_token() == "z"*200
    else:
        with pytest.raises(runner.MigrationGuard, match="GitHub-owned token domain"):
            runner._oidc_token()
