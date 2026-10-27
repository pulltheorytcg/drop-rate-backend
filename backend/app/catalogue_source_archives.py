"""Private, hash-pinned copies of the recovered Open Library factual evidence.

This archives one historical reviewed checkpoint. It does not fetch source
data, import records, change review decisions or establish new source rights.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import tempfile

from .object_storage import ObjectStorageError, configured_object_storage


SCHEMA = "drop-rate-catalogue-source-archive-v1"
CHECKPOINT = "openlibrary-reviewed-20261027-v1"
SOURCE_COMMIT = "51a32083990202b9d6c91f5424e03f3459d5b427"
SOURCE_URL = "https://archive.org/download/ol_dump_2026-09-30/ol_dump_editions_2026-09-30.txt.gz"
SOURCE_SHA1 = "c2b534d524ba7de1b7161574da00b3ffb51d2d69"
LICENSING_URL = "https://openlibrary.org/developers/licensing"
MAX_FILES = 16
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 8_000_000
DATA = "backend/app/data/"
EVIDENCE = "docs/evidence/"


@dataclass(frozen=True, slots=True)
class SourceInput:
    path: str
    sha256: str
    size_bytes: int
    role: str


# These are the committed bytes, not hashes learned from an upload request.
# New monthly cohorts require a separately reviewed checkpoint definition.
INPUTS = (
    SourceInput(DATA + "book_openlibrary_dump_20260930_manifest.json",
        "ee43bd914c9dfa928152556d366fdaf73d61bf75d577f5a7ff4b2485ad5fb234", 348, "OFFICIAL_DUMP_MANIFEST"),
    SourceInput(DATA + "book_openlibrary_full_20261027.jsonl",
        "94391f9c867678e1773031d58d09c549d6e1555d2dcf903419021d51fc077a23", 1444649, "SOURCE_SELECTED_2420"),
    SourceInput(DATA + "book_openlibrary_full_20261027.selection.json",
        "1448b072ce33234685df9c65ccf20a73bf31ae869aa2bfbd4c5e433ec366f87b", 4847, "FULL_SELECTION_RECEIPT"),
    SourceInput(DATA + "book_openlibrary_full_20261027.review.json",
        "64089d9b62f9b078d7ee8d88180889645d0dee28a08cbd29b675349ef910344f", 153364, "EXPORT_QUALITY_REVIEW"),
    SourceInput(DATA + "book_openlibrary_recovery_20261027.jsonl",
        "84d28339c7cab469715d02dc16c351a0347ec5b406f29fea4fc1abca7a1ff65e", 1434897, "NOVEL_2404_PARTIALLY_IMPORTED"),
    SourceInput(DATA + "book_openlibrary_recovery_20261027.selection.json",
        "28cbfc6cc28a55b5bf02177d5b50b67ba53c0fb3d85751231784bf4a6314d8ac", 4891, "NOVEL_SELECTION_RECEIPT"),
    SourceInput(DATA + "book_openlibrary_recovery_20261027.import-plan.json",
        "278b43782df2712fe7cb1b50b7f247427a68f3be8fc2b1e5a9b3f3ce053f95b5", 52588, "HISTORICAL_IMPORT_PLAN"),
    SourceInput(DATA + "book_openlibrary_initial_reviewed_20261027.jsonl",
        "dc10814daac57325fa766b730c92567b4da5454487e67ef8fe5cdf9802d5def3", 896846, "HISTORICAL_IMPORTED_1495"),
    SourceInput(DATA + "book_openlibrary_initial_reviewed_20261027.selection.json",
        "9c2c5d4d536753aee73b9e38d0c771fb7825e7fabb9c683cb642f3dadc81458c", 255672, "INITIAL_REVIEW_NO_REFILL"),
    SourceInput(DATA + "book_openlibrary_original_subject_review_20261027.json",
        "fc99c7f72222a2568dc50f95b9afcd6d7f52783e87a65c23f436cc47dcbe4849", 1378537, "ORIGINAL_SUBJECT_EVIDENCE"),
    SourceInput(DATA + "book_openlibrary_review_holds.json",
        "72f742bd619b4586e15328f72fa30ff9628c0dfdc2b84a8d31b3590136ccacd0", 70068, "UNCHANGED_57_REVIEW_HOLDS"),
    SourceInput(EVIDENCE + "book-openlibrary-production-import-20261027.json",
        "c80cfc9953684ee8ecd103ffcbd9fa0188767d7c2c533f1a7420e881df43abaf", 510598, "HISTORICAL_COMMITTED_IMPORT_RECEIPTS"),
    SourceInput(EVIDENCE + "book-deferred-review-20261027.json",
        "d69809f52e7e86b7599b928906738ab7c36113ec4b91674a51a11df92f1bcf7a", 12617, "DEFERRED_909_HELD_PENDING_REVIEW"),
    SourceInput(EVIDENCE + "book-recovery-file-integrity-20261027.json",
        "ef635cf315bba6e7cd6833937433bc3136a3b850ae46eefa35b71f589f3cda7f", 8667, "RECOVERY_FILE_INTEGRITY"),
)


class SourceArchiveError(ObjectStorageError):
    """The fixed evidence checkpoint could not be verified."""


def _json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _require(condition, reason):
    if not condition:
        raise SourceArchiveError(reason)


def _read_inputs(root):
    _require(0 < len(INPUTS) <= MAX_FILES, "Source archive file limit exceeded")
    _require(len({item.path for item in INPUTS}) == len(INPUTS), "Duplicate source archive path")
    _require(sum(item.size_bytes for item in INPUTS) <= MAX_TOTAL_BYTES, "Source archive byte limit exceeded")
    result = {}
    for item in INPUTS:
        relative = Path(item.path)
        _require(not relative.is_absolute() and ".." not in relative.parts, "Invalid fixed source path")
        path = root / relative
        try:
            # Refuse both file and parent symlinks; only this fixed repo tree is read.
            _require(not any(parent.is_symlink() for parent in (path, *path.parents)
                             if parent != root and root in parent.parents), "Source archive symlink refused")
            info = path.stat()
            _require(stat.S_ISREG(info.st_mode), "Source archive input must be a regular file")
            _require(0 < item.size_bytes <= MAX_FILE_BYTES and info.st_size == item.size_bytes,
                     "Source archive input size changed: " + item.path)
            with path.open("rb") as stream:
                data = stream.read(item.size_bytes + 1)
        except OSError as exc:
            raise SourceArchiveError("Source archive input unavailable: " + item.path) from exc
        _require(len(data) == item.size_bytes and _sha(data) == item.sha256,
                 "Source archive input hash changed: " + item.path)
        result[item.path] = data
    return result


def _cohorts(payloads):
    """Bind historical receipts and the exact source-ID partition, not live state."""
    documents = {path: json.loads(data) for path, data in payloads.items() if path.endswith(".json")}
    indexed = {}
    for stem, count in (("full", 2420), ("recovery", 2404), ("initial_reviewed", 1495)):
        base = DATA + "book_openlibrary_" + stem + "_20261027"
        rows = [json.loads(line) for line in payloads[base + ".jsonl"].splitlines()]
        ids = [row["edition"]["key"].removeprefix("/books/") for row in rows]
        _require(len(rows) == len(set(ids)) == count and all(re.fullmatch(r"OL\d+M", key) for key in ids),
                 "Source cohort identity/count mismatch")
        indexed[stem] = dict(zip(ids, rows))
        selection = documents[base + ".selection.json"]
        _require(selection["selected_snapshot_sha256"] == _sha(payloads[base + ".jsonl"])
                 and selection["exported_records"] == count
                 and selection["source"] == SOURCE_URL and selection["sha1"] == SOURCE_SHA1
                 and all(selection[field] is True for field in
                         ("complete_dump_read", "source_file_verified", "gzip_crc_verified"))
                 and selection["contains_prices"] is False and selection["contains_covers"] is False,
                 "Source selection receipt mismatch")
    full, novel, initial = (indexed[name] for name in ("full", "recovery", "initial_reviewed"))
    _require(all(full.get(key) == row for key, row in novel.items())
             and all(novel.get(key) == row for key, row in initial.items()), "Source cohort subset mismatch")
    deferred_ids = set(novel) - set(initial)
    _require(len(deferred_ids) == 909 and len(set(full) - set(novel)) == 16, "Source cohort partition mismatch")
    holds = documents[DATA + "book_openlibrary_review_holds.json"]["records"]
    _require(len(holds) == len({row["source_id"] for row in holds}) == 57
             and set(full).isdisjoint(row["source_id"] for row in holds), "Historical source hold mismatch")
    initial_selection = documents[DATA + "book_openlibrary_initial_reviewed_20261027.selection.json"]
    _require(initial_selection["deferred_novel_records"] == 909
             and initial_selection["selection_order"] == "reviewed_1500_cohort_order_minus_5_exact_holds_no_refill",
             "Initial review order or deferred cohort changed")
    imports = documents[EVIDENCE + "book-openlibrary-production-import-20261027.json"]
    binding = imports["source_binding"]
    for field, path in (
        ("initial_snapshot_sha256", DATA + "book_openlibrary_initial_reviewed_20261027.jsonl"),
        ("full_novel_snapshot_sha256", DATA + "book_openlibrary_recovery_20261027.jsonl"),
        ("selection_receipt_sha256", DATA + "book_openlibrary_initial_reviewed_20261027.selection.json"),
        ("reviewed_holds_sha256", DATA + "book_openlibrary_review_holds.json"),
        ("original_subject_review_sha256", DATA + "book_openlibrary_original_subject_review_20261027.json"),
    ):
        _require(binding[field] == _sha(payloads[path]), "Historical import source binding mismatch")
    committed = []
    for batch in imports["batches"]:
        rows = batch["receipt"]["records"]
        _require(batch["receipt"]["statuses"] == {"IMPORTED": len(rows)}
                 and batch["readback"]["matching_source_digests"] == len(rows)
                 and all(row["status"] == "IMPORTED" for row in rows), "Historical import receipt mismatch")
        committed.extend(rows)
    _require([row["source_id"] for row in committed] == list(initial)
             and len({row["catalogue_id"] for row in committed}) == 1495
             and [(row["source_id"], row["record_digest"]) for row in committed]
                 == [(row["source_id"], row["record_digest"])
                     for row in initial_selection["retained_normalized_record_digests"]],
             "Historical imported cohort mismatch")
    deferred = documents[EVIDENCE + "book-deferred-review-20261027.json"]
    _require(deferred["status"] == "DEFERRED_COHORT_HELD_PENDING_REVIEW"
             and deferred["partition"]["deferred_records"] == len(deferred_ids)
             and len(deferred["records"]) == 6
             and all(row["source_id"] in deferred_ids and row["conclusive_reclassification"] is False
                     for row in deferred["records"]), "Deferred review status mismatch")
    return {
        "as_of": imports["production_completion"]["finished_at"],
        "basis": "HASH_BOUND_HISTORICAL_RECEIPTS_NOT_A_LIVE_DATABASE_READ",
        "source_selected_records": len(full), "existing_candidates_excluded": 16,
        "novel_records": len(novel), "historically_imported_records": len(initial),
        "deferred_records": len(deferred_ids), "deferred_status": deferred["status"],
        "deferred_form_review_findings": len(deferred["records"]),
        "historical_exact_review_holds": len(holds),
        "physical_printing_verified": False, "source_genre_verified": False,
    }


def _prepare(root):
    payloads = _read_inputs(root)
    try:
        cohorts = _cohorts(payloads)
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceArchiveError("Source evidence schema mismatch") from exc
    files, compressed = [], []
    for item in INPUTS:
        output = io.BytesIO()
        # GzipFile fixes filename, timestamp and OS header across supported Python versions.
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0, compresslevel=9) as stream:
            stream.write(payloads[item.path])
        data = output.getvalue()
        _require(gzip.decompress(data) == payloads[item.path], "Source archive gzip round trip failed")
        compressed.append(data)
        files.append({"path": item.path, "role": item.role, "sha256": item.sha256,
                      "size_bytes": item.size_bytes, "gzip_sha256": _sha(data), "gzip_bytes": len(data)})
    content_root = _sha(_json([{key: row[key] for key in ("path", "role", "sha256", "size_bytes")} for row in files]))
    manifest = {
        "schema": SCHEMA, "checkpoint": CHECKPOINT, "source_commit": SOURCE_COMMIT,
        "content_root_sha256": content_root, "source": "OPEN_LIBRARY",
        "source_url": SOURCE_URL, "source_sha1": SOURCE_SHA1, "metadata_license": LICENSING_URL,
        "scope": "SELECTED_FACTUAL_METADATA_AND_HISTORICAL_REVIEW_IMPORT_EVIDENCE",
        "contains_original_dump": False, "contains_cover_bytes": False,
        "archive_grants_publication_rights": False, "cohorts": cohorts, "files": files,
        "effects": {"database_writes": 0, "imports": 0, "price_changes": 0, "rights_changes": 0,
                    "deferred_records_promoted": 0, "provider_requests": 0},
    }
    return manifest, compressed


def _verified_receipt(receipt, storage, digest, size, suffix):
    expected_key = f"{storage.config.prefix}/exports/{digest}{suffix}"
    _require(isinstance(receipt, dict) and receipt.get("verified") is True
             and receipt.get("sha256") == digest and type(receipt.get("size_bytes")) is int
             and receipt["size_bytes"] == size and receipt.get("key") == expected_key,
             "Source archive storage receipt mismatch")
    # Do not copy any provider response fields, endpoints or credentials into reports.
    return {key: receipt[key] for key in ("key", "sha256", "size_bytes", "verified")}


async def archive_reviewed_openlibrary_sources(*, apply=False, storage=None, source_root=None):
    """Verify one fixed checkpoint; optionally upload private, idempotent copies.

    The returned manifest and object receipts fit an existing maintenance job
    report. No storage configuration is read and no remote call occurs in dry run.
    All source files are read and verified before the first possible upload.
    """
    _require(type(apply) is bool, "Source archive apply must be boolean")
    root = Path(source_root) if source_root is not None else Path(__file__).resolve().parents[2]
    manifest, compressed = await asyncio.to_thread(_prepare, root.resolve())
    report = {"archive_id": CHECKPOINT + ":" + manifest["content_root_sha256"],
              "status": "DRY_RUN", "uploaded": False, "file_count": len(INPUTS),
              "source_bytes": sum(item.size_bytes for item in INPUTS), "manifest": manifest}
    if not apply:
        return report
    storage = storage if storage is not None else configured_object_storage()
    _require(storage is not None, "Private object storage is not enabled")
    with tempfile.TemporaryDirectory(prefix="drop-rate-catalogue-source-") as directory:
        folder = Path(directory)
        for number, (item, entry, data) in enumerate(zip(INPUTS, manifest["files"], compressed)):
            # Logical filenames remain in the manifest; storage accepts a small
            # safe extension alphabet (the historical .import-plan suffix does not).
            path = folder / (f"input-{number}" + Path(item.path).suffix + ".gz")
            path.write_bytes(data)
            receipt = await asyncio.to_thread(storage.put_verified_file, path,
                                             category="exports", content_type="application/gzip")
            entry["object"] = _verified_receipt(receipt, storage, entry["gzip_sha256"],
                                                entry["gzip_bytes"], "".join(path.suffixes))
        manifest_bytes = _json(manifest)
        path = folder / "catalogue-source.manifest.json"
        path.write_bytes(manifest_bytes)
        receipt = await asyncio.to_thread(storage.put_verified_file, path,
                                         category="exports", content_type="application/json")
        report["manifest_object"] = _verified_receipt(receipt, storage, _sha(manifest_bytes),
                                                     len(manifest_bytes), ".manifest.json")
    report.update(status="BYTES_VERIFIED", uploaded=True)
    return report
