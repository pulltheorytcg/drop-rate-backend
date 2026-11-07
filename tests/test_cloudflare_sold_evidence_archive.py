"""Synthetic, no-network UK sold evidence archive controls."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts import archive_cloudflare_sold_evidence as arc

H="a"*64
ROOT="0c61ae41-2206-4204-bbe1-e8033eccfeea"
CARD="efce33be-8749-41bc-bd41-a509f8e34be5"


@pytest.fixture(autouse=True)
def source_floor(monkeypatch):
    monkeypatch.setattr(arc,"MIN_SOLD_ROWS",1)


def row(**changes):
    values={
      "id":ROOT,"catalogue_id":CARD,"source":"EBAY",
      "source_record_key":H,"observation_type":"SOLD",
      "observed_at":"2026-11-01T19:00:00+00:00",
      "price_minor":1999,"shipping_minor":200,"currency":"GBP",
      "price_gbp_minor":1999,"shipping_gbp_minor":200,
      "condition":"NM","grading_company":None,"grade":None,
      "language":"English","seal_status":None,"source_country":"GB",
      "sample_size":1,"evidence_quality":1.0,
      "ingested_at":"2026-11-02T00:00:00+00:00"}
    values.update(changes)
    return json.dumps(values,separators=(",",":"),sort_keys=False)


def test_sold_projection_never_contains_freeform_provider_metadata_or_secrets():
    assert len(arc.FIELDS)==20
    assert "metadata" not in arc.FIELDS and "metadata" not in arc.QUERY
    assert "url" not in arc.FIELDS and "title" not in arc.FIELDS
    assert "auth" not in arc.QUERY.lower()
    assert arc.validate_record(row())==(ROOT,H)


@pytest.mark.parametrize("bad",[
    {"source":"CARDMARKET"},{"observation_type":"PRICE_GUIDE"},
    {"source_country":"US"},{"currency":"USD"},{"source_record_key":"password=abc"},
    {"price_gbp_minor":0},{"price_minor":-1},
    {"shipping_gbp_minor":-1},{"id":None},{"catalogue_id":None},
    {"observed_at":None},
])
def test_unapproved_evidence_fails_closed(bad):
    with pytest.raises(arc.SoldEvidenceGuard):
        arc.validate_record(row(**bad))


def test_extra_metadata_columns_do_not_sneak_into_archive():
    with pytest.raises(arc.SoldEvidenceGuard,match="columns changed"):
        arc.validate_record(row(metadata={"url":"https://example.com/unsafe"}))


def test_duplicate_or_missing_sold_proof_does_not_count_as_complete():
    with pytest.raises(arc.SoldEvidenceGuard,match="Duplicate"):
        arc.canonical_lines([row(),row()])
    with pytest.raises(arc.SoldEvidenceGuard,match="floor"):
        arc.canonical_lines([])


def test_deterministic_gzip_roundtrip_preserves_each_original_sale(tmp_path):
    raw,count,source_sha=arc.canonical_lines([row()])
    file=tmp_path/"approved.ndjson.gz"
    digest=arc.pack_and_verify(raw,file)
    assert count==1
    assert digest==hashlib.sha256(file.read_bytes()).hexdigest()
    assert gzip.decompress(file.read_bytes())==raw
    assert hashlib.sha256(raw).hexdigest()==source_sha


class FakeR2:
    def __init__(self,*,tamper:bool=False):
        self.data={}
        self.tamper=tamper
    def put_verified_file(self,path,*,category,content_type):
        assert category=="exports"
        raw=path.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        key=f"drop-rate/exports/{digest}.ndjson.gz"
        self.data[key]=raw
        return {"verified":True,"key":key,"sha256":digest,"size_bytes":len(raw)}
    def download_verified_file(self,key,target,*,expected_sha256,expected_size):
        raw=self.data[key]
        if self.tamper:
            raw=b"corrupted"+raw
        if (len(raw)!=expected_size
                or hashlib.sha256(raw).hexdigest()!=expected_sha256):
            raise arc.ObjectStorageError("Checksum mismatch")
        target.write_bytes(raw)


def test_real_byte_readback_with_synthetic_object_storage(tmp_path):
    raw,_,_=arc.canonical_lines([row()])
    path=tmp_path/"uk-sold.ndjson.gz"
    digest=arc.pack_and_verify(raw,path)
    storage=FakeR2()
    result=arc.verify_remote(storage,path,digest)
    assert result["payload"]==raw
    assert result["r2_compressed_sha256"]==digest


def test_remote_tampered_bytes_are_never_certified(tmp_path):
    raw,_,_=arc.canonical_lines([row()])
    path=tmp_path/"uk-sold.ndjson.gz"
    digest=arc.pack_and_verify(raw,path)
    with pytest.raises(arc.ObjectStorageError):
        arc.verify_remote(FakeR2(tamper=True),path,digest)


def test_apply_uses_separate_explicit_one_shot_flag(monkeypatch):
    monkeypatch.delenv("TCG_PRIVATE_SOLD_EVIDENCE_R2_APPLY_ENABLED",raising=False)
    import asyncio
    with pytest.raises(arc.SoldEvidenceGuard,match="one-shot authorisation"):
        asyncio.run(arc.run(apply=True))
