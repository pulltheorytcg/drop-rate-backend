"""Resumable, disk-backed selection from a complete official edition dump.

The old prefix pilot remains deliberately bounded.  This worker downloads one
monthly file, checks its published size/SHA1, streams gzip without expanding it
on disk, and exports only after EOF (including gzip's CRC check).  It never calls
the live Open Library search/edition APIs or writes the production database.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import time
from urllib.parse import urlsplit

from .book_openlibrary import (
    EditionReviewRequired, canonical_isbn, classification_subject, dump_source, edition_facts,
)

VERSION = "openlibrary-full-editions-v2"
MAX_DUMP_BYTES = 32 * 1024**3
MIN_DISK_RESERVE = 1024**3
MAX_LINE_BYTES = 2_000_000
PREFILTER = (b"manga", b"comics", b"comic books", b"graphic novel", b"one piece",
             b"naruto", b"dragon ball z", b"hunter x hunter", b"jujutsu kaisen", b"death note")
# The earlier publisher review established that this title omits its 3-in-1
# edition qualifier. A monthly snapshot is not permission to undo that hold.
REVIEWED_ISBN_HOLDS = {"9781421539935": "KNOWN_OMNIBUS_TITLE_INCOMPLETE"}
QUALITY_VERSION = "openlibrary-export-quality-v1"
EXPORT_ISBN_HOLDS = {
    # The stratified source QA sample found a pulp-series title assigned generic
    # graphic-novel subjects. Hold it pending publisher form confirmation.
    "9781886937758": "PULP_OR_GRAPHIC_FORM_REVIEW_REQUIRED",
}


class BulkPaused(ValueError):
    """Stable diagnostic; does not contain source payloads or credentials."""


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def official_host(url):
    p = urlsplit(url)
    return (p.scheme == "https" and not p.username and not p.password
            and p.port in (None, 443) and not p.fragment
            and (p.hostname == "archive.org" or str(p.hostname).endswith(".archive.org")))


def manifest_spec(source, manifest):
    """Bind the exact dated edition filename to its official file manifest."""
    dump_source(source)
    filename = source.rsplit("/", 1)[-1]
    files = [f for f in manifest.get("files", []) if f.get("name") == filename]
    if len(files) != 1:
        raise BulkPaused("DUMP_MANIFEST_FILE_REQUIRED")
    entry = files[0]
    try:
        size = int(entry["size"])
    except (ValueError, TypeError, KeyError):
        raise BulkPaused("DUMP_MANIFEST_SIZE_INVALID") from None
    sha1 = entry.get("sha1", "")
    if not 1 <= size <= MAX_DUMP_BYTES or not re.fullmatch(r"[a-f0-9]{40}", sha1):
        raise BulkPaused("DUMP_MANIFEST_INTEGRITY_REQUIRED")
    return {"source": source, "size": size, "sha1": sha1,
            "manifest_url": "https://archive.org/metadata/" + source.split("/")[-2]}


def _request(client, url, headers):
    """Follow a bounded chain of official HTTPS archive redirects only."""
    for _ in range(6):
        if not official_host(url):
            raise BulkPaused("DUMP_REDIRECT_NOT_ALLOWED")
        request = client.build_request("GET", url, headers=headers)
        response = client.send(request, stream=True, follow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise BulkPaused("DUMP_REDIRECT_NOT_ALLOWED")
            from urllib.parse import urljoin
            url = urljoin(url, location)
            continue
        return response
    raise BulkPaused("DUMP_REDIRECT_LIMIT")


def fetch_manifest(source, client):
    dump_source(source)
    url = "https://archive.org/metadata/" + source.split("/")[-2]
    response = _request(client, url, {"User-Agent": "DropRateCatalogue/1.0 (monthly metadata importer)"})
    try:
        if response.status_code != 200:
            raise BulkPaused("DUMP_MANIFEST_HTTP_FAILURE")
        content = bytearray()
        for chunk in response.iter_bytes(64 * 1024):
            content.extend(chunk)
            if len(content) > 8 * 1024**2:
                raise BulkPaused("DUMP_MANIFEST_TOO_LARGE")
        return manifest_spec(source, json.loads(content))
    finally:
        response.close()


def verify_dump(path, spec):
    path = Path(path)
    if path.stat().st_size != spec["size"]:
        raise BulkPaused("DUMP_SIZE_MISMATCH")
    sha = hashlib.sha1()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024**2), b""):
            sha.update(chunk)
    if sha.hexdigest() != spec["sha1"]:
        raise BulkPaused("DUMP_HASH_MISMATCH")


def download_dump(path, spec, client, *, max_bytes=1024**3, max_seconds=300):
    """One bounded range request; a later invocation resumes the .part file.

    The accepted final file always has the full manifest hash. No retry loop,
    API harvesting, hidden bandwidth expansion or automatic quota increase.
    """
    dump_source(spec["source"])
    if (type(max_bytes) is not int or not 1 <= max_bytes <= 4 * 1024**3
            or type(max_seconds) is not int or not 1 <= max_seconds <= 900):
        raise BulkPaused("BOUNDED_DOWNLOAD_REQUIRED")
    path = Path(path)
    if path.exists():
        verify_dump(path, spec)
        return {"complete": True, "downloaded_bytes": path.stat().st_size, "requested_bytes": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > spec["size"]:
        raise BulkPaused("DUMP_PARTIAL_SIZE_INVALID")
    if offset == spec["size"]:
        verify_dump(partial, spec)
        partial.replace(path)
        return {"complete": True, "downloaded_bytes": offset, "requested_bytes": 0}
    end = min(spec["size"], offset + max_bytes) - 1
    if shutil.disk_usage(path.parent).free < (end + 1 - offset) + MIN_DISK_RESERVE:
        raise BulkPaused("DUMP_LOCAL_DISK_RESERVE")
    headers = {"User-Agent": "DropRateCatalogue/1.0 (monthly metadata importer)",
               "Range": f"bytes={offset}-{end}", "Accept-Encoding": "identity"}
    started = time.monotonic()
    response = _request(client, spec["source"], headers)
    try:
        expected = f"bytes {offset}-{end}/{spec['size']}"
        if response.status_code != 206 or response.headers.get("content-range") != expected:
            raise BulkPaused("DUMP_RANGE_MISMATCH")
        written = 0
        with partial.open("ab") as target:
            for chunk in response.iter_bytes(1024**2):
                if offset + written + len(chunk) > end + 1:
                    raise BulkPaused("DUMP_RANGE_OVERRUN")
                target.write(chunk)
                written += len(chunk)
                if time.monotonic() - started >= max_seconds:
                    break
            target.flush()
            import os
            os.fsync(target.fileno())
    finally:
        response.close()
    size = partial.stat().st_size
    complete = size == spec["size"]
    if complete:
        verify_dump(partial, spec)
        partial.replace(path)
    return {"complete": complete, "downloaded_bytes": size, "requested_bytes": end + 1 - offset}


def open_selection(path):
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        create table if not exists progress (id integer primary key check(id=1), value text not null);
        create table if not exists candidates (isbn text primary key, source_id text not null,
            fingerprint text not null, row_json text not null, system text not null, language text not null);
        create table if not exists sources (source_id text primary key, isbn text not null, fingerprint text not null);
        create table if not exists blocked_isbns (isbn text primary key, reason text not null);
        create table if not exists blocked_sources (source_id text primary key);
    """)
    return connection


def _block(state, isbn, reason):
    state.execute("delete from candidates where isbn=?", (isbn,))
    state.execute("insert or ignore into blocked_isbns values(?,?)", (isbn, reason))


def _candidate(state, row, reasons):
    edition = row["edition"]
    # Ambiguous identifiers/qualifiers must quarantine aliases even when another
    # missing field (for example language) would make edition_facts fail first.
    # This also removes earlier accepted candidates and survives later aliases.
    aliases = set()
    for field in ("isbn_13", "isbn_10"):
        values = edition.get(field, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            for value in values:
                try:
                    aliases.add(canonical_isbn(value))
                except EditionReviewRequired:
                    pass
    held_reason = ("MULTIPLE_EDITION_ISBNS" if len(aliases) > 1 else
        next((REVIEWED_ISBN_HOLDS[isbn] for isbn in sorted(aliases) if isbn in REVIEWED_ISBN_HOLDS), None))
    if any(edition.get(field) for field in ("edition_name", "subtitle")):
        held_reason = held_reason or "EDITION_QUALIFIER_REVIEW_REQUIRED"
    if held_reason:
        for isbn in aliases:
            _block(state, isbn, held_reason)
        key = edition.get("key", "")
        if isinstance(key, str) and re.fullmatch(r"/books/OL[1-9][0-9]*M", key):
            source_id = key.rsplit("/", 1)[-1]
            prior = state.execute("select isbn from sources where source_id=?", (source_id,)).fetchone()
            if prior:
                _block(state, prior["isbn"], held_reason)
            state.execute("insert or ignore into blocked_sources values(?)", (source_id,))
        raise EditionReviewRequired(held_reason)
    facts = edition_facts(row)
    isbn, source_id = facts["book"]["barcode_gtin"], facts["record_id"]
    if isbn in REVIEWED_ISBN_HOLDS:
        raise EditionReviewRequired(REVIEWED_ISBN_HOLDS[isbn])
    # These fields can distinguish an omnibus, revised edition or variant from
    # the title. Until represented losslessly, hold the row rather than drop them.
    safe = {k: edition[k] for k in ("key", "type", "title", "publishers", "languages",
            "physical_format", "publish_date", "isbn_13", "isbn_10") if k in edition}
    safe["subjects"] = [s for s in edition.get("subjects", [])
                        if len(s) <= 200 and classification_subject(s)]
    selected = {**row, "edition": safe}
    if edition_facts(selected) != facts:
        raise EditionReviewRequired("SNAPSHOT_FACTS_CHANGED")
    # Exercise the same complete schema/identity adapter used at import time.
    from .book_catalogue_sources import normalise
    normalise("OPEN_LIBRARY", selected)
    fingerprint = _json({k: facts[k] for k in ("book", "language", "release_date")})
    if state.execute("select 1 from blocked_sources where source_id=?", (source_id,)).fetchone():
        _block(state, isbn, "CONFLICTING_SOURCE_RECORD")
        reasons["CONFLICTING_SOURCE_RECORD"] += 1
        return
    prior_source = state.execute("select * from sources where source_id=?", (source_id,)).fetchone()
    if prior_source:
        if (prior_source["isbn"], prior_source["fingerprint"]) == (isbn, fingerprint):
            reasons["DUPLICATE_SOURCE_RECORD"] += 1
        else:
            for touched in {prior_source["isbn"], isbn}:
                _block(state, touched, "CONFLICTING_SOURCE_RECORD")
            state.execute("insert or ignore into blocked_sources values(?)", (source_id,))
            reasons["CONFLICTING_SOURCE_RECORD"] += 1
        return
    state.execute("insert into sources values(?,?,?)", (source_id, isbn, fingerprint))
    if state.execute("select 1 from blocked_isbns where isbn=?", (isbn,)).fetchone():
        reasons["CONFLICTING_EDITION_ISBN"] += 1
        return
    prior = state.execute("select fingerprint from candidates where isbn=?", (isbn,)).fetchone()
    if prior:
        if prior["fingerprint"] != fingerprint:
            _block(state, isbn, "CONFLICTING_EDITION_ISBN")
            reasons["CONFLICTING_EDITION_ISBN"] += 1
        else:
            reasons["DUPLICATE_EDITION_ISBN"] += 1
        return
    state.execute("insert into candidates values(?,?,?,?,?,?)", (
        isbn, source_id, fingerprint, _json(selected), facts["book"]["system_code"], facts["language"]))


def _save_progress(state, progress, reasons):
    progress["rejection_reasons"] = dict(sorted(reasons.items()))
    state.execute("insert or replace into progress values(1,?)", (_json(progress),))
    state.commit()


def selection_report(state):
    saved = state.execute("select value from progress where id=1").fetchone()
    progress = json.loads(saved[0]) if saved else {}
    return {**progress,
            "accepted_records": state.execute("select count(*) from candidates").fetchone()[0],
            "quarantined_isbns": state.execute("select count(*) from blocked_isbns").fetchone()[0],
            "quarantine_reasons": dict(state.execute("select reason,count(*) from blocked_isbns group by reason")),
            "systems": dict(state.execute("select system,count(*) from candidates group by system")),
            "languages": dict(state.execute("select language,count(*) from candidates group by language")),
            "contains_covers": False, "contains_prices": False,
            "physical_printing_verified": False}


def classification_hold(row):
    edition = row["edition"]
    title = str(edition.get("title", ""))
    subjects = " | ".join(edition.get("subjects", []))
    if (edition.get("publishers") == ["Adventure House"]
            and re.match(r"^(?:G-8 And His Battle Aces|High Adventure)\s+#", title, re.I)):
        return "PULP_OR_GRAPHIC_FORM_REVIEW_REQUIRED"
    if re.search(r"\b(?:history\s+and\s+criticism|study\s+and\s+teaching|bibliograph\w*|"
                 r"handbooks?|manuals?|dictionaries|encyclop\w*|drawing\s+techniques?)\b", subjects, re.I):
        return "ABOUT_COMICS_NONFICTION_REVIEW_REQUIRED"
    if re.search(r"\b(?:art\s+of|how\s+to\s+(?:draw|create|write)|official\s+handbook)\b", title, re.I):
        return "ART_OR_INSTRUCTION_BOOK_REVIEW_REQUIRED"
    if re.search(r"\b(?:not\s+yet\s+titled|title\s+to\s+come|tbd|untitled)\b", title, re.I):
        return "PROVISIONAL_SOURCE_TITLE_REVIEW_REQUIRED"
    isbn = edition_facts(row)["book"]["barcode_gtin"]
    return EXPORT_ISBN_HOLDS.get(isbn)


def apply_export_quality_holds(state):
    """Audit broad classification false positives after the immutable full scan.

    A hold means the source needs further review, not a definitive assertion
    that a book can never be a comic. No printing or genre becomes VERIFIED.
    """
    report = selection_report(state)
    if not report.get("complete_dump_read") or report.get("status") != "COMPLETE":
        raise BulkPaused("COMPLETE_DUMP_SELECTION_REQUIRED")
    if report.get("export_quality", {}).get("version") == QUALITY_VERSION:
        return report["export_quality"]
    state.execute("""create table if not exists export_review_holds(
        isbn text primary key, source_id text not null, reason text not null, row_json text not null)""")
    holds, checked = Counter(), 0
    for row in state.execute("select * from candidates order by isbn").fetchall():
        checked += 1
        reason = classification_hold(json.loads(row["row_json"]))
        if reason:
            state.execute("insert or ignore into export_review_holds values(?,?,?,?)",
                          (row["isbn"], row["source_id"], reason, row["row_json"]))
            _block(state, row["isbn"], reason)
            holds[reason] += 1
    quality = {"version": QUALITY_VERSION, "checked_candidates": checked,
               "held_candidates": sum(holds.values()), "hold_reasons": dict(sorted(holds.items()))}
    saved = json.loads(state.execute("select value from progress where id=1").fetchone()[0])
    saved["export_quality"] = quality
    state.execute("update progress set value=? where id=1", (_json(saved),))
    state.commit()
    return quality


def scan_dump(path, spec, state, *, observed_on=None, max_seconds=900,
              max_records=10_000_000, progress_callback=None):
    """Resume at a committed raw gzip offset; only full EOF permits export.

    Gzip seeking re-decompresses the local prefix. It does not redownload or
    expand that prefix onto disk. SQLite stores only candidate facts/conflicts.
    """
    if (type(max_seconds) is not int or not 1 <= max_seconds <= 3600
            or type(max_records) is not int or not 1 <= max_records <= 100_000_000):
        raise BulkPaused("BOUNDED_SCAN_REQUIRED")
    verify_dump(path, spec)
    observed_on = observed_on or date.today().isoformat()
    if date.fromisoformat(observed_on) > date.today():
        raise BulkPaused("FUTURE_SOURCE_OBSERVATION")
    binding = {"version": VERSION, "source": spec["source"], "size": spec["size"],
               "sha1": spec["sha1"], "observed_on": observed_on}
    saved = state.execute("select value from progress where id=1").fetchone()
    progress = json.loads(saved[0]) if saved else {**binding, "scanned_records": 0,
        "raw_offset": 0, "complete_dump_read": False, "status": "INCOMPLETE",
        "source_file_verified": True, "gzip_crc_verified": False}
    if any(progress.get(k) != v for k, v in binding.items()):
        raise BulkPaused("SELECTION_SNAPSHOT_CHANGED")
    if progress.get("status") == "FAILED":
        raise BulkPaused("SELECTION_FAILED_REBUILD_REQUIRED")
    if progress["complete_dump_read"]:
        return selection_report(state)
    reasons = Counter(progress.get("rejection_reasons", {}))
    _save_progress(state, progress, reasons)
    initial_records = progress["scanned_records"]
    try:
        with gzip.open(path, "rb") as source:
            resume_started = time.monotonic()
            source.seek(progress["raw_offset"])
            progress["resume_replay_seconds"] = round(time.monotonic() - resume_started, 2)
            # The local gzip prefix replay is finite but may exceed a short run
            # budget. Start that budget afterwards so a late checkpoint always
            # makes forward progress instead of repeatedly timing out on seek.
            started = time.monotonic()
            while True:
                if (progress["scanned_records"] - initial_records >= max_records
                        or time.monotonic() - started >= max_seconds):
                    progress["stop_reason"] = "RUN_BUDGET_REACHED"
                    break
                raw = source.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    progress.update(complete_dump_read=True, status="COMPLETE", stop_reason="DUMP_EXHAUSTED",
                                    gzip_crc_verified=True)
                    break
                progress["scanned_records"] += 1
                if len(raw) > MAX_LINE_BYTES:
                    while raw and not raw.endswith(b"\n"):
                        raw = source.readline(MAX_LINE_BYTES + 1)
                    if not raw.endswith(b"\n"):
                        raise BulkPaused("DUMP_LINE_TRUNCATED")
                    reasons["EDITION_RECORD_TOO_LARGE"] += 1
                elif not raw.endswith(b"\n"):
                    raise BulkPaused("DUMP_LINE_TRUNCATED")
                elif not _has_target_token(raw):
                    reasons["NO_TARGET_CLASSIFICATION_TOKEN"] += 1
                else:
                    parts = raw.rstrip(b"\r\n").split(b"\t", 4)
                    if len(parts) != 5 or parts[0] != b"/type/edition":
                        reasons["NON_EDITION_RECORD"] += 1
                    else:
                        try:
                            edition = json.loads(parts[4])
                            if edition.get("key") != parts[1].decode("utf-8"):
                                raise EditionReviewRequired("DUMP_KEY_MISMATCH")
                            _candidate(state, {"edition": edition, "observed_on": observed_on,
                                               "dump_source": spec["source"]}, reasons)
                        except (ValueError, TypeError, KeyError, AttributeError) as exc:
                            reason = str(exc) if isinstance(exc, EditionReviewRequired) else "INVALID_EDITION_RECORD"
                            reasons[reason] += 1
                progress["raw_offset"] = source.tell()
                if progress["scanned_records"] % 50_000 == 0:
                    progress["compressed_bytes_read"] = source.fileobj.tell()
                    progress["run_elapsed_seconds"] = round(time.monotonic() - started, 2)
                    progress["run_records"] = progress["scanned_records"] - initial_records
                    _save_progress(state, progress, reasons)
                    if progress_callback:
                        progress_callback(selection_report(state))
    except (EOFError, gzip.BadGzipFile, OSError, BulkPaused):
        progress.update(status="FAILED", complete_dump_read=False, stop_reason="DUMP_READ_FAILED")
        _save_progress(state, progress, reasons)
        raise BulkPaused("DUMP_READ_FAILED") from None
    _save_progress(state, progress, reasons)
    return selection_report(state)


def _has_target_token(raw):
    folded = raw.lower()
    return any(token in folded for token in PREFILTER)


def export_selection(state, output, *, exclude_isbns=(), max_records=None):
    """An incomplete or failed full-snapshot selection cannot become import data."""
    report = selection_report(state)
    if not report.get("complete_dump_read") or report.get("status") != "COMPLETE":
        raise BulkPaused("COMPLETE_DUMP_SELECTION_REQUIRED")
    if max_records is not None and (type(max_records) is not int or not 1 <= max_records <= 100_000):
        raise BulkPaused("BOUNDED_EXPORT_REQUIRED")
    excluded = set(exclude_isbns)
    apply_export_quality_holds(state)
    report = selection_report(state)
    output, digest, count = Path(output), hashlib.sha256(), 0
    temporary = Path(str(output) + ".partial")
    with temporary.open("wb") as target:
        # Alternate manga and comics after reading the complete snapshot. The
        # bounded production subset therefore does not just take one ISBN prefix
        # or one family; all selected facts still pass exactly the same rules.
        for row in state.execute("""select isbn,row_json from (
                select isbn,row_json,case when system='MANGA' then 'MANGA' else 'COMICS' end as family,
                    row_number() over(partition by case when system='MANGA' then 'MANGA' else 'COMICS' end
                                      order by isbn) as family_rank from candidates)
                order by family_rank,family,isbn"""):
            if row["isbn"] in excluded:
                continue
            if max_records is not None and count >= max_records:
                break
            content = (row["row_json"] + "\n").encode()
            target.write(content)
            digest.update(content)
            count += 1
    temporary.replace(output)
    return {**report, "exported_records": count, "excluded_existing_isbns": len(excluded),
            "selected_snapshot_sha256": digest.hexdigest(), "export_limit": max_records,
            "selection_order": "alternating_comics_manga_then_isbn"}
