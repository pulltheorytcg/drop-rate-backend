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
        "cdn.marvel.com": r"/u/prod/marvel/i/mg/[a-f0-9]/[a-f0-9]{2}/[a-f0-9]+/clean\.jpg",
        "imgix-media.wbdndc.net": r"/ingest/book/preview/[a-f0-9-]{36}/[a-f0-9-]{36}/0\.jpg",
    }
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
def reviewed_covers():
    path = Path(__file__).resolve().parents[1] / "data/book_reference_covers_20261017.json"
    return {row["catalogue_id"]: row for row in json.loads(path.read_text())["entries"]}


def book_cover_reference(book, language):
    """Only the reviewed edition can use a cover; no title/ISBN-only fallback."""
    entry = reviewed_covers().get(str(book.get("catalogue_id")))
    if not entry or language != entry["language"]:
        return None
    attrs = book.get("attributes") or {}
    if isinstance(attrs, str):
        attrs = json.loads(attrs)
    if not isinstance(attrs, dict):
        return None
    if (book.get("identity_status") not in {"STRUCTURED", "VERIFIED"}
            or book.get("profile_status") not in {"STRUCTURED", "VERIFIED"}
            or attrs.get("identity_source") != "OFFICIAL_PUBLISHER_CATALOGUE"
            or attrs.get("source_url") != entry["source_url"]
            or attrs.get("cover_rights_status") in {"REVOKED", "REJECTED"}
            or attrs.get("cover_source_status") in {"REVOKED", "INACTIVE"}
            or str(book.get("profile_release_date")) != entry["release_date"]
            or date.fromisoformat(entry["release_date"]) > date.today()):
        return None
    fields = {**book, "publisher": attrs.get("publisher"), "book_format": attrs.get("book_format")}
    if printing_digest(fields) != entry["book_identity_digest"] or not publisher_cover_url(entry["image_url"]):
        return None
    return entry
