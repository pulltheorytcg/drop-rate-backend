"""Offline no-write tests for protected Yu-Gi-Oh source-vs-D1 drift classification."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import d1_yugioh_drift_audit as audit  # noqa: E402
from d1_r2_real_shadow import MigrationGuard  # noqa: E402
from app.d1_shadow_catalogue import Projection, SQLITE_COLUMNS


OLD_SHA="a"*64
NEW_SHA="b"*64
UID="12345678-1234-1234-1234-1234567890ab"


def row(index, *, manifest=NEW_SHA, name=None, provider_id=None):
    key=f"stable-{index}"
    item={
        "manifest_sha":manifest, "card_key":key,
        "provider":"ygoprodeck", "system_code":"YUGIOH",
        "language":"English", "provider_id":provider_id or f"prod-{index}",
        "product_type":"CARD", "name":name or f"Card {index}",
        "name_fold":(name or f"Card {index}").casefold(),
        "set_id":"SET", "set_name":"Verified Set",
        "card_number":str(index), "rarity":"Common",
        "finish":None, "release_date":"2026-01-01",
        "cardmarket_product_id":None,
    }
    return tuple(item[k] for k in SQLITE_COLUMNS)


class FakeD1:
    stage=[row(0,manifest=OLD_SHA),row(1,manifest=OLD_SHA)]
    old_rows=3
    databases=True
    queries=0
    writes=0

    def __init__(self,account,token):
        assert account==audit.ACCOUNT and token=="fake-scoped-token"

    def list_databases(self):
        return ([{"name":audit.EXACT_DATABASE_NAME,"uuid":UID}]
                if self.databases else [])

    def query(self,uid,sql,params=()):
        assert uid==UID
        assert sql.lstrip().lower().startswith("select ")
        type(self).queries+=1
        if "from shadow_generations" in sql:
            result=[{"manifest_sha":OLD_SHA, "provider":audit.SCOPE[0],
                     "system_code":audit.SCOPE[1],"language":audit.SCOPE[2],
                     "expected_rows":self.old_rows}]
        elif "count(*)" in sql:
            assert params==(OLD_SHA,)
            result=[{"n":len(self.stage)}]
        elif "from shadow_cards" in sql:
            assert params[0]==OLD_SHA
            ordered=sorted(self.stage,key=lambda x:x[1])
            result=[dict(zip(SQLITE_COLUMNS,x)) for x in ordered[params[2]:params[2]+params[1]]]
        else:
            raise AssertionError("Unexpected read-only D1 query")
        return {"success":True,"results":result},0

    def call(self,*args,**kwargs):
        type(self).writes+=1
        raise AssertionError("Audit must not write D1")
    def batch(self,*args,**kwargs):
        type(self).writes+=1
        raise AssertionError("Audit must not batch D1 writes")


@pytest.fixture(autouse=True)
def guard(monkeypatch):
    FakeD1.stage=[row(0,manifest=OLD_SHA),row(1,manifest=OLD_SHA)]
    FakeD1.old_rows=3
    FakeD1.databases=True
    FakeD1.queries=0
    FakeD1.writes=0
    snapshot=Projection(
        manifest_sha=NEW_SHA,scope=audit.SCOPE,expected_rows=4,
        source_content_sha="c"*64,source_revision="test-readonly",
        projection_sha="d"*64,rows=tuple(row(i) for i in range(4)))
    monkeypatch.setattr(audit,"EXPECTED_RECORDS",3)
    monkeypatch.setattr(audit,"D1Client",FakeD1)
    monkeypatch.setattr(audit,"_oidc_token",lambda:"trusted-test-oidc")
    monkeypatch.setattr(audit,"load_verified_source",
        lambda *_args,**_kwargs:(snapshot,{}))


def run():
    with httpx.Client(transport=httpx.MockTransport(
            lambda req:httpx.Response(500))) as client:
        return audit.audit(audit.ACCOUNT,"fake-scoped-token",http=client)


def test_identical_old_stage_reports_no_drift_without_any_write():
    report=run()
    assert report["current_r2_source_rows"]==4
    assert report["old_source_rows"]==3
    assert report["existing_d1_staged_rows"]==2
    assert report["unchanged_records"]==2
    assert report["changed_records"]==0
    assert report["automatic_identity_reuse_permitted"] is True
    assert report["source_d1_rows_written"]==0
    assert FakeD1.writes==0


def test_changed_name_is_counted_as_metadata_not_identity():
    FakeD1.stage=[row(0,manifest=OLD_SHA,name="Old name"),
                  row(1,manifest=OLD_SHA)]
    report=run()
    assert report["changed_records"]==1
    assert report["metadata_only_records"]==1
    assert report["identity_changed_records"]==0
    assert report["changed_fields"]=={"name":1,"name_fold":1}
    assert report["automatic_identity_reuse_permitted"] is True


def test_old_provider_identity_change_requires_review():
    FakeD1.stage=[row(0,manifest=OLD_SHA,provider_id="legacy-wrong"),
                  row(1,manifest=OLD_SHA)]
    report=run()
    assert report["identity_changed_records"]==1
    assert report["changed_fields"]["provider_id"]==1
    assert report["automatic_identity_reuse_permitted"] is False
    assert FakeD1.writes==0


def test_old_card_missing_from_current_source_is_classified_not_deleted():
    old=list(row(0,manifest=OLD_SHA))
    old[1]="removed-stable-id"
    FakeD1.stage=[tuple(old),row(1,manifest=OLD_SHA)]
    report=run()
    assert report["missing_old_keys"]==1
    assert report["automatic_identity_reuse_permitted"] is False
    assert FakeD1.writes==0


def test_tampered_row_and_missing_database_fail_closed():
    original=FakeD1.stage[0]
    FakeD1.stage=[original[:-1], FakeD1.stage[1]]
    with pytest.raises(MigrationGuard,match="malformed"):
        run()
    FakeD1.databases=False
    with pytest.raises(MigrationGuard,match="Missing or ambiguous"):
        run()
    assert FakeD1.writes==0


def test_unapproved_account_is_rejected_before_cloudflare_connection():
    with httpx.Client() as client,pytest.raises(MigrationGuard,match="Wrong account"):
        audit.audit("0"*32,"fake-scoped-token",http=client)
    assert FakeD1.queries==0
    assert FakeD1.writes==0


def test_audit_github_workflow_does_not_enable_writes():
    content=(Path(__file__).resolve().parents[1]
             / ".github/workflows/d1-yugioh-drift-audit.yml").read_text()
    assert "id-token: write" in content
    assert "python tools/d1_yugioh_drift_audit.py" in content
    assert "${{ secrets.CLOUDFARE_D1_PILOT_TOKEN }}" in content
    assert "git push" not in content
    assert "workflow_dispatch" in content
