"""Offline guards for real R2 byte-readback; synthetic keys only."""
from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from scripts import audit_cloudflare_media_bytes as audit
from app.object_storage import ObjectStorageError


WEBP=b"RIFF"+(8).to_bytes(4,"little")+b"WEBP"+b"DATA"
H=hashlib.sha256(WEBP).hexdigest()


def row(id,provider=None,*,bad=False):
    record={
        "object_key":f"drop-rate/private-media/{H}.webp",
        "content_sha256":H,
        "size_bytes":len(WEBP),
    }
    if provider is None:
        record.update(media_asset_id=id,asset_sha256=H)
    else:
        record.update(provider=provider,system_code="POKEMON",
                      language="EN",provider_id=id)
    if bad: record["size_bytes"]=len(WEBP)+1
    return record


@pytest.fixture(autouse=True)
def bounded(monkeypatch):
    monkeypatch.setattr(audit,"PHYSICAL_MIN",1)
    monkeypatch.setattr(audit,"REFERENCE_MIN",8)
    monkeypatch.setattr(audit,"PROBES_PER_PROVIDER",2)


def fixtures():
    return [row("media1")],[
        row(p+"-a",p) for p in sorted(audit.REF_PROVIDER_NAMES)
    ] + [row(p+"-b",p) for p in sorted(audit.REF_PROVIDER_NAMES)]


def test_exact_r2_hash_size_key_and_owner_mirror():
    physical,ref=fixtures()
    chosen,providers,index_sha=audit.verify_metadata(physical,ref,"drop-rate")
    assert len(chosen)==8
    assert providers=={p:2 for p in audit.REF_PROVIDER_NAMES}
    assert len(index_sha)==64
    assert audit.assert_mirror(physical[0],"drop-rate")==(
        physical[0]["object_key"],H,len(WEBP))


def test_rejects_any_spoofed_or_unapproved_source_identity():
    p,r=fixtures()
    variants=[
        {**p[0],"object_key":"different/safe.jpg"},
        {**p[0],"content_sha256":"0"*64},
        {**p[0],"asset_sha256":"0"*64},
        {**p[0],"size_bytes":0},
        {**p[0],"size_bytes":True},
    ]
    for entry in variants:
        with pytest.raises(audit.MediaByteAuditError):
            audit.verify_metadata([entry],r,"drop-rate")
    unknown={**r[0],"provider":"unreviewed"}
    with pytest.raises(audit.MediaByteAuditError):
        audit.verify_metadata(p,[unknown,*r[1:]],"drop-rate")


def test_no_false_full_reference_coverage_with_a_sample_only():
    p,r=fixtures()
    assert audit.REFERENCE_MIN==8
    with pytest.raises(audit.MediaByteAuditError,match="behind RLS or reduced"):
        audit.verify_metadata(p,r[:1],"drop-rate")
    with pytest.raises(audit.MediaByteAuditError,match="duplicated"):
        audit.verify_metadata([p[0],p[0]],r,"drop-rate")


class FakeStorage:
    def __init__(self,*,bad_key=None):
        self.bad_key=bad_key
        self.calls=[]
    def _bounded_reference_client(self):
        return self
    def read_verified_media(self,key,*,expected_sha256,expected_size):
        self.calls.append((key,expected_sha256,expected_size))
        if self.bad_key is not None and key==self.bad_key:
            raise ObjectStorageError("fake private failure with secret path")
        if hashlib.sha256(WEBP).hexdigest()!=expected_sha256 or expected_size!=len(WEBP):
            raise ObjectStorageError("bad byte hash")
        return WEBP


@pytest.mark.asyncio
async def test_actual_R2_reader_counts_success_and_fails_closed_without_leaking_keys():
    p,r=fixtures()
    successful=FakeStorage()
    ok,bad=await audit.verify_actual_bytes(successful,p+r)
    assert (ok,bad)==(9,0)
    assert len(successful.calls)==9
    failing=FakeStorage(bad_key="drop-rate/private-media/"+H+".webp")
    ok,bad=await audit.verify_actual_bytes(failing,p+r)
    assert (ok,bad)==(0,9)


def test_read_budget_rejects_unbounded_download():
    p,r=fixtures()
    assert audit.MAX_TOTAL_SELECTED_BYTES<=105_000_000
    assert audit.CONCURRENCY<=8
    assert audit.MAX_FILE<=10_000_000


def test_full_reference_mode_has_strict_opt_in(monkeypatch):
    monkeypatch.delenv("TCG_FULL_R2_REFERENCE_BYTE_AUDIT_ENABLED",raising=False)
    with pytest.raises(audit.MediaByteAuditError,match="explicit one-shot opt-in"):
        asyncio.run(audit.run(all_references=True))


def test_full_reference_mode_hashes_entire_snapshot_not_just_sample():
    p,r=fixtures()
    sample,provider_counts,digest=audit.verify_metadata(
        p,r,"drop-rate",all_references=True)
    assert len(sample)==8
    assert len(provider_counts)==4
    assert len(digest)==64
    assert audit.MAX_FULL_REFERENCE_BYTES<=7_000_000_000
    assert audit.READ_BATCH<=480


@pytest.mark.asyncio
async def test_batching_over_multiple_pages_is_lossless(monkeypatch):
    monkeypatch.setattr(audit,"READ_BATCH",3)
    p,r=fixtures()
    storage=FakeStorage()
    ok,bad=await audit.verify_actual_bytes(storage,p+r)
    assert (ok,bad)==(9,0)
    assert len(storage.calls)==9


@pytest.mark.asyncio
async def test_only_transient_r2_read_failure_is_retried_and_verified():
    p,r=fixtures()
    class OneTransient(FakeStorage):
        failures=0
        def read_verified_media(self,key,*,expected_sha256,expected_size):
            if self.failures==0:
                self.failures+=1
                raise ObjectStorageError("Mirrored media unavailable or invalid")
            return super().read_verified_media(key,expected_sha256=expected_sha256,
                                              expected_size=expected_size)
    storage=OneTransient()
    ok,bad=await audit.verify_actual_bytes(storage,p+r)
    assert (ok,bad)==(9,0)
    assert storage.failures==1


@pytest.mark.asyncio
async def test_sha_integrity_failure_is_never_retried():
    p,r=fixtures()
    class Corrupt(FakeStorage):
        def read_verified_media(self,key,*,expected_sha256,expected_size):
            self.calls.append(key)
            raise ObjectStorageError("Mirrored media failed byte-for-byte verification")
    storage=Corrupt()
    ok,bad=await audit.verify_actual_bytes(storage,p+r)
    assert (ok,bad)==(0,9)
    assert len(storage.calls)==9


@pytest.mark.asyncio
async def test_persistent_transient_failure_still_fails_with_bounded_retry():
    p,r=fixtures()
    class Unavailable(FakeStorage):
        def read_verified_media(self,key,*,expected_sha256,expected_size):
            self.calls.append(key)
            raise ObjectStorageError("Mirrored media unavailable or invalid")
    storage=Unavailable()
    ok,bad=await audit.verify_actual_bytes(storage,p+r)
    assert (ok,bad)==(0,9)
    assert len(storage.calls)==27
