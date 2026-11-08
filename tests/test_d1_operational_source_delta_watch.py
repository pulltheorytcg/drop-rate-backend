"""Protect against stale D1 multi-owner inventory/ledger snapshots without writes."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import d1_operational_source_delta_watch as watch
from d1_operational_source_stage import ACCOUNT,ORDER,TARGETS,DB_NAME


H="a"*64
G="src-test-one"


def source():
    return {
      name:[(f"id-{name}",{"id":f"id-{name}"},"{}",H)]
      for name in ORDER
    }


class FakeD1:
    account_id=ACCOUNT
    def __init__(self,captured):
        self.tables={
          TARGETS[name][0]:[
              {"id":r[0],"source_row_sha256":r[3]} for r in captured[name]]
          for name in ORDER
        }
        self.catalogue=[
           {"catalogue_id":"catalogue-1","reference_manifest_sha256":H}]
        self.write_calls=0
    def list_databases(self):
        return [{"name":DB_NAME,"uuid":"11111111-1111-4111-8111-111111111111"}]
    def query(self,dbid,sql,params=()):
        assert dbid=="11111111-1111-4111-8111-111111111111"
        assert sql.strip().startswith("SELECT")
        assert any(word in sql for word in (
            "ops_shadow_generations","ops_shadow_catalogue_links",
            *self.tables))
        if "FROM ops_shadow_generations" in sql:
            result=[{"generation_id":G,"state":"STAGING",
                     "source_manifest_sha256":H}]
        elif "FROM ops_shadow_catalogue_links" in sql:
            result=self.catalogue
        else:
            table=next(n for n in self.tables if f'FROM "{n}"' in sql)
            result=self.tables[table]
        return {"results":result},0.1


def test_same_source_means_true_read_only_parity():
    src=source();db=FakeD1(src)
    result=watch.verify_shadow(db,src,{"catalogue-1":H})
    assert result["status"]=="READ_ONLY_OPERATIONAL_D1_SNAPSHOT_PARITY"
    assert result["changed_or_missing_record_count"]==0
    assert result["verified_original_tables"]==9
    assert result["source_postgres_writes"]==0
    assert result["shadow_d1_writes"]==0
    assert result["safely_authorizes_cutover"] is False
    assert db.write_calls==0


@pytest.mark.parametrize("table",[
    "owners","owner_memberships","inventory_items","orders","order_items",
    "refund_events","financial_ledger_entries","shopify_webhook_events","media_assets"])
def test_any_owner_finance_or_media_change_blocks_cutover(table):
    src=source();db=FakeD1(src)
    # a changed original record has the same primary key but a new hash
    key,body,raw,_=src[table][0]
    src[table][0]=(key,body,raw,"b"*64)
    result=watch.verify_shadow(db,src,{"catalogue-1":H})
    assert result["status"]=="READ_ONLY_OPERATIONAL_D1_SNAPSHOT_STALE"
    assert result["source_drift"][table]["changed_after_snapshot"]==1
    assert result["changed_or_missing_record_count"]==1


def test_new_sale_or_missing_ledger_has_distinct_drift_directions():
    src=source();db=FakeD1(src)
    src["orders"].append(("new-sale",{"id":"new-sale"},"{}",H))
    src["financial_ledger_entries"].clear()
    result=watch.verify_shadow(db,src,{"catalogue-1":H})
    assert result["source_drift"]["orders"]["added_after_snapshot"]==1
    assert result["source_drift"]["financial_ledger_entries"]["missing_in_source"]==1
    assert result["changed_or_missing_record_count"]==2


def test_catalogue_link_reference_change_also_detected():
    src=source();db=FakeD1(src)
    result=watch.verify_shadow(db,src,{"catalogue-1":"b"*64})
    assert result["catalogue_link_drift"]["changed_after_snapshot"]==1
    assert result["status"]=="READ_ONLY_OPERATIONAL_D1_SNAPSHOT_STALE"


def test_duplicate_or_invalid_original_and_shadow_identity_rejected():
    one=[("key",{},"{}",H)]
    with pytest.raises(watch.SnapshotDriftGuard,match="Duplicate"):
        watch.compare_hashes(one+one,[])
    with pytest.raises(watch.SnapshotDriftGuard,match="Duplicate"):
        watch.compare_hashes(one,[{"id":"key","source_row_sha256":H}]*2)
    with pytest.raises(watch.SnapshotDriftGuard,match="Invalid"):
        watch.compare_hashes(one,[{"id":"key","source_row_sha256":"not-hash"}])


def test_changed_account_or_database_is_fail_closed():
    src=source()
    db=FakeD1(src)
    db.account_id="0"*32
    with pytest.raises(watch.SnapshotDriftGuard,match="account"):
        watch.verify_shadow(db,src,{"catalogue-1":H})
    db.account_id=ACCOUNT
    db.list_databases=lambda: []
    with pytest.raises(watch.SnapshotDriftGuard,match="shadow"):
        watch.verify_shadow(db,src,{"catalogue-1":H})


def test_no_sensitive_ids_appear_in_receipt():
    src=source();db=FakeD1(src)
    result=watch.verify_shadow(db,src,{"catalogue-1":H})
    rendered=json.dumps(result)
    assert "id-owners" not in rendered
    assert "id-inventory_items" not in rendered
    assert "catalogue-1" not in rendered


def payload_pair(before,after):
    import hashlib
    old=json.dumps(before);new=json.dumps(after)
    digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
    return [(after['id'],after,new,digest(new))],[{'id':before['id'],'source_row_json':old,'source_row_sha256':digest(old)}]


def test_column_diagnostics_preserve_privacy_and_distinguish_missing_null_and_types():
    src,remote=payload_pair({'id':'private-id','owner_id':'owner-a','cost':None,'active':1},
                            {'id':'private-id','owner_id':'owner-b','active':True})
    r=watch.explain_changed_fields(src,remote,{'id','owner_id','cost','active'})
    assert r['changed_field_counts']=={'active':1,'cost':1,'owner_id':1}
    assert r['changed_records_examined']==1
    assert r['serialization_only_records']==0
    assert 'private-id' not in str(r) and 'owner-a' not in str(r)


def test_column_diagnostics_reject_corrupt_payload_and_unapproved_fields():
    src,remote=payload_pair({'id':'x','owner_id':'a'},{'id':'x','owner_id':'b'})
    with pytest.raises(watch.SnapshotDriftGuard,match='Unapproved'):
        watch.explain_changed_fields(src,remote,{'id'})
    remote[0]['source_row_json']='{}'
    with pytest.raises(watch.SnapshotDriftGuard,match='hash'):
        watch.explain_changed_fields(src,remote,{'id','owner_id'})


def test_serialization_difference_is_explained_but_hash_still_blocks():
    import hashlib
    src,remote=payload_pair({'id':'x'},{'id':'x'})
    remote[0]['source_row_json']='{ "id": "x" }'
    remote[0]['source_row_sha256']=hashlib.sha256(remote[0]['source_row_json'].encode()).hexdigest()
    r=watch.explain_changed_fields(src,remote,{'id'})
    assert r['serialization_only_records']==1
    assert watch.compare_hashes(src,remote)['changed_after_snapshot']==1


def test_real_diagnostic_path_keeps_cutover_blocked_and_issues_no_writes():
    src=source();db=FakeD1(src)
    new,old=payload_pair({'id':'private-inventory','owner_id':'a'},
                         {'id':'private-inventory','owner_id':'b'})
    src['inventory_items']=new
    db.tables[TARGETS['inventory_items'][0]]=old
    r=watch.verify_shadow(db,src,{'catalogue-1':H},explain_drift=True,
        source_schema={'inventory_items':[{'column':'id'},{'column':'owner_id'}]})
    assert r['column_drift_diagnostics']['inventory_items']['changed_field_counts']=={'owner_id':1}
    assert r['status']=='READ_ONLY_OPERATIONAL_D1_SNAPSHOT_STALE'
    assert r['safely_authorizes_cutover'] is False
    assert db.write_calls==0
    assert 'private-inventory' not in json.dumps(r)
