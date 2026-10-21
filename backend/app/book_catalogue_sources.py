"""Edition adapters for authorised publisher/GCD exports, never copy approval.

Source JSON is data. Missing classification, edition or language is quarantined;
we never infer a first printing or reuse a cover from another ISBN/issue.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from uuid import NAMESPACE_URL, uuid5

from .book_market import printing_digest
from .book_recognition import valid_book_barcode
from .book_research import publisher_source, source_cover_matches
from .comic_identity import ComicPrintingCreate
from .inventory_intake import _manual_identity_key
from .schemas import ManualCatalogueCreate

IMPORT_VERSION = "book-bulk-v1"
GCD_LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"
LANGUAGES = {"en": "English", "e": "English", "ja": "Japanese", "j": "Japanese",
             "fr": "French", "de": "German", "es": "Spanish", "sp": "Spanish",
             "it": "Italian", "pt": "Portuguese", "ko": "Korean", "zh": "Chinese"}


class ReviewRequired(ValueError):
    """Stable reason code, safe to log without source payloads or credentials."""


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def language_name(value):
    for name in LANGUAGES.values():
        if str(value).casefold() == name.casefold():
            return name
    result = LANGUAGES.get(str(value).lower())
    if not result:
        raise ReviewRequired("LANGUAGE_REVIEW_REQUIRED")
    return result


def _gcd_id(value, resource):
    match = re.fullmatch(r"https://www\.comics\.org/api/" + resource + r"/([1-9][0-9]*)/", str(value))
    if not match:
        raise ReviewRequired("GCD_RESOURCE_REVIEW_REQUIRED")
    return match[1]


def _barcode(value):
    result = "".join(str(value or "").replace("-", "").split()).upper() or None
    if result and not valid_book_barcode(result):
        raise ReviewRequired("INVALID_OR_MULTIPLE_BARCODES")
    if result and len(result) == 10:
        base = "978" + result[:9]
        result = base + str((-sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(base))) % 10)
    return result


def barcode_aliases(value):
    """Find legacy ISBN-10 / zero-prefixed UPC rows without dropping add-ons."""
    canonical = _barcode(value)
    aliases = {canonical} if canonical else set()
    if canonical and len(canonical) == 13 and canonical.startswith("978"):
        base = canonical[3:12]
        check = (-sum(int(n) * (10 - i) for i, n in enumerate(base))) % 11
        aliases.add(base + ("X" if check == 10 else str(check)))
    elif canonical and len(canonical) == 12:
        aliases.add("0" + canonical)
    elif canonical and len(canonical) == 13 and canonical.startswith("0"):
        aliases.add(canonical[1:])
    return sorted(aliases)


def from_gcd(row):
    """One joined API issue/series/publisher record; rules are per series.

    GCD does not provide a reliable universal manga/physical format flag. Require
    the operator's reviewed classification; never classify by country or title.
    GCD's data licence does not grant cover image rights, so ignore its scans.
    """
    issue, series, publisher = row["issue"], row["series"], row["publisher"]
    record_id = _gcd_id(issue["api_url"], "issue")
    series_id = _gcd_id(series["api_url"], "series")
    if issue["series"] != series["api_url"] or series["publisher"] != publisher["api_url"]:
        raise ReviewRequired("GCD_RELATION_MISMATCH")
    _gcd_id(publisher["api_url"], "publisher")
    rule = row["classification"]
    if str(rule["series_id"]) != series_id:
        raise ReviewRequired("GCD_CLASSIFICATION_MISMATCH")
    variant = issue.get("variant_name") or None
    if issue.get("variant_of") and not variant:
        raise ReviewRequired("VARIANT_NAME_REQUIRED")
    year = re.match(r"^([0-9]{4})", str(issue.get("key_date") or ""))
    if not year or not series.get("year_began"):
        raise ReviewRequired("SERIES_AND_RELEASE_YEAR_REQUIRED")
    released = issue.get("on_sale_date") or None
    if released and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", released):
        released = None  # Partial dates are not exact publication dates.
    book = dict(system_code=rule["system_code"], book_format=rule["book_format"],
                series_title=series["name"], issue_number=str(issue["number"]),
                volume_identifier=f"Series {series['year_began']}" + (f" / {issue['volume']}" if issue.get("volume") else ""),
                release_year=int(year[1]), cover_code=variant,
                barcode_gtin=_barcode(issue.get("isbn") or issue.get("barcode")), publisher=publisher["name"])
    return dict(provider="GCD", record_id=record_id, book=book,
                language=series["language"], release_date=released,
                source_url=f"https://www.comics.org/issue/{record_id}/", observed_on=row["observed_on"],
                evidence_url=f"https://www.comics.org/issue/{record_id}/" if variant else None,
                metadata_license=GCD_LICENSE, image_url=None)


def from_prh(row):
    """PRH Title representation: ISBN editions, not work-level cover guesses."""
    title = row["title"]
    isbn = _barcode(title["isbn"])
    if not isbn or len(isbn) != 13:
        raise ReviewRequired("PRH_ISBN13_REQUIRED")
    subjects = title.get("subjects") or []
    if not any(str(s.get("code", "")).startswith("CGN") for s in subjects):
        raise ReviewRequired("COMICS_OR_MANGA_SUBJECT_REQUIRED")
    manga = any("manga" in str(s.get("description", "")).casefold() for s in subjects)
    form = title.get("format", {}).get("code")
    if form not in {"TR", "HC"}:
        raise ReviewRequired("PHYSICAL_BOOK_FORMAT_REVIEW_REQUIRED")
    publisher = title.get("consumerImprint") or title.get("imprint", {}).get("description")
    if not publisher:
        raise ReviewRequired("PUBLISHER_REQUIRED")
    system = "MANGA" if manga else {"marvel": "MARVEL_COMICS", "dc comics": "DC_COMICS", "dc": "DC_COMICS"}.get(publisher.casefold(), "OTHER_COMICS")
    # Keep omnibus/deluxe/edition words in the title. A work can have many ISBNs.
    name = title["title"]
    match = re.fullmatch(r"(.+?)\s*,?\s+(?:Vol\.?|Volume|#)\s*([0-9]+(?:[-–][0-9]+)?)(?:\s*[:\-]\s*(.+))?", name, re.I)
    number = title.get("seriesNumber")
    if match and number not in (None, 0, "0") and str(number) != match[2]:
        raise ReviewRequired("VOLUME_NUMBER_CONFLICT")
    # Ambiguous bare numbers (e.g. '86') are never parsed as volume numbers.
    if match:
        name, number = match[1] + (f": {match[3]}" if match[3] else ""), match[2]
    elif number not in (None, 0, "0"):
        number = str(number)
    else:
        raise ReviewRequired("ISSUE_OR_VOLUME_NUMBER_REQUIRED")
    edition = " / ".join(str(v) for v in (title.get("formatFamily"), title.get("editionType"),
                          title.get("version") if title.get("version") != "Regular Edition" else None) if v) or None
    image = next((link.get("href") for link in title.get("_links", []) if link.get("rel") == "icon"), None)
    if image == f"https://images.randomhouse.com/cover/{isbn}":
        image = f"https://images.penguinrandomhouse.com/cover/{isbn}"
    source = f"https://prhcomics.com/book/?isbn={isbn}"
    if not source_cover_matches(source, image):
        image = None
    released = date.fromisoformat(title["onsale"])
    return dict(provider="PRH", record_id=isbn, book=dict(system_code=system,
                book_format="MANGA" if manga else {"TR": "TRADE_PAPERBACK", "HC": "HARDCOVER"}[form],
                series_title=name, issue_number=str(number), publisher=publisher,
                release_year=released.year, volume_identifier=edition, barcode_gtin=isbn),
                language=title["language"], release_date=released.isoformat(), source_url=source,
                observed_on=row["observed_on"], metadata_license="PROVIDER_TERMS", image_url=image)


def normalise(provider, row):
    if provider == "GCD":
        row = from_gcd(row)
    elif provider == "PRH":
        row = from_prh(row)
    elif provider == "PUBLISHER":
        row = {**row, "provider": provider, "metadata_license": "PROVIDER_TERMS"}
    else:
        raise ReviewRequired("UNKNOWN_PROVIDER")
    return _normalise_adapted(row)


def _normalise_adapted(row):
    provider = row["provider"]
    if provider not in {"GCD", "PRH", "PUBLISHER"}:
        raise ReviewRequired("UNKNOWN_PROVIDER")
    book = ComicPrintingCreate.model_validate(row["book"])
    language = language_name(row["language"])
    released = date.fromisoformat(row["release_date"]) if row.get("release_date") else None
    if not book.release_year or (released and released.year != book.release_year):
        raise ReviewRequired("RELEASE_YEAR_MISMATCH")
    if (released and released > date.today()) or (not released and book.release_year >= date.today().year):
        raise ReviewRequired("RELEASE_NOT_ESTABLISHED")
    observed = date.fromisoformat(row["observed_on"])
    if observed > date.today():
        raise ReviewRequired("FUTURE_SOURCE_OBSERVATION")
    book.barcode_gtin = _barcode(book.barcode_gtin)
    source = row["source_url"]
    if provider == "GCD":
        if (not re.fullmatch(r"[1-9][0-9]*", str(row["record_id"]))
                or source != f"https://www.comics.org/issue/{row['record_id']}/"):
            raise ReviewRequired("UNTRUSTED_SOURCE")
    elif not publisher_source(source):
        raise ReviewRequired("UNTRUSTED_SOURCE")
    if any((book.printing_number, book.cover_code, book.cover_artist)) and row.get("evidence_url") != source:
        raise ReviewRequired("PRINTING_OR_VARIANT_EVIDENCE_REQUIRED")
    record_id = str(row["record_id"])
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", record_id):
        raise ReviewRequired("INVALID_RECORD_ID")
    # Publisher IDs are scoped by origin, since different publishers reuse IDs.
    if provider == "PUBLISHER":
        from urllib.parse import urlsplit
        record_id = f"{urlsplit(source).netloc}:{record_id}"
    product = ManualCatalogueCreate(product_type="COMIC", language=language,
                                   comic_printing=book, **book.catalogue_fields())
    key = _manual_identity_key(product)
    image = row.get("image_url")
    if image and (provider == "GCD" or not source_cover_matches(source, image)):
        raise ReviewRequired("UNTRUSTED_OR_MISMATCHED_COVER")
    entry = dict(id=str(uuid5(NAMESPACE_URL, "drop-rate:" + key)), identity_key=key,
                 catalogue=product.model_dump(exclude={"comic_printing"}), book=book.model_dump(),
                 provider=provider, record_id=record_id, source_url=source,
                 release_date=released.isoformat() if released else None, observed_on=observed.isoformat(),
                 metadata_license=GCD_LICENSE if provider == "GCD" else "PROVIDER_TERMS", evidence_url=row.get("evidence_url"),
                 image_url=image, reference=None, import_version=IMPORT_VERSION)
    entry["record_digest"] = record_digest(entry)
    return entry


def record_digest(entry):
    # Observation dates and independently checked cover bytes may change on replay.
    return digest({k: v for k, v in entry.items() if k not in {"record_digest", "observed_on", "reference"}})


def cover_receipt(entry, sha256, width, height):
    if not source_cover_matches(entry["source_url"], entry.get("image_url")):
        raise ReviewRequired("UNTRUSTED_OR_MISMATCHED_COVER")
    if not re.fullmatch(r"[a-f0-9]{64}", sha256) or min(width, height) < 200:
        raise ReviewRequired("COVER_BYTES_NOT_USABLE")
    return dict(catalogue_id=entry["id"], language=entry["catalogue"]["language"],
                book_identity_digest=printing_digest(entry["book"]), source_url=entry["source_url"],
                release_date=entry["release_date"], image_url=entry["image_url"],
                observed_sha256=sha256, observed_width=width, observed_height=height)


def validate_entry(entry):
    """Revalidate local staging data before any database write."""
    row = {k: entry[k] for k in ("record_id", "book", "source_url", "release_date", "observed_on", "image_url", "evidence_url")}
    row["language"] = entry["catalogue"]["language"]
    provider = entry["provider"]
    row["provider"] = provider
    if provider == "PUBLISHER":
        row["record_id"] = row["record_id"].split(":", 1)[1]
    candidate = _normalise_adapted(row)
    if {k: v for k, v in candidate.items() if k != "reference"} != {k: v for k, v in entry.items() if k != "reference"}:
        raise ReviewRequired("STAGING_INTEGRITY_MISMATCH")
    if entry.get("reference"):
        ref = entry["reference"]
        if provider == "GCD" or ref != cover_receipt(entry, ref["observed_sha256"], ref["observed_width"], ref["observed_height"]):
            raise ReviewRequired("STAGING_COVER_MISMATCH")
