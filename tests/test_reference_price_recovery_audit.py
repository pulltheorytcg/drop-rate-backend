"""Offline recovery cannot turn archive integrity or guide quotes into fresh values."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import os
import sys

import pytest
from app.object_storage import ObjectStorageError
from test_reference_quote_source_backup import make_archive, row

spec = importlib.util.spec_from_file_location(
    "recovery_audit", Path(__file__).resolve().parents[1] / "tools/reference_price_recovery_audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
AS_OF = datetime(2026, 11, 7, tzinfo=timezone.utc)


def bundle(tmp_path, rows, mutate=None):
    archive = tmp_path / "archive.gz"
    manifest = make_archive(archive, rows, "reference_market_prices")
    if mutate:
        mutate(manifest)
    path = tmp_path / "manifest.json"
    data = json.dumps(manifest).encode()
    path.write_bytes(data)
    return path, archive, hashlib.sha256(data).hexdigest()


def run(paths, as_of=AS_OF):
    return audit.audit_archive(paths[0], paths[1], expected_manifest_sha256=paths[2], as_of=as_of)


def test_expired_guides_missing_and_claimed_sold_evidence_are_never_promoted(tmp_path):
    paths = bundle(tmp_path, [
        row(provider_id="1", quotes=[{"source": "TCGDEX_CARDMARKET", "physical_valuation_eligible": True}]),
        row(provider_id="2", quotes=[], market_value_minor=None, market_value_high_minor=None,
            pricing_updated_at=None),
        row(provider_id="3", quotes=[{"source": "EBAY_SOLD", "rights_approved": True}]),
    ])
    before = [p.read_bytes() for p in paths[:2]]
    result = run(paths)
    assert result == run(paths)  # Stable retry: no implicit clock or side effects.
    assert result["counts"] == {"EXPIRED": 3, "GUIDE_ONLY": 1, "MISSING_EVIDENCE": 1,
                                "NO_AMOUNT": 1, "REVIEW_REQUIRED": 1, "STORED_AMOUNT": 2}
    assert result["eligible_market_values"] == result["database_mutations"] == result["provider_requests"] == 0
    assert result["current_sql_parity"] == "NOT_VERIFIED"
    assert result["typed_restore_this_run"] is False
    assert result["deletion_authorized"] is False
    assert [p.read_bytes() for p in paths[:2]] == before
    assert 'provider_id' not in json.dumps(result)


@pytest.mark.parametrize("changes,expected", [
    ({"expires_at": "2026-11-08T00:00:00+00:00"}, "UNEXPIRED_CACHE_ONLY"),
    ({"expires_at": "2026-11-07T00:00:00+00:00"}, "EXPIRED"),
    ({"checked_at": "2026-11-08T00:00:00+00:00", "expires_at": "2026-11-09T00:00:00+00:00"}, "TIMESTAMP_REVIEW"),
    ({"quotes": [{"source": "TCGDEX_CARDMARKET", "observed_at": "2026-11-08T00:00:00+00:00"}]}, "TIMESTAMP_REVIEW"),
])
def test_clock_boundaries_do_not_imply_eligibility(tmp_path, changes, expected):
    result = run(bundle(tmp_path, [row(**changes)]))
    assert result["counts"][expected] == 1
    assert result["eligible_market_values"] == 0


@pytest.mark.parametrize("field,value", [
    ("row_count", 2), ("row_count", True), ("row_count", 0),
    ("raw_bytes", 1), ("gzip_bytes", 1), ("content_root_sha256", "0" * 64),
    ("ndjson_sha256", "0" * 64), ("source", "tcg.reference_catalogue_prices"),
    ("full_table_snapshot", False), ("fields", []),
])
def test_mismatched_proofs_are_rejected(tmp_path, field, value):
    paths = bundle(tmp_path, [row()], lambda m: m.update({field: value}))
    with pytest.raises(ObjectStorageError):
        run(paths)


@pytest.mark.parametrize("ids", [["1", "1"], ["2", "1"]])
def test_duplicate_or_unordered_identities_rejected_even_with_matching_hashes(tmp_path, ids):
    with pytest.raises(ObjectStorageError, match="identity"):
        run(bundle(tmp_path, [row(provider_id=i) for i in ids]))


def test_manifest_and_archive_tampering_rejected(tmp_path):
    paths = bundle(tmp_path, [row()])
    with pytest.raises(ObjectStorageError, match="trusted receipt"):
        run((paths[0], paths[1], "0" * 64))
    paths[1].write_bytes(b"damaged")
    with pytest.raises(ObjectStorageError, match="Archive bytes"):
        run(paths)


def test_naive_clock_and_malformed_observation_refused(tmp_path):
    paths = bundle(tmp_path, [row()])
    with pytest.raises(ObjectStorageError, match="timezone"):
        run(paths, datetime(2026, 11, 7))
    paths = bundle(tmp_path, [row(quotes=[{"observed_at": "not a timestamp"}])])
    with pytest.raises(ObjectStorageError, match="timestamp"):
        run(paths)


def test_cli_emits_no_partial_report_on_invalid_input(tmp_path):
    paths = bundle(tmp_path, [row()], lambda m: m.update(ndjson_sha256="0" * 64))
    proc = subprocess.run([sys.executable, str(audit.__file__), "--manifest", str(paths[0]),
                           "--archive", str(paths[1]), "--manifest-sha256", paths[2],
                           "--as-of", AS_OF.isoformat()], capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": "backend"})
    assert proc.returncode == 1
    assert not proc.stdout
    assert "Recovery audit refused" in proc.stderr


def test_bounded_line_reader_refuses_oversized_input(tmp_path, monkeypatch):
    paths = bundle(tmp_path, [row()])
    monkeypatch.setattr(audit.backup, "MAX_LINE_BYTES", 16)
    with pytest.raises(ObjectStorageError, match="archive line"):
        run(paths)


def test_invalid_gzip_refused_even_with_matching_compressed_digest(tmp_path):
    paths = bundle(tmp_path, [row()])
    data = b"not-gzip"
    paths[1].write_bytes(data)
    manifest = json.loads(paths[0].read_bytes())
    manifest.update(gzip_bytes=len(data), gzip_sha256=hashlib.sha256(data).hexdigest())
    raw = json.dumps(manifest).encode()
    paths[0].write_bytes(raw)
    with pytest.raises(ObjectStorageError, match="decompress"):
        run((paths[0], paths[1], hashlib.sha256(raw).hexdigest()))


def test_mixed_quotes_and_missing_source_need_review():
    assert audit.evidence_class([{"source": "TCGDEX_CARDMARKET"}, {"source": "RETAIL"}]) == "REVIEW_REQUIRED"
    assert audit.evidence_class([{}]) == "REVIEW_REQUIRED"
    assert audit.evidence_class([{"source": {}}]) == "REVIEW_REQUIRED"


def test_evaluation_clock_normalizes_offsets(tmp_path):
    paths = bundle(tmp_path, [row()])
    assert run(paths) == run(paths, datetime.fromisoformat("2026-11-07T01:00:00+01:00"))
