"""Legacy owner-free 5-relation R2 -> D1 typed shadow migration offline tests."""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import httpx
import pytest

from app import catalogue_r2_live as source_codec

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import d1_legacy_r2_shadow as mover  # noqa: E402
from d1_r2_real_shadow import MigrationGuard  # noqa: E402

FOLLOWON_UUID="11111111-1111-4111-8111-111111111111"
LEGACY_UUID="22222222-2222-4222-8222-222222222222"


class FakeCloud:
    db=None
    created=0
    writes=0
    source_day="2026-11-05"

    def __init__(self,account,token):
        assert account==mover.ACCOUNT and token=="scoped-test-token"
        self.path="/accounts/"+account+"/d1/database"

    def list_databases(self):
        values=[{"name":mover.FOLLOWON_DB,"uuid":FOLLOWON_UUID}]
        if self.db is not None:
            values.append({"name":mover.LEGACY_DB,"uuid":LEGACY_UUID})
        return values

    def call(self,method,path,data=None):
        assert method=="POST" and path==self.path
        assert data=={"name":mover.LEGACY_DB}
        assert self.db is None
        type(self).created+=1
        type(self).db=sqlite3.connect(":memory:",isolation_level=None)
        type(self).db.row_factory=sqlite3.Row
        type(self).db.execute("pragma foreign_keys=on")
        return {"name":mover.LEGACY_DB,"uuid":LEGACY_UUID},0

    def query(self,uid,sql,params=()):
        if uid==FOLLOWON_UUID:
            assert sql=="select max(utc_day) as day from followon_daily_budget"
            return {"success":True,"results":[{"day":self.source_day}]},0
        assert uid==LEGACY_UUID and self.db is not None
        c=self.db.execute(sql,params)
        if sql.lstrip().lower().startswith("insert"):
            type(self).writes+=1
        return {"success":True,
                "results":[dict(r) for r in c.fetchall()] if c.description else []},0


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    FakeCloud.db=None
    FakeCloud.created=0
    FakeCloud.writes=0
    FakeCloud.source_day="2026-11-05"
    monkeypatch.setattr(mover,"D1Client",FakeCloud)
    monkeypatch.setattr(mover,"_oidc_token",lambda:"signed-source")
    monkeypatch.setattr(mover,"_source_active",lambda *args:True)
    monkeypatch.setattr(mover,"_disk_used",lambda *args:1024)
    monkeypatch.setattr(mover,"DAILY_ROWS",2)
    yield
    if FakeCloud.db is not None:
        FakeCloud.db.close()


def fixture(*,tamper=False,altered=False):
    src=("test","POKEMON_TCG","English")
    rows={
      "reference_cards":[dict(provider=src[0],system_code=src[1],language=src[2],
         provider_id="test:001",set_id="TST",name="Changed" if altered else "Card",
         card_number="1",rarity="Rare",image_url=None,
         source_url="https://test.example/item",number_key="001")],
      "reference_sets":[dict(provider=src[0],system_code=src[1],language=src[2],
         set_id="TST",name="Test Set",release_date="2026-01-01",
         declared_card_count=1)],
      "reference_sealed_products":[dict(
         provider=src[0],system_code=src[1],language=src[2],
         provider_id="test:sealed",set_id="TST",name="Test Booster",
         product_type="BOOSTER_BOX",image_url=None,
         source_url="https://test.example/sealed")],
      "catalogue_products":[dict(
         id="11111111-1111-4111-8111-111111111111",
         product_type="COMIC",game="Comic",name="Test Comic",
         set_name="Test Series",card_number="1",variant=None,rarity=None,
         language="English")],
      "catalogue_product_profiles":[dict(
         catalogue_id="11111111-1111-4111-8111-111111111111",
         system_code="COMICS",collectible_type="COMIC",
         set_code="TEST",release_date="2026-01-01",identity_status="VERIFIED")],
    }
    # The real publisher chunks in fixed RELATIONS order; we deliberately
    # shuffle the part order relative to alphabetical D1 readback order.
    parts=[]
    payloads=[]
    for relation in source_codec.RELATIONS:
        raw=json.dumps(rows[relation],sort_keys=True,separators=(",",":")).encode()
        parts.append({"relation":relation,"sha256":hashlib.sha256(raw).hexdigest(),
                      "raw_bytes":len(raw),"rows":1})
        payloads.append(raw)
    manifest={"schema":source_codec.SCHEMA,"generation":122500,
              "counts":{k:1 for k in rows},"parts":parts,
              "raw_bytes":sum(p["raw_bytes"] for p in parts)}
    raw=json.dumps(manifest,sort_keys=True,separators=(",",":")).encode()
    sha=hashlib.sha256(raw).hexdigest()
    by_relation={}
    for relation,records in rows.items():
        digest=hashlib.sha256()
        for record in records:
            digest.update(json.dumps(record,sort_keys=True,
                ensure_ascii=False,separators=(",",":")).encode()+b"\n")
        by_relation[relation]=digest.hexdigest()

    def handle(request:httpx.Request):
        assert request.url.host=="drop-rate-api-live-production.up.railway.app"
        assert request.headers["authorization"]=="Bearer signed-source"
        if request.url.path==mover.SOURCE_PATH_LEGACY_D1+"/manifest":
            return httpx.Response(200,content=raw)
        if request.url.path.startswith(mover.SOURCE_PATH_LEGACY_D1+"/part/"):
            idx=int(request.url.path.rsplit("/",1)[-1])
            data=payloads[idx]
            if tamper and idx==0: data=data[:-1]+b"!"
            return httpx.Response(200,content=data)
        return httpx.Response(404)
    client=httpx.Client(transport=httpx.MockTransport(handle),
                        follow_redirects=False)
    return client,sha,manifest,by_relation


def clock(d):
    return datetime(2026,11,d,tzinfo=timezone.utc)


def pin(monkeypatch,sha,manifest,by_relation):
    monkeypatch.setattr(mover,"MANIFEST_SHA",sha)
    monkeypatch.setattr(mover,"SOURCE_BYTES",manifest["raw_bytes"])
    monkeypatch.setattr(mover,"SOURCE_PARTS",len(manifest["parts"]))
    monkeypatch.setattr(mover,"COUNTS",manifest["counts"])
    monkeypatch.setattr(mover,"EXPECTED_ROWS",sum(manifest["counts"].values()))
    monkeypatch.setattr(mover,"RELATION_SHA",by_relation)


def test_all_five_types_survive_multiple_days_and_only_activate_after_exact_sha(monkeypatch):
    client,sha,manifest,digests=fixture()
    pin(monkeypatch,sha,manifest,digests)
    with client:
        for day,expected in [(6,2),(6,2),(7,4),(8,5)]:
            out=mover.run(mover.ACCOUNT,"scoped-test-token","123","1",
                          http=client,now=clock(day))
            count=out.get("d1_staged_rows",out.get("d1_verified_rows"))
            assert count==expected
            assert out["market_value_writes"]==0
            assert out["owner_and_settlement_writes"]==0
            assert out["production_reads_switched"] is False
            active=FakeCloud.db.execute("select count(*) from legacy_live_rows").fetchone()[0]
            assert active==(5 if expected==5 else 0)
        assert out["status"]=="LEGACY_FIVE_RELATIONS_D1_FULL_PARITY_VERIFIED"
        assert out["relations"]=={k:1 for k in source_codec.RELATIONS}
        saved=FakeCloud.db.execute(
            "select relation,payload_json from legacy_shadow_rows order by relation"
        ).fetchall()
        assert len(saved)==5
        assert {r["relation"] for r in saved}==set(source_codec.RELATIONS)
        assert FakeCloud.created==1


def test_followon_not_active_never_fetches_legacy_or_creates_d1(monkeypatch):
    monkeypatch.setattr(mover,"_source_active",lambda *args:False)
    client,_,_,_=fixture()
    with client:
        report=mover.run(mover.ACCOUNT,"scoped-test-token","124","1",
                         http=client,now=clock(6))
    assert report["status"]=="LEGACY_WAITING_FOR_PRECEDING_CATALOGUE"
    assert FakeCloud.created==0


def test_followon_wrote_today_cannot_compete_for_account_quota():
    FakeCloud.source_day="2026-11-06"
    client,_,_,_=fixture()
    with client:
        report=mover.run(mover.ACCOUNT,"scoped-test-token","125","1",
                         http=client,now=clock(6))
    assert report["reason"]=="FOLLOWON_WROTE_TODAY_OR_RECEIPT_UNAVAILABLE"
    assert FakeCloud.created==0


def test_corrupt_source_and_wrong_manifest_fail_before_d1_creation(monkeypatch):
    client,sha,manifest,digests=fixture(tamper=True)
    pin(monkeypatch,sha,manifest,digests)
    with client,pytest.raises((MigrationGuard,ValueError)):
        mover.run(mover.ACCOUNT,"scoped-test-token","126","1",
                  http=client,now=clock(6))
    assert FakeCloud.db is None

    client,sha,manifest,digests=fixture(altered=True)
    pin(monkeypatch,"f"*64,manifest,digests)
    with client,pytest.raises(MigrationGuard,match="changed"):
        mover.run(mover.ACCOUNT,"scoped-test-token","127","1",
                  http=client,now=clock(6))
    assert FakeCloud.db is None


def test_staged_copy_must_match_every_identity_and_payload_on_resume(monkeypatch):
    client,sha,manifest,digests=fixture()
    pin(monkeypatch,sha,manifest,digests)
    with client:
        mover.run(mover.ACCOUNT,"scoped-test-token","128","1",
                  http=client,now=clock(6))
        FakeCloud.db.execute("update legacy_shadow_rows set payload_json='{}' "
                             "where identity_sha=(select identity_sha from legacy_shadow_rows limit 1)")
        with pytest.raises(MigrationGuard,match="differs"):
            mover.run(mover.ACCOUNT,"scoped-test-token","129","1",
                      http=client,now=clock(7))
        assert FakeCloud.db.execute("select count(*) from legacy_live_rows").fetchone()[0]==0


def test_source_projection_never_contains_financial_private_tables():
    sql=mover.SCHEMA.lower()
    assert "settlement" not in sql and "shopify" not in sql
    assert "acquisition" not in sql and "market_value" not in sql
    assert mover.EXPECTED_ROWS==79186


def test_only_trusted_workflow_credentials_can_write():
    workflow=(Path(__file__).resolve().parents[1]/
              ".github/workflows/d1-legacy-r2-shadow.yml").read_text()
    assert (chr(92)+"${{") not in workflow
    assert "CLOUDFARE_D1_PILOT_TOKEN: "+"${{ secrets.CLOUDFARE_D1_PILOT_TOKEN }}" in workflow
    assert "GITHUB_STATUS_TOKEN: "+"${{ github.token }}" in workflow
    assert "id-token: write" in workflow and "refs/heads/main" in workflow
