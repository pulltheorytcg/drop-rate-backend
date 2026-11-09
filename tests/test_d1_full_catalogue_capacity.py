"""Source catalogue D1 capacity checks never mutate Cloudflare resources."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import d1_full_catalogue_capacity as cap  # noqa: E402
from d1_r2_real_shadow import MigrationGuard  # noqa: E402

UUID = "12345678-1234-1234-1234-1234567890ab"
NEW_YGO_SHA="f"*64


class ReadOnlyD1:
    database_names = ["drop-rate-d1-real-yugioh-shadow", "synthetic-a"]
    current = 8000
    pointer = None
    pages = 1200
    total_queries = 0
    newer=False

    def __init__(self,account,token):
        assert account==cap.ACCOUNT
        assert token=="scoped-test-token"
        self.path=f"/accounts/{account}/d1/database"

    def call(self,method,path,data=None):
        assert method=="GET"
        assert data is None
        assert path==f"{self.path}/{UUID}"
        type(self).total_queries+=1
        return {"file_size":self.pages*4096,"uuid":UUID},1.2

    def list_databases(self):
        return [{"name":name,"uuid":UUID} for name in self.database_names]

    def query(self,uuid,sql,params=()):
        assert uuid==UUID
        assert not any(bad in sql.lower() for bad in (
            "insert ","update ","delete ","drop ","create ","alter "
        ))
        type(self).total_queries += 1
        assert not sql.lower().startswith("pragma")
        if "from shadow_generations" in sql:
            rows=[{"manifest_sha":cap.YGO_MANIFEST_SHA,
                   "expected_rows":cap.YGO_TOTAL,"projection_sha":"a"*64}]
            if self.newer:
                rows.append({"manifest_sha":NEW_YGO_SHA,
                             "expected_rows":cap.YGO_TOTAL+1,"projection_sha":"b"*64})
        elif "count(*)" in sql:
            assert params and len(params)==1
            sha=params[0]
            if sha==NEW_YGO_SHA:
                rows=[{"n":self.current}]
            elif sha==cap.YGO_MANIFEST_SHA:
                rows=[{"n":cap.YGO_TOTAL if self.newer else self.current}]
            else:
                raise AssertionError("Unexpected D1 source generation")
        elif "shadow_active_partitions" in sql:
            assert params==cap.YGO_SCOPE
            rows=[{"manifest_sha":self.pointer}] if self.pointer else []
        else:
            raise AssertionError("Unapproved D1 SQL")
        return {"success":True,"results":rows}, 1.2


@pytest.fixture(autouse=True)
def safe_fake(monkeypatch):
    ReadOnlyD1.database_names=["drop-rate-d1-real-yugioh-shadow","synthetic-a"]
    ReadOnlyD1.current=8000
    ReadOnlyD1.pointer=None
    ReadOnlyD1.pages=1200
    ReadOnlyD1.total_queries=0
    ReadOnlyD1.newer=False
    monkeypatch.setattr(cap,"D1Client",ReadOnlyD1)


def test_current_verified_yugioh_batch_does_not_unlock_other_writes():
    report=cap.inspect_capacity(cap.ACCOUNT,"scoped-test-token")
    assert report["status"]=="READ_ONLY_D1_ACCOUNT_INVENTORY_VERIFIED"
    assert report["yugioh_staged_rows"]==8000
    assert not report["yugioh_full_active_parity"]
    assert not report["subsequent_import_allowed_by_static_readiness"]
    assert report["visible_database_count"]==2
    assert report["d1_writes"]==0
    assert not report["daily_account_write_quota_measured"]
    assert ReadOnlyD1.total_queries==5


def test_full_source_and_active_pointer_allows_later_review():
    ReadOnlyD1.current=45418
    ReadOnlyD1.pointer=cap.YGO_MANIFEST_SHA
    report=cap.inspect_capacity(cap.ACCOUNT,"scoped-test-token")
    assert report["yugioh_full_active_parity"]
    assert report["subsequent_import_allowed_by_static_readiness"]
    assert report["owner_or_settlement_writes"]==0
    assert not report["production_reads_switched"]



def test_capacity_tracks_newer_verified_active_yugioh_generation():
    ReadOnlyD1.newer=True
    ReadOnlyD1.current=cap.YGO_TOTAL+1
    ReadOnlyD1.pointer=NEW_YGO_SHA
    report=cap.inspect_capacity(cap.ACCOUNT,"scoped-test-token")
    assert report["yugioh_source_rows"]==cap.YGO_TOTAL+1
    assert report["yugioh_staged_rows"]==cap.YGO_TOTAL+1
    assert report["yugioh_full_active_parity"] is True
    assert report["subsequent_import_allowed_by_static_readiness"] is True
    assert report["d1_writes"]==0


def test_capacity_rejects_old_active_as_complete_when_newer_is_partial():
    ReadOnlyD1.newer=True
    ReadOnlyD1.current=24000
    ReadOnlyD1.pointer=cap.YGO_MANIFEST_SHA
    report=cap.inspect_capacity(cap.ACCOUNT,"scoped-test-token")
    assert report["yugioh_source_rows"]==cap.YGO_TOTAL+1
    assert report["yugioh_staged_rows"]==24000
    assert report["yugioh_full_active_parity"] is False
    assert report["subsequent_import_allowed_by_static_readiness"] is False


def test_saturated_account_blocks_new_database():
    ReadOnlyD1.database_names=[cap.YGO]+[f"synthetic-{n}" for n in range(9)]
    ReadOnlyD1.current=45418
    ReadOnlyD1.pointer=cap.YGO_MANIFEST_SHA
    report=cap.inspect_capacity(cap.ACCOUNT,"scoped-test-token")
    assert report["visible_database_count"]==10
    assert not report["has_space_for_one_new_database_by_count"]
    assert not report["subsequent_import_allowed_by_static_readiness"]


def test_database_near_free_tier_capacity_blocks_new_import():
    ReadOnlyD1.pages=100000
    ReadOnlyD1.current=45418
    ReadOnlyD1.pointer=cap.YGO_MANIFEST_SHA
    report=cap.inspect_capacity(cap.ACCOUNT,"scoped-test-token")
    assert report["largest_database_bytes"]==409_600_000
    assert not report["existing_database_storage_under_safety_threshold"]
    assert not report["subsequent_import_allowed_by_static_readiness"]


def test_active_pointer_cannot_claim_full_with_partial_source():
    ReadOnlyD1.current=8000
    ReadOnlyD1.pointer=cap.YGO_MANIFEST_SHA
    with pytest.raises(MigrationGuard,match="active pointer is inconsistent"):
        cap.inspect_capacity(cap.ACCOUNT,"scoped-test-token")


def test_unapproved_account_never_attempts_api():
    with pytest.raises(MigrationGuard,match="account differs"):
        cap.inspect_capacity("0"*32,"scoped-test-token")


def test_capacity_workflow_has_valid_tokens_without_d1_changes():
    workflow=(Path(__file__).resolve().parents[1]/
              ".github/workflows/d1-full-catalogue-capacity.yml").read_text()
    assert (chr(92)+"${{") not in workflow
    assert "CLOUDFARE_D1_PILOT_TOKEN: "+"${{ secrets.CLOUDFARE_D1_PILOT_TOKEN }}" in workflow
    assert "contents: read" in workflow
    assert "python tools/d1_full_catalogue_capacity.py" in workflow


def test_missing_supported_cloudflare_metadata_fails_closed(monkeypatch):
    class NoSize(ReadOnlyD1):
        def call(self,method,path,data=None):
            return {"uuid":UUID},0
    monkeypatch.setattr(cap,"D1Client",NoSize)
    with pytest.raises(MigrationGuard,match="file_size"):
        cap.inspect_capacity(cap.ACCOUNT,"scoped-test-token")


def test_official_file_size_metadata_allows_integer_floats(monkeypatch):
    class FloatSize(ReadOnlyD1):
        def call(self,method,path,data=None):
            return {"file_size":float(4096*1200)},0
    monkeypatch.setattr(cap,"D1Client",FloatSize)
    proof=cap.inspect_capacity(cap.ACCOUNT,"scoped-test-token")
    assert proof["largest_database_bytes"]==4096*1200
    assert proof["d1_writes"]==0
