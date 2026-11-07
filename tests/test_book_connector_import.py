"""Offline exporter validation and optional real PostgreSQL transaction checks.

Set BOOK_TEST_PGLITE_MODULE to an installed @electric-sql/pglite module entry to
run SQL integration cases. No network, database credentials or production data.
"""
from copy import deepcopy
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess

import pytest

from app.book_bulk_import import ImportPaused, open_stage, stage_file
from app.book_catalogue_sources import normalise
from app.book_connector_import import build_batch, export_stage_batches
from app.book_openlibrary_bulk import QUALITY_VERSION, SUBJECT_PROJECTION, VERSION, reviewed_hold_registry

DUMP = "https://archive.org/download/ol_dump_2026-09-30/ol_dump_editions_2026-09-30.txt.gz"
SNAPSHOT = "a" * 64


def source_row(index=1, **changes):
    base = "9789910" + f"{index:05}"
    isbn = base + str((-sum(int(n)*(1 if i%2 == 0 else 3) for i, n in enumerate(base))) % 10)
    edition = dict(key=f"/books/OL{index}M", type={"key": "/type/edition"},
        title=f"Fixture Manga Vol. {index}", publishers=["Fixture Publisher"],
        languages=[{"key": "/languages/eng"}], isbn_13=[isbn], physical_format="Paperback",
        publish_date="2020", subjects=["Manga"])
    edition.update(changes)
    return dict(edition=edition, observed_on="2026-10-27", dump_source=DUMP)


def entry(index=1, **changes):
    return normalise("OPEN_LIBRARY", source_row(index, **changes))


def run_sql(tmp_path, steps, *, setup=None, inspect="select count(*) as n from tcg.catalogue_products"):
    if not os.environ.get("BOOK_TEST_PGLITE_MODULE"):
        pytest.skip("Optional isolated PGlite SQL runtime not installed")
    request = tmp_path / "sql-case.json"
    request.write_text(json.dumps(dict(steps=steps, setup=setup, inspect=inspect)))
    command = ["node", str(Path(__file__).with_name("book_connector_pgcheck.mjs")), str(request)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
    return json.loads(result.stdout)


def test_export_binds_stage_hash_and_never_overwrites_a_different_batch(tmp_path):
    snapshot = tmp_path / "books.jsonl"
    snapshot.write_text(json.dumps(source_row()) + "\n")
    sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    receipt = dict(version=VERSION, status="COMPLETE", complete_dump_read=True,
        source_file_verified=True, gzip_crc_verified=True, selected_snapshot_sha256=sha, exported_records=1,
        export_quality={"version": QUALITY_VERSION, "reviewed_holds_sha256": reviewed_hold_registry()[1]}, subject_projection=SUBJECT_PROJECTION)
    with open_stage(":memory:") as state:
        stage_file(state, snapshot, "OPEN_LIBRARY")
        with pytest.raises(ImportPaused, match="BOOK_CONNECTOR_STAGE_BINDING_MISMATCH"):
            export_stage_batches(state, tmp_path / "wrong", expected_snapshot_sha256=SNAPSHOT,
                selection_receipt={**receipt, "selected_snapshot_sha256": SNAPSHOT}, database_bytes=358_042_771)
        report = export_stage_batches(state, tmp_path / "sql", expected_snapshot_sha256=sha,
            selection_receipt=receipt, database_bytes=358_042_771)
        assert report["exported_records"] == 1 and len(report["batches"]) == 1
        assert report["estimated_database_bytes"] > 8192
        (tmp_path / "sql" / "batch-001.sql").write_text("a different immutable reviewed batch")
        with pytest.raises(ImportPaused, match="BOOK_CONNECTOR_IMMUTABLE_EXPORT_EXISTS"):
            export_stage_batches(state, tmp_path / "sql", expected_snapshot_sha256=sha,
                selection_receipt=receipt, database_bytes=358_042_771)


@pytest.mark.parametrize("field", ["complete_dump_read", "source_file_verified", "gzip_crc_verified"])
def test_incomplete_source_receipt_cannot_export_even_when_jsonl_staging_is_complete(tmp_path, field):
    snapshot = tmp_path / "books.jsonl"; snapshot.write_text(json.dumps(source_row()) + "\n")
    sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    receipt = dict(version=VERSION, status="COMPLETE", complete_dump_read=True,
        source_file_verified=True, gzip_crc_verified=True, selected_snapshot_sha256=sha, exported_records=1,
        export_quality={"version": QUALITY_VERSION, "reviewed_holds_sha256": reviewed_hold_registry()[1]}, subject_projection=SUBJECT_PROJECTION)
    receipt[field] = False
    with open_stage(":memory:") as state:
        stage_file(state, snapshot, "OPEN_LIBRARY")
        with pytest.raises(ImportPaused, match="BOOK_CONNECTOR_FULL_DUMP_RECEIPT_REQUIRED"):
            export_stage_batches(state, tmp_path / "sql", expected_snapshot_sha256=sha,
                selection_receipt=receipt, database_bytes=358_042_771)


def test_export_reduces_batch_to_current_capacity_without_lifting_guard(tmp_path):
    snapshot = tmp_path / "books.jsonl"
    snapshot.write_text("".join(json.dumps(source_row(i)) + "\n" for i in (1, 2)))
    sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    receipt = dict(version=VERSION, status="COMPLETE", complete_dump_read=True,
        source_file_verified=True, gzip_crc_verified=True, selected_snapshot_sha256=sha, exported_records=2,
        export_quality={"version": QUALITY_VERSION, "reviewed_holds_sha256": reviewed_hold_registry()[1]}, subject_projection=SUBJECT_PROJECTION)
    from app.book_bulk_import import estimated_bytes
    available = estimated_bytes([entry()]) + 1
    with open_stage(":memory:") as state:
        stage_file(state, snapshot, "OPEN_LIBRARY")
        report = export_stage_batches(state, tmp_path / "sql", expected_snapshot_sha256=sha,
            selection_receipt=receipt, database_bytes=400_000_000-available)
    assert report["exported_records"] == 1
    assert report["pause_threshold_bytes"] == 400_000_000
    assert report["projected_database_bytes"] < 400_000_000


def test_tampered_staging_and_unbounded_batches_cannot_export():
    corrupt = entry(); corrupt["book"]["printing_number"] = 1
    with pytest.raises(ValueError):
        build_batch([corrupt], snapshot_sha256=SNAPSHOT)
    with pytest.raises(ImportPaused, match="BOOK_CONNECTOR_BATCH_BOUNDS"):
        build_batch([entry()] * 101, snapshot_sha256=SNAPSHOT)
    with pytest.raises(ImportPaused, match="BOOK_CONNECTOR_DUPLICATE_SOURCE"):
        build_batch([entry(), entry()], snapshot_sha256=SNAPSHOT)


@pytest.mark.parametrize("match_by", ["isbn", "source_id"])
def test_connector_rechecks_exact_review_holds_before_generating_sql(match_by):
    registry, _ = reviewed_hold_registry()
    hold = registry["9780759531048"]
    changes = ({"isbn_13": [hold["isbn"]]} if match_by == "isbn"
               else {"key": "/books/" + hold["source_id"]})
    with pytest.raises(ImportPaused, match="BOOK_CONNECTOR_REVIEWED_IDENTITY_HOLD"):
        build_batch([entry(**changes)], snapshot_sha256=SNAPSHOT)


def test_sql_applies_once_and_replay_is_existing_with_independent_readback(tmp_path):
    sql, readback, _ = build_batch([entry(1), entry(2)], snapshot_sha256=SNAPSHOT)
    result = run_sql(tmp_path, [sql, sql, readback])
    assert result["results"][0]["ok"], result
    first = next(r["receipt"] for r in result["results"][0]["rows"] if "receipt" in r)
    second = next(r["receipt"] for r in result["results"][1]["rows"] if "receipt" in r)
    assert first["statuses"] == {"IMPORTED": 2}
    assert second["statuses"] == {"EXISTING": 2}
    read = result["results"][2]["rows"][0]["readback"]
    assert read["matching_source_digests"] == read["new_structured"] == 2
    assert read["missing"] == read["conflicting_source_digests"] == read["new_with_invented_printing"] == 0
    assert result["inspected"] == [{"n": 2}]


def test_sql_source_change_is_held_and_original_identity_is_not_updated(tmp_path):
    original, changed = entry(), entry(title="Changed Series Vol. 1")
    first, _, _ = build_batch([original], snapshot_sha256=SNAPSHOT)
    second, _, _ = build_batch([changed], snapshot_sha256=SNAPSHOT)
    result = run_sql(tmp_path, [first, second], inspect="select series_title from tcg.comic_printing_details")
    receipt = next(r["receipt"] for r in result["results"][1]["rows"] if "receipt" in r)
    assert receipt["statuses"] == {"REVIEW": 1}
    assert receipt["records"][0]["reason"] == "SOURCE_CHANGED_REVIEW_REQUIRED"
    assert result["inspected"] == [{"series_title": "Fixture Manga"}]


@pytest.mark.parametrize("language", ["eng", "jpn"])
def test_sql_existing_isbn_alias_is_held_across_languages(tmp_path, language):
    original = entry()
    changed = entry(2, isbn_13=[original["book"]["barcode_gtin"]], languages=[{"key": f"/languages/{language}"}])
    first, _, _ = build_batch([original], snapshot_sha256=SNAPSHOT)
    second, _, _ = build_batch([changed], snapshot_sha256=SNAPSHOT)
    # Store a legacy ISBN-10 representation, exercising real alias matching.
    from app.book_catalogue_sources import barcode_aliases
    alias = next(v for v in barcode_aliases(original["book"]["barcode_gtin"]) if len(v) == 10)
    result = run_sql(tmp_path, [first,
        "update tcg.comic_printing_details set barcode_gtin='" + alias + "';", second])
    receipt = next(r["receipt"] for r in result["results"][2]["rows"] if "receipt" in r)
    assert receipt["statuses"] == {"REVIEW": 1}
    assert receipt["records"][0]["reason"] == "BARCODE_IDENTITY_CONFLICT"
    assert result["inspected"] == [{"n": 1}]


def test_sql_existing_identity_with_changed_facts_is_held(tmp_path):
    first, _, _ = build_batch([entry()], snapshot_sha256=SNAPSHOT)
    alias = entry(key="/books/OL99M")
    second, _, _ = build_batch([alias], snapshot_sha256=SNAPSHOT)
    result = run_sql(tmp_path, [first,
        "update tcg.comic_printing_details set attributes=jsonb_set(attributes,'{publisher}','\"Different Publisher\"');",
        second])
    receipt = next(r["receipt"] for r in result["results"][2]["rows"] if "receipt" in r)
    assert receipt["records"][0]["reason"] == "EXISTING_IDENTITY_CONFLICT"
    assert result["inspected"] == [{"n": 1}]


@pytest.mark.parametrize("title", [
    "O'Brien $$; DROP TABLE innocent; __PAYLOAD_SHA__",
    "O'Brien $book_apply$; DROP TABLE innocent; $book_guard$",
])
def test_sql_literal_quotes_and_dollar_signs_remain_source_data(tmp_path, title):
    row = entry(title=title + " Vol. 1")
    sql, _, _ = build_batch([row], snapshot_sha256=SNAPSHOT)
    result = run_sql(tmp_path, [sql], inspect="select series_title from tcg.comic_printing_details")
    assert result["results"][0]["ok"], result
    assert result["inspected"] == [{"series_title": title}]


def test_sql_modified_payload_fails_hash_before_catalogue_writes(tmp_path):
    sql, _, _ = build_batch([entry()], snapshot_sha256=SNAPSHOT)
    encoded = re.search(r"decode\('([A-Za-z0-9+/=]+)','base64'\)", sql)[1]
    modified = base64.b64encode(base64.b64decode(encoded).replace(b"Fixture Manga", b"Modified Manga")).decode()
    result = run_sql(tmp_path, [sql.replace(encoded, modified)])
    assert result["results"][0]["error"] == "BOOK_CONNECTOR_PAYLOAD_HASH_MISMATCH"
    assert result["inspected"] == [{"n": 0}]


def test_sql_entire_batch_rolls_back_if_a_later_row_cannot_insert(tmp_path):
    first, second = entry(1), entry(2)
    sql, _, _ = build_batch([first, second], snapshot_sha256=SNAPSHOT)
    setup = "insert into tcg.catalogue_products(id,identity_key,product_type) values('" + second["id"] + "','a-different-identity','COMIC');"
    result = run_sql(tmp_path, [sql], setup=setup)
    assert not result["results"][0]["ok"] and "duplicate key" in result["results"][0]["error"]
    assert result["inspected"] == [{"n": 1}]


def test_sql_capacity_guard_retains_400mb_limit_and_reserve(tmp_path):
    sql, _, _ = build_batch([entry()], snapshot_sha256=SNAPSHOT)
    # Only this isolated fixture shadows pg_database_size, avoiding a 400 MB allocation.
    setup = """create schema capacity_test;
    create function capacity_test.pg_database_size(name) returns bigint language sql as
    $$select 399999999::bigint$$;
    set search_path=capacity_test,pg_catalog,public;"""
    result = run_sql(tmp_path, [sql], setup=setup)
    assert result["results"][0]["error"] == "BATCH_EXCEEDS_CAPACITY_RESERVE"
    assert result["inspected"] == [{"n": 0}]


def test_sql_read_only_database_stays_read_only_and_no_import_occurs(tmp_path):
    sql, _, _ = build_batch([entry()], snapshot_sha256=SNAPSHOT)
    result = run_sql(tmp_path, [sql], setup="set default_transaction_read_only='on';")
    assert result["results"][0]["error"] == "DATABASE_READ_ONLY"
    assert result["inspected"] == [{"n": 0}]
