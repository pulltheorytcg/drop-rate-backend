"""Fixed source evidence survives retries without promoting deferred editions."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil

import pytest

from app import catalogue_source_archives as archive
from app.object_storage import ObjectStorageConfig, ObjectStorageError, S3ObjectStorage


ROOT = Path(__file__).resolve().parents[1]


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class MemoryS3:
    """Exercise the actual storage uploader and readback, not a trusted receipt stub."""
    def __init__(self):
        self.objects = {}
        self.puts = 0
        self.corrupt_upload = False
        self.interrupt_after = None

    def get_object(self, *, Bucket, Key):
        assert Bucket == "private-source-test"
        if Key not in self.objects:
            raise MissingObject()
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        assert Bucket == "private-source-test"
        assert ContentType in {"application/gzip", "application/json"}
        if self.interrupt_after is not None and self.puts >= self.interrupt_after:
            raise TimeoutError("interrupted fixture upload")
        data = Body.read()
        assert Metadata["sha256"] == hashlib.sha256(data).hexdigest()
        self.puts += 1
        self.objects[Key] = data[:-1] if self.corrupt_upload else data


@pytest.fixture
def store():
    return S3ObjectStorage(ObjectStorageConfig(
        endpoint="https://test.r2.cloudflarestorage.com", bucket="private-source-test",
        region="auto", access_key_id="fixture-only", secret_access_key="fixture-only"), client=MemoryS3())


@pytest.fixture
def copied_source(tmp_path):
    for item in archive.INPUTS:
        destination = tmp_path / item.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / item.path, destination)
    return tmp_path


def run_archive(**kwargs):
    return asyncio.run(archive.archive_reviewed_openlibrary_sources(**kwargs))


def test_offline_checkpoint_has_no_storage_configuration_and_keeps_deferred_hold(monkeypatch, store):
    def forbidden():
        raise AssertionError("Dry run must not load credentials")

    monkeypatch.setattr(archive, "configured_object_storage", forbidden)
    report = run_archive(storage=store)
    assert report == run_archive(storage=store)
    assert report["status"] == "DRY_RUN" and report["uploaded"] is False
    assert report["file_count"] == 14 and report["source_bytes"] == 6228589
    assert store.client.puts == 0 and "manifest_object" not in report
    manifest = report["manifest"]
    assert manifest["source_commit"] == "51a32083990202b9d6c91f5424e03f3459d5b427"
    assert manifest["metadata_license"] == "https://openlibrary.org/developers/licensing"
    assert manifest["archive_grants_publication_rights"] is False
    assert manifest["contains_original_dump"] is manifest["contains_cover_bytes"] is False
    cohorts = manifest["cohorts"]
    assert cohorts["source_selected_records"] == 2420 and cohorts["novel_records"] == 2404
    assert cohorts["historically_imported_records"] == 1495 and cohorts["deferred_records"] == 909
    assert cohorts["deferred_status"] == "DEFERRED_COHORT_HELD_PENDING_REVIEW"
    assert cohorts["deferred_form_review_findings"] == 6 and cohorts["historical_exact_review_holds"] == 57
    assert cohorts["basis"] == "HASH_BOUND_HISTORICAL_RECEIPTS_NOT_A_LIVE_DATABASE_READ"
    assert all(value == 0 for value in manifest["effects"].values())
    assert "CC0" not in json.dumps(manifest)


def test_private_archive_roundtrips_exact_bytes_and_retry_reuses_verified_objects(store):
    first = run_archive(apply=True, storage=store)
    assert first["status"] == "BYTES_VERIFIED" and first["uploaded"] is True
    assert store.client.puts == 15
    manifest_receipt = first["manifest_object"]
    saved = store.client.objects[manifest_receipt["key"]]
    assert json.loads(saved) == first["manifest"]
    assert hashlib.sha256(saved).hexdigest() == manifest_receipt["sha256"]
    for item in first["manifest"]["files"]:
        receipt = item["object"]
        raw = gzip.decompress(store.client.objects[receipt["key"]])
        assert raw == (ROOT / item["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        assert receipt["verified"] is True and receipt["key"].startswith("drop-rate/exports/")
    assert run_archive(apply=True, storage=store) == first
    assert store.client.puts == 15, "Retry must verify/reuse every object without adding new copies"


@pytest.mark.parametrize("change", ["same_size_mutation", "truncation", "oversize", "missing", "symlink"])
def test_any_changed_input_blocks_all_uploads_even_when_it_is_the_last_file(copied_source, store, change):
    item = archive.INPUTS[-1]
    target = copied_source / item.path
    if change == "same_size_mutation":
        data = target.read_bytes()
        target.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    elif change == "truncation":
        target.write_bytes(target.read_bytes()[:-1])
    elif change == "oversize":
        target.write_bytes(b"x" * (archive.MAX_FILE_BYTES + 1))
    elif change == "missing":
        target.unlink()
    else:
        target.unlink()
        target.symlink_to(ROOT / item.path)
    with pytest.raises(archive.SourceArchiveError):
        run_archive(apply=True, storage=store, source_root=copied_source)
    assert store.client.puts == 0


def test_corrupt_uploaded_bytes_never_produce_manifest_or_completion(store):
    store.client.corrupt_upload = True
    with pytest.raises(ObjectStorageError):
        run_archive(apply=True, storage=store)
    assert store.client.puts == 1
    assert not any(key.endswith(".manifest.json") for key in store.client.objects)


def test_corrupt_existing_object_is_not_overwritten_or_treated_as_complete(store):
    first = run_archive(apply=True, storage=store)
    key = first["manifest"]["files"][0]["object"]["key"]
    store.client.objects[key] = b"corrupted existing object"
    with pytest.raises(ObjectStorageError):
        run_archive(apply=True, storage=store)
    assert store.client.puts == 15
    assert store.client.objects[key] == b"corrupted existing object"


def test_interrupted_batch_reuses_verified_prefix_on_retry(store):
    store.client.interrupt_after = 3
    with pytest.raises(TimeoutError):
        run_archive(apply=True, storage=store)
    saved = dict(store.client.objects)
    assert len(saved) == 3 and not any(key.endswith(".manifest.json") for key in saved)
    store.client.interrupt_after = None
    result = run_archive(apply=True, storage=store)
    assert result["status"] == "BYTES_VERIFIED" and store.client.puts == 15
    assert all(store.client.objects[key] == data for key, data in saved.items())


@pytest.mark.parametrize("field,value", [("verified", False), ("sha256", "0" * 64),
                                         ("size_bytes", 1), ("key", "drop-rate/private-media/unrelated.webp")])
def test_storage_receipt_must_bind_exact_uploaded_export(monkeypatch, store, field, value):
    original = store.put_verified_file

    def altered(*args, **kwargs):
        return {**original(*args, **kwargs), field: value}

    monkeypatch.setattr(store, "put_verified_file", altered)
    with pytest.raises(archive.SourceArchiveError, match="storage receipt"):
        run_archive(apply=True, storage=store)
    assert store.client.puts == 1
    assert not any(key.endswith(".manifest.json") for key in store.client.objects)


def test_deferred_evidence_cannot_be_relabelled_ready_by_archive():
    # Exercise the semantic binding separately from the independent byte pins.
    payloads = archive._read_inputs(ROOT)
    path = archive.EVIDENCE + "book-deferred-review-20261027.json"
    evidence = json.loads(payloads[path])
    evidence["status"] = "READY_TO_IMPORT"
    payloads[path] = json.dumps(evidence).encode()
    with pytest.raises(archive.SourceArchiveError, match="Deferred review"):
        archive._cohorts(payloads)


def test_file_and_total_limits_cannot_expand_the_fixed_archive(monkeypatch, store):
    monkeypatch.setattr(archive, "MAX_TOTAL_BYTES", 1000)
    with pytest.raises(archive.SourceArchiveError, match="byte limit"):
        run_archive(apply=True, storage=store)
    assert store.client.puts == 0
