"""Offline integrity gate for the recovered, already imported book cohort.

These checks bind the recovered source snapshots to the historical review and
production receipts. They do not contact providers, replay SQL or assert fresh
production state. The dated hashes are deliberately independent of the parser.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import pytest

from app.book_catalogue_sources import canonical_json, normalise, validate_entry
from app.book_openlibrary_bulk import (
    QUALITY_VERSION,
    SUBJECT_PROJECTION,
    VERSION,
    classification_hold,
    reviewed_hold_registry,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend/app/data"
INITIAL = "book_openlibrary_initial_reviewed_20261027"
FULL = "book_openlibrary_full_20261027"
INITIAL_SHA = "dc10814daac57325fa766b730c92567b4da5454487e67ef8fe5cdf9802d5def3"
FULL_SHA = "94391f9c867678e1773031d58d09c549d6e1555d2dcf903419021d51fc077a23"
NORMALIZED_SHA = "d2829f0d62ff504ef30885aed87a20067e3ac1fd218053eb904f3b80104ba54d"
HOLDS_SHA = "72f742bd619b4586e15328f72fa30ff9628c0dfdc2b84a8d31b3590136ccacd0"
SUBJECTS_SHA = "fc99c7f72222a2568dc50f95b9afcd6d7f52783e87a65c23f436cc47dcbe4849"
REMOVED_SOURCE_IDS = {
    "OL12501935M", "OL12503067M", "OL12558827M", "OL12558829M", "OL12558830M",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def recovered():
    snapshots = {}
    for name in (INITIAL, FULL):
        data = (DATA / f"{name}.jsonl").read_bytes()
        rows = [json.loads(line) for line in data.splitlines()]
        entries = [normalise("OPEN_LIBRARY", row) for row in rows]
        for entry in entries:
            validate_entry(entry)
        snapshots[name] = {
            "data": data,
            "rows": rows,
            "entries": entries,
            "receipt": read_json(DATA / f"{name}.selection.json"),
        }
    return snapshots


@pytest.mark.parametrize("name,count,digest", [(INITIAL, 1495, INITIAL_SHA), (FULL, 2420, FULL_SHA)])
def test_recovered_snapshots_retain_unique_reviewed_metadata_only(name, count, digest, recovered):
    snapshot = recovered[name]
    rows, entries, receipt = snapshot["rows"], snapshot["entries"], snapshot["receipt"]
    registry, registry_sha = reviewed_hold_registry()
    assert sha256(snapshot["data"]) == digest == receipt["selected_snapshot_sha256"]
    assert len(rows) == count == receipt["exported_records"]
    assert registry_sha == HOLDS_SHA and len(registry) == 57
    source_ids = {entry["record_id"] for entry in entries}
    isbns = {entry["book"]["barcode_gtin"] for entry in entries}
    assert len(source_ids) == len(isbns) == count
    assert source_ids.isdisjoint({hold["source_id"] for hold in registry.values()})
    assert isbns.isdisjoint(registry)
    assert all(classification_hold(row, reviewed=registry) is None for row in rows)
    for entry in entries:
        assert entry["provider"] == "OPEN_LIBRARY"
        assert entry["image_url"] is None and entry["reference"] is None
        assert all(entry["book"][field] is None for field in ("printing_number", "cover_code", "cover_artist"))


def test_initial_cohort_preserves_exact_review_order_without_refill(recovered):
    snapshot = recovered[INITIAL]
    entries, receipt = snapshot["entries"], snapshot["receipt"]
    normalized_bytes = "".join(canonical_json(entry) + "\n" for entry in entries).encode("utf-8")
    assert sha256(normalized_bytes) == NORMALIZED_SHA
    retained = [
        {"source_id": entry["record_id"], "isbn": entry["book"]["barcode_gtin"],
         "record_digest": entry["record_digest"]}
        for entry in entries
    ]
    assert retained == receipt["retained_normalized_record_digests"]
    assert sha256(canonical_json(retained).encode("utf-8")) == receipt["retained_normalized_record_digests_sha256"]
    assert receipt["selection_order"] == "reviewed_1500_cohort_order_minus_5_exact_holds_no_refill"
    assert receipt["selection_kind"] == "REVIEWED_COHORT_SUBSET"
    assert set(receipt["removed_source_ids"]) == REMOVED_SOURCE_IDS
    assert {entry["record_id"] for entry in entries}.isdisjoint(REMOVED_SOURCE_IDS)
    assert receipt["reviewed_parent_cohort_records"] - len(REMOVED_SOURCE_IDS) == len(entries)
    assert receipt["parent_full_selected_snapshot_sha256"] == FULL_SHA
    full_rows = {row["edition"]["key"]: row for row in recovered[FULL]["rows"]}
    assert all(row == full_rows[row["edition"]["key"]] for row in snapshot["rows"])
    assert len(full_rows) - receipt["existing_candidate_isbns_excluded"] - len(entries) == receipt["deferred_novel_records"] == 909


def test_receipts_bind_original_subjects_full_dump_and_exact_hold_registry(recovered):
    subject_path = DATA / "book_openlibrary_original_subject_review_20261027.json"
    subjects = read_json(subject_path)
    assert sha256(subject_path.read_bytes()) == SUBJECTS_SHA
    assert subjects["full_source_read"] is True and subjects["gzip_crc_verified"] is True
    by_source = {record["source_id"]: record for record in subjects["records"]}
    assert len(by_source) == subjects["matched_source_records"] == 2537
    for snapshot in recovered.values():
        receipt = snapshot["receipt"]
        assert receipt["version"] == VERSION
        assert receipt["status"] == "COMPLETE"
        assert all(receipt[field] is True for field in ("complete_dump_read", "source_file_verified", "gzip_crc_verified"))
        assert receipt["subject_projection"] == SUBJECT_PROJECTION
        assert receipt["export_quality"]["version"] == QUALITY_VERSION
        assert receipt["export_quality"]["reviewed_holds_sha256"] == HOLDS_SHA
        assert receipt["export_quality"]["reviewed_hold_records"] == 57
        assert receipt["original_subject_review"]["sha256"] == SUBJECTS_SHA
        assert receipt["source"] == subjects["source"]
        assert receipt["sha1"] == subjects["source_sha1"]
        assert receipt["size"] == subjects["source_size"]
        for row in snapshot["rows"]:
            original = by_source[row["edition"]["key"].rsplit("/", 1)[-1]]
            assert row["edition"]["subjects"] == [s for s in original["original_subjects"] if len(s) <= 200]


def test_saved_committed_batches_cover_initial_cohort_once_and_no_deferred_rows(recovered):
    evidence = read_json(ROOT / "docs/evidence/book-openlibrary-production-import-20261027.json")
    entries = recovered[INITIAL]["entries"]
    binding = evidence["source_binding"]
    assert binding["initial_snapshot_sha256"] == INITIAL_SHA
    assert binding["normalized_cohort_sha256"] == NORMALIZED_SHA
    assert binding["selection_receipt_sha256"] == sha256((DATA / f"{INITIAL}.selection.json").read_bytes())
    assert binding["reviewed_holds_sha256"] == HOLDS_SHA
    assert binding["original_subject_review_sha256"] == SUBJECTS_SHA
    assert evidence["production_completion"]["receipt_id"] == "fb47fea2-ff75-4e46-b468-468288d6de17"
    assert evidence["production_completion"]["status"] == "COMPLETE"
    batches = evidence["batches"]
    assert [batch["number"] for batch in batches] == list(range(1, 31))
    committed = []
    for batch in batches:
        receipt, readback = batch["receipt"], batch["readback"]
        records = receipt["records"]
        assert receipt["snapshot_sha256"] == INITIAL_SHA
        assert receipt["batch"] == readback["batch"]
        assert receipt["statuses"] == {"IMPORTED": len(records)}
        assert len(records) == readback["expected"] == readback["matching_source_digests"] == readback["new_structured"]
        assert all(readback[field] == 0 for field in ("missing", "conflicting_source_digests", "new_with_invented_printing"))
        assert all(record["status"] == "IMPORTED" and record["reason"] is None for record in records)
        committed.extend(records)
    assert [len(batch["receipt"]["records"]) for batch in batches] == [50] * 29 + [45]
    assert [row["line"] for row in committed] == list(range(1, 1496))
    assert [(row["source_id"], row["record_digest"]) for row in committed] == [
        (entry["record_id"], entry["record_digest"]) for entry in entries
    ]
    assert len({row["catalogue_id"] for row in committed}) == 1495
    assert evidence["verification"]["source_derived_systems"] == dict(Counter(entry["book"]["system_code"] for entry in entries))
    assert evidence["verification"]["new_market_values"] == evidence["verification"]["new_cover_artwork"] == 0
    assert evidence["local_stage_reconciliation"]["full_stage"]["statuses"] == {"IMPORTED": 1495, "READY": 909}
