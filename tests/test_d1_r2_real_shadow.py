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
    keyset_queries=0

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
        if method=="GET":
            assert path==self.path+"/12345678-1234-1234-1234-1234567890ab"
            # Simulate supported Cloudflare metadata, not a public SQL PRAGMA.
            size=self.connection.execute('pragma page_count').fetchone()[0]*self.connection.execute('pragma page_size').fetchone()[0]
            return {"file_size":size},0.0
        assert method=="POST" and path==self.path
        assert data["name"].startswith(runner.SHADOW_DB_PREFIX)
        type(self).created+=1
        return {"name":data["name"],"uuid":"12345678-1234-1234-1234-1234567890ab"},0.0

    def query(self,uuid,sql,params=()):
        assert not sql.lstrip().lower().startswith('pragma'), "D1 REST rejects size PRAGMAs"
        assert uuid=="12345678-1234-1234-1234-1234567890ab"
        if sql == runner.D1_KEYSET_READBACK_SQL:
            assert "offset" not in sql.lower()
            assert "card_key>?" in sql.lower()
            assert len(params)==3
            type(self).keyset_queries += 1
        # Legacy Lorcana generation-refresh reads still use the original
        # OFFSET statement. This patch changes exact full-source parity only.
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


def test_verified_projection_uses_primary_key_cursor():
    assert "card_key>?" in runner.D1_KEYSET_READBACK_SQL
    assert "offset" not in runner.D1_KEYSET_READBACK_SQL.lower()
    assert "order by card_key" in runner.D1_KEYSET_READBACK_SQL.lower()


def test_full_real_r2_to_isolated_d1_readback(monkeypatch):
    FakeD1.created=0;FakeD1.corrupt=False;FakeD1.existing=[]
    FakeD1.keyset_queries=0
    monkeypatch.setattr(runner,"D1Client",FakeD1)
    monkeypatch.setattr(runner,"_oidc_token",lambda:"fake-oidc")
    manifest_bytes,parts,manifest=fixture()
    with http_client(manifest_bytes,parts) as client:
        result=runner.import_real_lorcana("a"*32,"dummy-d1-token","12345","1",client=client)
    assert result["status"]=="REAL_R2_LORCANA_TO_ISOLATED_D1_VERIFIED"
    assert result["source_rows"]==result["d1_verified_rows"]==1002
    assert FakeD1.keyset_queries >= 11  # 1,002 verified rows / 100-page cursor
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


def test_temporary_503_during_railway_rollout_retries_then_verifies(monkeypatch):
    FakeD1.created = 0
    FakeD1.corrupt = False
    FakeD1.existing = []
    monkeypatch.setattr(runner,"D1Client",FakeD1)
    monkeypatch.setattr(runner,"_oidc_token",lambda:"fake-oidc")
    manifest_bytes, parts, _ = fixture()
    with http_client(manifest_bytes, parts) as client:
        valid_source = runner.load_verified_source(client, "fake-oidc")
        attempts, delays = [], []

        def temporary_failure(_client, _identity):
            attempts.append(FakeD1.created)
            if len(attempts) < 3:
                raise runner.MigrationGuard("R2 export rejected: HTTP 503")
            return valid_source

        monkeypatch.setattr(runner,"load_verified_source",temporary_failure)
        monkeypatch.setattr(runner.time,"sleep",lambda n:delays.append(n))
        result = runner.import_real_lorcana("a"*32,"dummy-d1-token","55555","1",client=client)
    assert runner.MAX_SOURCE_READ_ATTEMPTS >= 20
    assert attempts == [0,0,0]
    assert delays == [10,10]
    assert result["d1_verified_rows"] == 1002
    assert FakeD1.created == 1
    FakeD1.last.connection.close()


def test_authenticated_export_401_never_retries_or_creates_d1(monkeypatch):
    FakeD1.created = 0
    FakeD1.existing = []
    monkeypatch.setattr(runner,"D1Client",FakeD1)
    monkeypatch.setattr(runner,"_oidc_token",lambda:"fake-oidc")
    sleeps = []
    monkeypatch.setattr(runner.time,"sleep",lambda n:sleeps.append(n))
    def unauthorized(_client,_identity):
        raise runner.MigrationGuard("R2 export rejected: HTTP 401")
    monkeypatch.setattr(runner,"load_verified_source",unauthorized)
    raw,parts,_=fixture()
    with http_client(raw,parts) as client:
        with pytest.raises(runner.MigrationGuard,match="401"):
            runner.import_real_lorcana("a"*32,"dummy-d1-token","55556","1",client=client)
    assert FakeD1.created == 0
    assert sleeps == []



def test_previous_lorcana_shadow_is_reverified_read_only_not_duplicated(monkeypatch):
    from app import d1_shadow_catalogue as bridge
    FakeD1.created = 0
    FakeD1.corrupt = False
    FakeD1.existing = []
    raw, parts, _ = fixture()
    with http_client(raw, parts) as client:
        source, _ = runner.load_verified_source(client, "fake-oidc")
    cloud = FakeD1("a"*32,"dummy-d1-token")
    runner._schema(cloud,"12345678-1234-1234-1234-1234567890ab")
    init = bridge.generation_statement(source)
    cloud.query("12345678-1234-1234-1234-1234567890ab",init["sql"],init["params"])
    for stmt in bridge.insert_statements(source):
        cloud.query("12345678-1234-1234-1234-1234567890ab",stmt["sql"],stmt["params"])
    activate = bridge.activation_statement(source)
    cloud.query("12345678-1234-1234-1234-1234567890ab",
                activate["sql"],activate["params"])
    FakeD1.existing = [{"name":runner.SHADOW_DB_PREFIX+"123-1",
                         "uuid":"12345678-1234-1234-1234-1234567890ab"}]
    report=runner._existing_lorcana_proof(cloud,source)
    assert report["status"] == "REAL_R2_LORCANA_TO_ISOLATED_D1_VERIFIED"
    assert report["existing_readonly_reverified"] is True
    assert report["d1_verified_rows"] == 1002
    assert FakeD1.created == 0
    assert cloud.connection.execute("select count(*) from shadow_active_partitions").fetchone()[0] == 1
    cloud.connection.close()
    FakeD1.existing=[]


def test_corrupt_existing_lorcana_shadow_refuses_to_claim_success():
    from app import d1_shadow_catalogue as bridge
    FakeD1.corrupt=False
    FakeD1.existing = []
    raw, parts, _ = fixture()
    with http_client(raw, parts) as client:
        source, _ = runner.load_verified_source(client,"fake-oidc")
    cloud=FakeD1("a"*32,"dummy-d1-token")
    runner._schema(cloud,"12345678-1234-1234-1234-1234567890ab")
    FakeD1.existing = [{"name":runner.SHADOW_DB_PREFIX+"123-1",
                         "uuid":"12345678-1234-1234-1234-1234567890ab"}]
    with pytest.raises(runner.MigrationGuard, match="generation"):
        runner._existing_lorcana_proof(cloud,source)
    cloud.connection.close()
    FakeD1.existing=[]


def refresh_fixture(monkeypatch):
    from dataclasses import replace
    from app import d1_shadow_catalogue as bridge
    FakeD1.existing=[];FakeD1.corrupt=False
    raw,parts,_=fixture()
    with http_client(raw,parts) as http:old,_=runner.load_verified_source(http,'fake-oidc')
    cloud=FakeD1('a'*32,'dummy-d1-token');uid='12345678-1234-1234-1234-1234567890ab'
    runner._schema(cloud,uid)
    init=bridge.generation_statement(old);cloud.query(uid,init['sql'],init['params'])
    for statement in bridge.insert_statements(old):cloud.query(uid,statement['sql'],statement['params'])
    activate=bridge.activation_statement(old);cloud.query(uid,activate['sql'],activate['params'])
    FakeD1.existing=[{'name':runner.SHADOW_DB_PREFIX+'123-1','uuid':uid}]
    # Same stable source identities; one upstream factual-name correction.
    rows=[list(r) for r in old.rows]
    rows[0][7]='Corrected public name';rows[0][8]='corrected public name'
    new_sha='f'*64
    for row in rows:row[0]=new_sha
    h=hashlib.sha256()
    for row in sorted(rows,key=lambda r:r[1]):h.update(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode()+b'\n')
    new=replace(old,manifest_sha=new_sha,rows=tuple(tuple(r) for r in rows),projection_sha=h.hexdigest())
    return cloud,uid,old,new


def test_refresh_preserves_old_generation_and_is_idempotent(monkeypatch):
    cloud,uid,old,new=refresh_fixture(monkeypatch)
    before=FakeD1.created
    result=runner._existing_lorcana_proof(cloud,new)
    assert result['refreshed_existing_database'] is True
    assert result['prior_generation_retained'] is True
    assert result['d1_verified_rows']==new.expected_rows
    assert FakeD1.created==before
    assert runner.verify_d1_projection(cloud,uid,old)==old.expected_rows
    assert runner._existing_lorcana_proof(cloud,new)['existing_readonly_reverified'] is True
    assert cloud.connection.execute('select count(*) from shadow_generations').fetchone()[0]==2
    cloud.connection.close();FakeD1.existing=[]


def test_interrupted_refresh_resumes_and_old_pointer_remains_until_parity(monkeypatch):
    cloud,uid,old,new=refresh_fixture(monkeypatch)
    batch=cloud.batch;failed=False
    def fail(db,queries):
        nonlocal failed
        if not failed:
            failed=True;batch(db,queries[:1]);raise OSError('lost acknowledgement')
        return batch(db,queries)
    monkeypatch.setattr(cloud,'batch',fail)
    with pytest.raises(OSError):runner._existing_lorcana_proof(cloud,new)
    assert cloud.connection.execute('select manifest_sha from shadow_active_partitions').fetchone()[0]==old.manifest_sha
    result=runner._existing_lorcana_proof(cloud,new)
    assert result['new_rows_this_run']<new.expected_rows
    assert runner.verify_d1_projection(cloud,uid,new)==new.expected_rows
    cloud.connection.close();FakeD1.existing=[]


def test_second_same_day_generation_defers_without_false_parity(monkeypatch):
    from dataclasses import replace
    cloud,uid,old,new=refresh_fixture(monkeypatch)
    runner._existing_lorcana_proof(cloud,new)
    third=replace(new,manifest_sha='e'*64)
    result=runner._existing_lorcana_proof(cloud,third)
    assert result['status']=='LORCANA_REFRESH_DEFERRED_DAILY_BUDGET'
    assert 'd1_verified_rows' not in result
    assert cloud.connection.execute('select manifest_sha from shadow_active_partitions').fetchone()[0]==new.manifest_sha
    cloud.connection.close();FakeD1.existing=[]


def test_refresh_rejects_removed_identity_and_retains_pointer(monkeypatch):
    from dataclasses import replace
    cloud,uid,old,new=refresh_fixture(monkeypatch)
    rows=list(new.rows);changed=list(rows[0]);changed[1]='x:'+'0'*64;rows[0]=tuple(changed)
    with pytest.raises(runner.MigrationGuard,match='identities'):
        runner._existing_lorcana_proof(cloud,replace(new,rows=tuple(rows)))
    assert cloud.connection.execute('select manifest_sha from shadow_active_partitions').fetchone()[0]==old.manifest_sha
    cloud.connection.close();FakeD1.existing=[]


def test_missing_cloudflare_size_metadata_blocks_refresh(monkeypatch):
    cloud,uid,old,new=refresh_fixture(monkeypatch)
    monkeypatch.setattr(cloud,'call',lambda *args,**kw:({'file_size':None},0.0))
    with pytest.raises(runner.MigrationGuard,match='file_size'):
        runner._existing_lorcana_proof(cloud,new)
    assert cloud.connection.execute('select manifest_sha from shadow_active_partitions').fetchone()[0]==old.manifest_sha
    cloud.connection.close();FakeD1.existing=[]
