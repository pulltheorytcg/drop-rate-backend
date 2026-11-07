"""Full-dump completion, restart and ambiguity guarantees; no network."""
from copy import deepcopy
import gzip
import hashlib
import json

import httpx
import pytest

from app.book_openlibrary_bulk import (BulkPaused, download_dump, export_selection,
    manifest_spec, open_selection, scan_dump, selection_report)

DUMP = "https://archive.org/download/ol_dump_2026-09-30/ol_dump_editions_2026-09-30.txt.gz"


def edition(index=1):
    base = "9789910" + f"{index:05}"
    isbn = base + str((-sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(base))) % 10)
    return {"key": f"/books/OL{index}M", "type": {"key": "/type/edition"},
        "title": f"Fixture Manga Vol. {index}", "publishers": ["Fixture Publisher"],
        "languages": [{"key": "/languages/eng"}], "isbn_13": [isbn],
        "physical_format": "Paperback", "publish_date": "January 2, 2020",
        "subjects": ["Comics & Graphic Novels / Manga"], "covers": [123],
        "description": "Descriptions must never enter the selected metadata."}


def make_dump(tmp_path, *editions, content=None):
    raw = b"".join(("/type/edition\t" + row["key"] + "\t1\t2026-09-01T00:00:00Z\t"
                    + json.dumps(row) + "\n").encode() for row in editions)
    data = gzip.compress(raw) if content is None else content
    path = tmp_path / "editions.gz"
    path.write_bytes(data)
    spec = manifest_spec(DUMP, {"files": [{"name": DUMP.rsplit("/", 1)[-1],
        "size": str(len(data)), "sha1": hashlib.sha1(data).hexdigest()}]})
    return path, spec


def test_full_scan_exports_only_after_eof_and_strips_cover_and_descriptions(tmp_path):
    path, spec = make_dump(tmp_path, edition(1), edition(2))
    with open_selection(tmp_path / "state.sqlite") as state:
        report = scan_dump(path, spec, state, observed_on="2026-10-27", max_records=1)
        assert report["status"] == "INCOMPLETE" and report["accepted_records"] == 1
        with pytest.raises(BulkPaused, match="COMPLETE_DUMP_SELECTION_REQUIRED"):
            export_selection(state, tmp_path / "out.jsonl")
    # Reopening disk state exercises restart rather than an in-memory counter.
    with open_selection(tmp_path / "state.sqlite") as state:
        report = scan_dump(path, spec, state, observed_on="2026-10-27")
        assert report["complete_dump_read"] and report["scanned_records"] == 2
        assert report["compressed_bytes_read"] == spec["size"]
        exported = export_selection(state, tmp_path / "out.jsonl")
    rows = [json.loads(line) for line in (tmp_path / "out.jsonl").read_text().splitlines()]
    assert len(rows) == exported["exported_records"] == 2
    assert exported["selected_snapshot_sha256"] == hashlib.sha256((tmp_path / "out.jsonl").read_bytes()).hexdigest()
    assert all("covers" not in row["edition"] and "description" not in row["edition"] for row in rows)
    assert not exported["contains_covers"] and not exported["contains_prices"]
    assert not exported["physical_printing_verified"]


def test_late_conflicting_isbn_quarantines_an_earlier_checkpoint(tmp_path):
    one, two = edition(1), edition(2)
    two["isbn_13"] = one["isbn_13"]
    path, spec = make_dump(tmp_path, one, two)
    with open_selection(tmp_path / "state.sqlite") as state:
        scan_dump(path, spec, state, max_records=1)
        report = scan_dump(path, spec, state)
        assert report["complete_dump_read"] and report["accepted_records"] == 0
        assert report["quarantined_isbns"] == 1
        assert export_selection(state, tmp_path / "out.jsonl")["exported_records"] == 0


def test_late_source_id_conflict_blocks_both_isbns_and_later_reuses(tmp_path):
    one, two = edition(1), edition(2)
    two["key"] = one["key"]
    three = deepcopy(two); three["key"] = "/books/OL3M"
    path, spec = make_dump(tmp_path, one, two, three)
    with open_selection(":memory:") as state:
        report = scan_dump(path, spec, state)
        assert report["accepted_records"] == 0 and report["quarantined_isbns"] == 2


def test_same_edition_alias_deduplicates_but_language_conflict_is_held(tmp_path):
    one, two = edition(1), deepcopy(edition(1)); two["key"] = "/books/OL2M"
    path, spec = make_dump(tmp_path, one, two)
    with open_selection(":memory:") as state:
        report = scan_dump(path, spec, state)
        assert report["accepted_records"] == 1
        assert report["rejection_reasons"]["DUPLICATE_EDITION_ISBN"] == 1
    two["languages"] = [{"key": "/languages/jpn"}]
    path, spec = make_dump(tmp_path, one, two)
    with open_selection(":memory:") as state:
        assert scan_dump(path, spec, state)["accepted_records"] == 0


def test_source_hash_is_verified_before_any_selection(tmp_path):
    path, spec = make_dump(tmp_path, edition())
    spec["sha1"] = "0" * 40
    with open_selection(":memory:") as state:
        with pytest.raises(BulkPaused, match="DUMP_HASH_MISMATCH"):
            scan_dump(path, spec, state)
        assert selection_report(state)["accepted_records"] == 0


def test_gzip_crc_and_truncated_input_never_become_complete(tmp_path):
    path, _ = make_dump(tmp_path, edition())
    data = path.read_bytes()[:-8]
    path, spec = make_dump(tmp_path, content=data)
    with open_selection(":memory:") as state:
        with pytest.raises(BulkPaused, match="DUMP_READ_FAILED"):
            scan_dump(path, spec, state)
        assert selection_report(state)["status"] == "FAILED"
        with pytest.raises(BulkPaused, match="COMPLETE_DUMP_SELECTION_REQUIRED"):
            export_selection(state, tmp_path / "out.jsonl")


def test_snapshot_binding_and_observation_cannot_change_during_resume(tmp_path):
    path, spec = make_dump(tmp_path, edition(1), edition(2))
    with open_selection(":memory:") as state:
        scan_dump(path, spec, state, observed_on="2026-10-26", max_records=1)
        with pytest.raises(BulkPaused, match="SELECTION_SNAPSHOT_CHANGED"):
            scan_dump(path, spec, state, observed_on="2026-10-27")


@pytest.mark.parametrize("field", ["subtitle", "edition_name"])
def test_edition_qualifiers_are_held_instead_of_silently_dropped(tmp_path, field):
    row = edition(); row[field] = "3-in-1 Omnibus Edition"
    path, spec = make_dump(tmp_path, row)
    with open_selection(":memory:") as state:
        report = scan_dump(path, spec, state)
    assert report["accepted_records"] == 0
    assert report["rejection_reasons"]["EDITION_QUALIFIER_REVIEW_REQUIRED"] == 1


def test_known_publisher_review_hold_survives_monthly_refresh(tmp_path):
    row = edition(); row["isbn_13"] = ["9781421539935"]
    path, spec = make_dump(tmp_path, row)
    with open_selection(":memory:") as state:
        report = scan_dump(path, spec, state)
    assert report["rejection_reasons"]["KNOWN_OMNIBUS_TITLE_INCOMPLETE"] == 1


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("field", ["subtitle", "edition_name"])
def test_held_edition_qualifier_quarantines_shared_isbn_in_both_orders(tmp_path, reverse, field):
    one = edition(); held = deepcopy(one)
    held["key"] = "/books/OL22M"; held[field] = "Omnibus 3-in-1"
    rows = [held, one] if reverse else [one, held]
    path, spec = make_dump(tmp_path, *rows)
    with open_selection(":memory:") as state:
        scan_dump(path, spec, state, max_records=1)
        report = scan_dump(path, spec, state)
    assert report["accepted_records"] == 0 and report["quarantined_isbns"] == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_multiple_isbns_quarantine_every_alias_even_when_language_missing(tmp_path, reverse):
    one, two = edition(1), edition(2)
    held = deepcopy(one); held["key"] = "/books/OL33M"
    held["isbn_13"] = one["isbn_13"] + two["isbn_13"]
    held.pop("languages")
    rows = [held, one, two] if reverse else [one, two, held]
    path, spec = make_dump(tmp_path, *rows)
    with open_selection(":memory:") as state:
        report = scan_dump(path, spec, state)
    assert report["accepted_records"] == 0 and report["quarantined_isbns"] == 2
    assert report["rejection_reasons"]["MULTIPLE_EDITION_ISBNS"] == 1


def test_export_can_skip_existing_isbns_and_bound_production_subset(tmp_path):
    rows = [edition(i) for i in (1, 2, 3)]
    path, spec = make_dump(tmp_path, *rows)
    with open_selection(":memory:") as state:
        scan_dump(path, spec, state)
        report = export_selection(state, tmp_path / "out.jsonl",
                                  exclude_isbns=rows[0]["isbn_13"], max_records=1)
    exported = json.loads((tmp_path / "out.jsonl").read_text())
    assert exported["edition"]["key"] == rows[1]["key"]
    assert report["accepted_records"] == 3 and report["exported_records"] == 1


@pytest.mark.parametrize("title,subjects,reason", [
    ("Comics Studies Vol. 1", ["Comics, history and criticism"], "ABOUT_COMICS_NONFICTION_REVIEW_REQUIRED"),
    ("Manga Teaching Vol. 1", ["Manga, Study and teaching"], "ABOUT_COMICS_NONFICTION_REVIEW_REQUIRED"),
    ("The Art Of Vampire Hunter D Volume 1", ["Graphic Novels"], "ART_OR_INSTRUCTION_BOOK_REVIEW_REQUIRED"),
    ("NOT YET TITLED ANTHOLOGY Volume 1", ["Manga"], "PROVISIONAL_SOURCE_TITLE_REVIEW_REQUIRED"),
])
def test_export_audits_about_comics_and_provisional_title_holds(tmp_path, title, subjects, reason):
    row = edition(); row.update(title=title, subjects=subjects)
    path, spec = make_dump(tmp_path, row, edition(2))
    with open_selection(":memory:") as state:
        report = scan_dump(path, spec, state)
        assert report["accepted_records"] == 2
        report = export_selection(state, tmp_path / "out.jsonl")
        assert report["exported_records"] == 1
        assert report["export_quality"]["hold_reasons"] == {reason: 1}
        hold = state.execute("select * from export_review_holds").fetchone()
        assert hold["reason"] == reason and json.loads(hold["row_json"])["edition"]["title"] == title
        # Re-export preserves the original review receipt instead of hiding it.
        again = export_selection(state, tmp_path / "again.jsonl")
        assert again["export_quality"] == report["export_quality"]


@pytest.mark.parametrize("subject", ["History and criticism", "Study and teaching", "History & Criticism", "Study & Teaching"])
def test_standalone_negative_subjects_survive_projection_and_hold_export(tmp_path, subject):
    row = edition(); row["subjects"] = ["Manga", subject]
    path, spec = make_dump(tmp_path, row)
    with open_selection(":memory:") as state:
        scan_dump(path, spec, state)
        selected = json.loads(state.execute("select row_json from candidates").fetchone()[0])
        assert selected["edition"]["subjects"] == ["Manga", subject]
        report = export_selection(state, tmp_path / "out.jsonl")
    assert report["exported_records"] == 0
    assert report["export_quality"]["hold_reasons"] == {"ABOUT_COMICS_NONFICTION_REVIEW_REQUIRED": 1}


def test_older_complete_checkpoint_cannot_claim_complete_subject_projection(tmp_path):
    path, spec = make_dump(tmp_path, edition())
    with open_selection(":memory:") as state:
        scan_dump(path, spec, state)
        saved = json.loads(state.execute("select value from progress").fetchone()[0])
        saved.pop("subject_projection")
        state.execute("update progress set value=?", (json.dumps(saved),)); state.commit()
        with pytest.raises(BulkPaused, match="COMPLETE_SUBJECT_PROJECTION_REQUIRED"):
            export_selection(state, tmp_path / "out.jsonl")


@pytest.mark.parametrize("title", ["G-8 And His Battle Aces #21", "High Adventure #90"])
def test_reviewed_pulp_series_require_form_review_despite_generic_graphic_subjects(tmp_path, title):
    row = edition(); row.update(title=title, publishers=["Adventure House"], subjects=["Graphic Novels"])
    path, spec = make_dump(tmp_path, row)
    with open_selection(":memory:") as state:
        assert scan_dump(path, spec, state)["accepted_records"] == 1
        report = export_selection(state, tmp_path / "out.jsonl")
    assert report["exported_records"] == 0
    assert report["export_quality"]["hold_reasons"] == {"PULP_OR_GRAPHIC_FORM_REVIEW_REQUIRED": 1}


@pytest.mark.parametrize("publisher", ["Adult", "Children", "Unknown"])
def test_publisher_placeholders_are_held_without_inventing_a_publisher(tmp_path, publisher):
    row = edition(); row["publishers"] = [publisher]
    path, spec = make_dump(tmp_path, row)
    with open_selection(":memory:") as state:
        scan_dump(path, spec, state)
        report = export_selection(state, tmp_path / "out.jsonl")
        held = json.loads(state.execute("select row_json from export_review_holds").fetchone()[0])
    assert report["exported_records"] == 0
    assert held["edition"]["publishers"] == [publisher]
    assert report["export_quality"]["hold_reasons"] == {"PUBLISHER_PLACEHOLDER_REVIEW_REQUIRED": 1}


def test_exact_reviewed_registry_holds_another_source_alias_of_same_isbn(tmp_path):
    from app.book_openlibrary_bulk import reviewed_hold_registry
    registry, sha = reviewed_hold_registry()
    row = edition(); row["isbn_13"] = ["9780759531048"]
    path, spec = make_dump(tmp_path, row)
    with open_selection(":memory:") as state:
        scan_dump(path, spec, state)
        report = export_selection(state, tmp_path / "out.jsonl")
    assert registry["9780759531048"]["source_id"] != row["key"].rsplit("/", 1)[-1]
    assert report["exported_records"] == 0
    assert report["export_quality"]["reviewed_holds_sha256"] == sha
    assert report["export_quality"]["hold_reasons"] == {"PROSE_EDITION_FORM_REVIEW_REQUIRED": 1}


@pytest.mark.parametrize("prior_cached_review", [False, True])
def test_reviewed_source_stays_held_after_its_isbn_changes(tmp_path, prior_cached_review):
    from app.book_openlibrary_bulk import QUALITY_VERSION, REVIEWED_HOLD_POLICY, reviewed_hold_registry
    registry, sha = reviewed_hold_registry()
    hold = registry["9780759531048"]
    row = edition(); row["key"] = "/books/" + hold["source_id"]
    assert row["isbn_13"][0] not in registry
    path, spec = make_dump(tmp_path, row)
    with open_selection(":memory:") as state:
        scan_dump(path, spec, state)
        if prior_cached_review:
            saved = json.loads(state.execute("select value from progress").fetchone()[0])
            saved["export_quality"] = {"version": QUALITY_VERSION,
                "reviewed_holds_sha256": sha, "held_candidates": 0}
            state.execute("update progress set value=?", (json.dumps(saved),)); state.commit()
        report = export_selection(state, tmp_path / "out.jsonl")
    assert report["exported_records"] == 0
    assert report["export_quality"]["reviewed_identity_policy"] == REVIEWED_HOLD_POLICY
    assert report["export_quality"]["hold_reasons"] == {hold["reason"]: 1}


def test_download_resumes_exact_ranges_then_verifies_full_manifest_hash(tmp_path):
    data = b"a verified official compressed payload fixture"
    spec = {"source": DUMP, "size": len(data), "sha1": hashlib.sha1(data).hexdigest()}
    seen = []
    def transport(request):
        bounds = request.headers["range"][6:]
        start, end = map(int, bounds.split("-")); seen.append((start, end))
        return httpx.Response(206, headers={"content-range": f"bytes {start}-{end}/{len(data)}"},
                              content=data[start:end+1])
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        report = download_dump(tmp_path / "source.gz", spec, client, max_bytes=10)
        assert not report["complete"] and not (tmp_path / "source.gz").exists()
        report = download_dump(tmp_path / "source.gz", spec, client, max_bytes=len(data))
    assert report["complete"] and (tmp_path / "source.gz").read_bytes() == data
    assert seen == [(0, 9), (10, len(data)-1)]


def test_download_rejects_ignored_range_and_untrusted_redirect_before_append(tmp_path):
    data = b"partial"
    spec = {"source": DUMP, "size": 12, "sha1": "a" * 40}
    partial = tmp_path / "source.gz.part"; partial.write_bytes(data)
    for response, expected in [
        (httpx.Response(200, content=b"whole body"), "DUMP_RANGE_MISMATCH"),
        (httpx.Response(302, headers={"location": "https://untrusted.example/dump"}), "DUMP_REDIRECT_NOT_ALLOWED"),
    ]:
        with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client:
            with pytest.raises(BulkPaused, match=expected):
                download_dump(tmp_path / "source.gz", spec, client)
        assert partial.read_bytes() == data


def test_download_final_hash_failure_retains_partial_and_no_verified_file(tmp_path):
    spec = {"source": DUMP, "size": 3, "sha1": "a" * 40}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            206, headers={"content-range": "bytes 0-2/3"}, content=b"bad"))) as client:
        with pytest.raises(BulkPaused, match="DUMP_HASH_MISMATCH"):
            download_dump(tmp_path / "source.gz", spec, client)
    assert not (tmp_path / "source.gz").exists()
    assert (tmp_path / "source.gz.part").read_bytes() == b"bad"


def test_official_manifest_requires_one_exact_file_and_integrity():
    with pytest.raises(BulkPaused, match="DUMP_MANIFEST_FILE_REQUIRED"):
        manifest_spec(DUMP, {"files": [{"name": "another-file.gz"}]})
    with pytest.raises(BulkPaused, match="DUMP_MANIFEST_INTEGRITY_REQUIRED"):
        manifest_spec(DUMP, {"files": [{"name": DUMP.rsplit("/", 1)[-1], "size": "4", "sha1": "missing"}]})
