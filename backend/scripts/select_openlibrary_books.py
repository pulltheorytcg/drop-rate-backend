"""Select bounded factual comic/manga editions from an official monthly dump.

This never writes PostgreSQL, fetches covers, or calls the live bulk API.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.book_openlibrary import EditionReviewRequired, dump_source, edition_facts, classification_subject

MAX_COMPRESSED = 64 * 1024 * 1024
MAX_RAW = 256 * 1024 * 1024
MAX_LINE = 2_000_000
MAX_SECONDS = 240
MAX_ROWS = 200


class SelectionLimit(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def redirect_allowed(url):
    p = urlsplit(url)
    return (p.scheme == "https" and p.username is None and p.password is None
            and p.port in (None,443) and not p.fragment
            and (p.hostname == "archive.org" or str(p.hostname).endswith(".archive.org")))


def open_dump(url, opener=None):
    dump_source(url)
    opener = opener or build_opener(NoRedirect)
    for _ in range(5):
        try:
            response = opener.open(Request(url,headers={
                "User-Agent":"DropRate/1.0 (bounded official metadata dump reader)",
                "Accept":"application/gzip"}),timeout=10)
            if response.status != 200:
                response.close()
                raise ValueError("DUMP_HTTP_FAILURE")
            return response
        except HTTPError as exc:
            location = exc.headers.get("Location")
            exc.close()
            if exc.code not in {301,302,303,307,308} or not location or not redirect_allowed(location):
                raise ValueError("DUMP_HTTP_FAILURE") from None
            url = location
    raise ValueError("DUMP_REDIRECT_LIMIT")


class BoundedReader(io.RawIOBase):
    def __init__(self, stream, max_bytes, deadline):
        self.stream,self.max_bytes,self.deadline = stream,max_bytes,deadline
        self.count = 0
        self.digest = hashlib.sha256()
    def readable(self):
        return True
    def readinto(self, target):
        if time.monotonic() >= self.deadline:
            raise SelectionLimit("TIME_LIMIT")
        remaining = self.max_bytes-self.count
        if remaining <= 0:
            raise SelectionLimit("COMPRESSED_BYTE_LIMIT")
        payload = self.stream.read(min(len(target),remaining,64*1024))
        if not payload:
            return 0
        self.count += len(payload)
        self.digest.update(payload)
        target[:len(payload)] = payload
        return len(payload)


def select_dump(stream, source, *, observed_on=None, max_bytes=MAX_COMPRESSED,
                max_rows=MAX_ROWS, max_seconds=MAX_SECONDS, max_raw_bytes=MAX_RAW):
    dump_source(source)
    if (type(max_bytes) is not int or not 1 <= max_bytes <= MAX_COMPRESSED
            or type(max_rows) is not int or not 1 <= max_rows <= MAX_ROWS
            or type(max_seconds) is not int or not 1 <= max_seconds <= MAX_SECONDS
            or type(max_raw_bytes) is not int or not 1 <= max_raw_bytes <= MAX_RAW):
        raise ValueError("BOUNDED_SELECTION_REQUIRED")
    observed_on = observed_on or date.today().isoformat()
    reader = BoundedReader(stream,max_bytes,time.monotonic()+max_seconds)
    selected,blocked,seen_ids,blocked_ids = {},set(),{},set()
    reasons = Counter()
    scanned = raw_bytes = 0
    stop = "DUMP_EXHAUSTED"
    try:
        with gzip.GzipFile(fileobj=io.BufferedReader(reader),mode="rb") as archive:
            while True:
                if time.monotonic() >= reader.deadline:
                    raise SelectionLimit("TIME_LIMIT")
                remaining_raw = max_raw_bytes - raw_bytes
                if remaining_raw <= 0:
                    raise SelectionLimit("RAW_BYTE_LIMIT")
                raw = archive.readline(min(MAX_LINE+1,remaining_raw))
                if not raw:
                    break
                raw_bytes += len(raw)
                if not raw.endswith(b"\n") and raw_bytes == max_raw_bytes:
                    raise SelectionLimit("RAW_BYTE_LIMIT")
                if len(raw)>MAX_LINE or not raw.endswith(b"\n"):
                    raise ValueError("DUMP_LINE_INVALID")
                scanned += 1
                parts = raw.decode("utf-8").rstrip("\r\n").split("\t",4)
                if len(parts)!=5 or parts[0]!="/type/edition":
                    reasons["NON_EDITION_RECORD"] += 1
                    continue
                try:
                    edition = json.loads(parts[4])
                    if edition.get("key") != parts[1]:
                        raise EditionReviewRequired("DUMP_KEY_MISMATCH")
                    candidate = dict(edition=edition,observed_on=observed_on,dump_source=source)
                    facts = edition_facts(candidate)
                    isbn = facts["book"]["barcode_gtin"]
                    source_id = facts["record_id"]
                    fingerprint = {k:facts[k] for k in ("book","language","release_date")}
                    if source_id in blocked_ids:
                        reasons["CONFLICTING_SOURCE_RECORD"] += 1
                        continue
                    prior_source = seen_ids.get(source_id)
                    if prior_source:
                        if prior_source == (isbn,fingerprint):
                            reasons["DUPLICATE_SOURCE_RECORD"] += 1
                        else:
                            # An OL ID cannot silently change edition identity.
                            # Quarantine every selected ISBN touched by that ID.
                            for touched in {prior_source[0],isbn}:
                                if touched in selected:
                                    del selected[touched]
                                    reasons["CONFLICTING_SOURCE_RECORD"] += 1
                                blocked.add(touched)
                            blocked_ids.add(source_id)
                            reasons["CONFLICTING_SOURCE_RECORD"] += 1
                        continue
                    seen_ids[source_id] = (isbn,fingerprint)
                    if isbn in blocked:
                        reasons["CONFLICTING_EDITION_ISBN"] += 1
                        continue
                    prior = selected.get(isbn)
                    if prior:
                        if prior[1] != fingerprint:
                            del selected[isbn]
                            blocked.add(isbn)
                            reasons["CONFLICTING_EDITION_ISBN"] += 2
                        else:
                            reasons["DUPLICATE_EDITION_ISBN"] += 1
                        continue
                    # Keep only factual fields needed for identity. No descriptions,
                    # author biographies, cover IDs or other payloads stored.
                    # Retain only brief classification subjects.
                    safe = {k:edition[k] for k in ("key","type","title","publishers","languages",
                            "physical_format","publish_date","isbn_13","isbn_10") if k in edition}
                    safe["subjects"] = [s for s in edition.get("subjects",[])
                        if len(s)<=200 and classification_subject(s)]
                    snapshot_row = dict(edition=safe,observed_on=observed_on,dump_source=source)
                    if edition_facts(snapshot_row) != facts:
                        raise EditionReviewRequired("SNAPSHOT_FACTS_CHANGED")
                    selected[isbn] = (snapshot_row,fingerprint)
                    if len(selected)>=max_rows:
                        stop = "ACCEPTED_ROW_LIMIT"
                        break
                except (EditionReviewRequired,ValueError,TypeError,KeyError,AttributeError) as exc:
                    reasons[str(exc) if isinstance(exc,EditionReviewRequired) else "INVALID_EDITION_RECORD"] += 1
    except SelectionLimit as exc:
        stop = str(exc)
    rows = [v[0] for _,v in sorted(selected.items())]
    snapshot = "".join(json.dumps(r,sort_keys=True,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows).encode()
    return snapshot,dict(source=source,observed_on=observed_on,scanned_records=scanned,
        accepted_records=len(rows),rejected_records=sum(reasons.values()),
        rejection_reasons=dict(sorted(reasons.items())),stop_reason=stop,
        compressed_bytes_read=reader.count,raw_bytes_read=raw_bytes,
        compressed_prefix_sha256=reader.digest.hexdigest(),
        selected_snapshot_sha256=hashlib.sha256(snapshot).hexdigest(),
        complete_dump_read=stop=="DUMP_EXHAUSTED",contains_covers=False,contains_prices=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--report",required=True)
    parser.add_argument("--max-rows",type=int,default=MAX_ROWS)
    args=parser.parse_args()
    with open_dump(args.source) as response:
        snapshot,report=select_dump(response,args.source,max_rows=args.max_rows)
    Path(args.output).write_bytes(snapshot)
    Path(args.report).write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()

