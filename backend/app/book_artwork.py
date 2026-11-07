"""Reviewed publisher covers for edition browsing, separate from listing media."""
from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .book_market import printing_digest


def publisher_cover_url(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
    except ValueError:
        return False
    if url.scheme != "https" or url.fragment:
        return False
    patterns = {
        "dw9to29mmj727.cloudfront.net": r"/products/[0-9]{9}[0-9X]\.jpg",
        "static.dc.com": r"/[0-9]{4}-[0-9]{2}/[A-Za-z0-9_]+\.jpg",
        "cdn.marvel.com": r"/u/prod/marvel/i/mg/[a-f0-9]/[a-f0-9]{2}/[a-f0-9]+/(?:clean|detail|background|portrait_uncanny|portrait_incredible|portrait_fantastic|portrait_xlarge)\.jpg",
        "imgix-media.wbdndc.net": r"/ingest/book/preview/[a-f0-9-]{36}/[a-f0-9-]{36}/0\.jpg",
        "images.penguinrandomhouse.com": r"/cover/(?:[0-9]{13}|[0-9]{17})",
    }
    # Marvel's own older issue pages also publish this original CDN hostname.
    patterns["i.annihil.us"] = patterns["cdn.marvel.com"]
    pattern = patterns.get(url.netloc)
    if url.netloc == "imgix-media.wbdndc.net":
        # Only public cover previews, never interior pages or arbitrary transforms.
        allowed = {"auto": {"format,compress"}, "fill": {"blur"}, "fit": {"fill"},
                   "h": {"576"}, "w": {"375"}, "sharp": {"50"}}
        pairs = parse_qsl(url.query, keep_blank_values=True)
        return bool(pattern and re.fullmatch(pattern, url.path)
                    and len(dict(pairs)) == len(pairs)
                    and all(key in allowed and val in allowed[key] for key, val in pairs))
    return bool(pattern and re.fullmatch(pattern, url.path)
                and (not url.query or (url.netloc == "static.dc.com" and url.query in {"w=160", "w=540"})))


@lru_cache(maxsize=1)
def reviewed_catalogue_entries():
    data = Path(__file__).resolve().parents[1] / "data"
    return [row for name in ("book_catalogue_starter_20261016.json", "book_catalogue_expansion_20261021.json")
            for row in json.loads((data / name).read_text())["entries"]]


@lru_cache(maxsize=1)
def reviewed_covers():
    path = Path(__file__).resolve().parents[1] / "data/book_reference_covers_20261017.json"
    covers = {row["catalogue_id"]: row for row in json.loads(path.read_text())["entries"]}
    covers.update({row["id"]: row["reference"] for row in reviewed_catalogue_entries() if row.get("reference")})
    return covers


def book_cover_reference(book, language):
    """Only the reviewed edition can use a cover; no title/ISBN-only fallback."""
    attrs = book.get("attributes") or {}
    if isinstance(attrs, str):
        attrs = json.loads(attrs)
    if not isinstance(attrs, dict):
        return None
    entry = reviewed_covers().get(str(book.get("catalogue_id")))
    if not entry:
        # Only trusted importer records, never seller-entered attributes or a
        # title/ISBN-only cover guess. RLS restricts STRUCTURED publisher writes
        # to administrators; the private image route rechecks this on each read.
        receipt = attrs.get("catalogue_import")
        candidate = attrs.get("publisher_reference")
        if (not isinstance(receipt, dict) or receipt.get("version") != "book-bulk-v1"
                or receipt.get("provider") not in {"PRH", "PUBLISHER"}
                or not re.fullmatch(r"[a-f0-9]{64}", str(receipt.get("record_digest", "")))
                or not isinstance(candidate, dict)):
            return None
        from .book_research import publisher_source, source_cover_matches
        if (candidate.get("catalogue_id") != str(book.get("catalogue_id"))
                or not publisher_source(candidate.get("source_url"))
                or not source_cover_matches(candidate["source_url"], candidate.get("image_url"))
                or not re.fullmatch(r"[a-f0-9]{64}", str(candidate.get("observed_sha256", "")))
                or any(type(candidate.get(k)) is not int or candidate[k] < 200
                       for k in ("observed_width", "observed_height"))
                or not {"language", "release_date", "book_identity_digest"}.issubset(candidate)):
            return None
        entry = candidate
    if not entry or language != entry["language"]:
        return None
    try:
        release = date.fromisoformat(entry["release_date"]) if entry["release_date"] else None
    except (TypeError, ValueError):
        return None
    if (book.get("identity_status") not in {"STRUCTURED", "VERIFIED"}
            or book.get("profile_status") not in {"STRUCTURED", "VERIFIED"}
            or attrs.get("identity_source") != "OFFICIAL_PUBLISHER_CATALOGUE"
            or attrs.get("source_url") != entry["source_url"]
            or attrs.get("cover_rights_status") in {"REVOKED", "REJECTED"}
            or attrs.get("cover_source_status") in {"REVOKED", "INACTIVE"}
            or (str(book.get("profile_release_date")) if book.get("profile_release_date") else None) != entry["release_date"]
            or (release and release > date.today())
            or (not entry["release_date"] and (not book.get("release_year") or book["release_year"] >= date.today().year))
            or (attrs.get("publisher_reference") is not None and attrs["publisher_reference"] != entry)):
        return None
    fields = {**book, "publisher": attrs.get("publisher"), "book_format": attrs.get("book_format")}
    if printing_digest(fields) != entry["book_identity_digest"] or not publisher_cover_url(entry["image_url"]):
        return None
    return entry
