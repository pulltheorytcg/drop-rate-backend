"""Reviewed CC BY 4.0 Topps Heritage references, in an independent R2 partition.

The licence covers Card Collector Capital's compilation and annotations, not
Topps artwork or the linked manufacturer PDF. This module fetches only the
reviewed 100-number JSON export. Neither the PDF nor any images are downloaded.
Checklist language, short-print designation and notes do not approve a physical
card's language, parallel, condition, ownership, authenticity or market value.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import hashlib
import unicodedata

import httpx

from . import r2_first_sources as sources


PROVIDER = "cardcollectorcapital_heritage"
SYSTEM_CODE = "SPORTS_CARDS"
DOWNLOAD_URL = "https://cardcollectorcapital.com/data/2026-topps-heritage-short-prints.json"
PERMISSION_REF = "https://cardcollectorcapital.com/data"
SOURCE_REVISION = "topps-heritage-short-prints-2026-09-30-metadata-v1"
SOURCE_REVIEWED_DATE = "2026-09-30"
SOURCE_CREDIT = "Card Collector Capital"
SOURCE_LICENSE = "https://creativecommons.org/licenses/by/4.0/"
SOURCE_TITLE = "2026 Topps Heritage starred base checklist"
SOURCE_EVIDENCE_URL = "https://cdn.shopify.com/s/files/1/0662/9749/5709/files/Checklist_26THBB_3.20.pdf?v=1774362662"
SOURCE_EVIDENCE_SHA256 = "4ad60fa68d1429519f9ceeee11188663d9b3c64b2a5e387112f1bb857d967c8a"
REVIEWED_EXPORT_SHA256 = "cb37f288a573533e6be0ebb8229dcf34d6d78f419018044447ed52aedcc226bd"
REFERENCE_SCOPE = "CHECKLIST_REFERENCE_ONLY_PHYSICAL_IDENTITY_UNVERIFIED"
SET_ID = "2026-topps-heritage"
SET_NAME = "2026 Topps Heritage"
MAX_BYTES = 65_536
EXPECTED_ROWS = 100
_SECTIONS = frozenset({"Base Cards", "World Series Highlights", "Turn Back The Clock", "Quad Rookies"})
_BACK_VARIATION_NOTE = "Official checklist also flags Back Variation; distinguish from Owen Caissie #88."


def _text(value, label: str, maximum: int = 256, *, optional: bool = False) -> str:
    result = sources._text(value, label, optional=optional, max_length=maximum)
    if any(unicodedata.category(char).startswith("C") for char in result):
        raise sources.SourceError(f"Invalid {label}")
    return result


def normalize_topps_heritage(payload, language: str = "English") -> list[dict]:
    """Preserve one reference per source card number, including multi-player cards.

    Offline fixtures may contain a subset; the network entry point requires all
    100 numbers and the reviewed export digest. The export's licence is recorded
    on its data-hub page, not invented from a third-party manufacturer's licence.
    """
    language_code, language_name = sources._language(language)
    if language_code != "en":
        raise sources.SourceError("Heritage checklist catalogue-language scope is English-only")
    if (not isinstance(payload, Mapping)
            or payload.get("title") != SOURCE_TITLE
            or payload.get("reviewedDate") != SOURCE_REVIEWED_DATE
            or payload.get("sourceUrl") != SOURCE_EVIDENCE_URL
            or payload.get("sourceSha256") != SOURCE_EVIDENCE_SHA256
            or type(payload.get("count")) is not int
            or payload["count"] != EXPECTED_ROWS
            or payload.get("license", SOURCE_LICENSE) != SOURCE_LICENSE
            or payload.get("creator", SOURCE_CREDIT) != SOURCE_CREDIT):
        raise sources.SourceError("Heritage source licence or reviewed-version evidence mismatch")
    rows = payload.get("cards")
    if not isinstance(rows, list) or not 0 < len(rows) <= EXPECTED_ROWS:
        raise sources.SourceError("Empty or oversized Heritage checklist snapshot")
    result, seen_numbers = [], set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise sources.SourceError("Invalid Heritage checklist row")
        number = row.get("number")
        if type(number) is not int or not 1 <= number <= 400:
            raise sources.SourceError("Invalid Heritage checklist card number")
        if number in seen_numbers:
            raise sources.SourceError("Duplicate Heritage checklist card number")
        seen_numbers.add(number)
        section = _text(row.get("category"), "Heritage checklist section")
        if section not in _SECTIONS:
            raise sources.SourceError("Unreviewed Heritage checklist section")
        subjects = row.get("subjects")
        expected_subjects = 4 if section == "Quad Rookies" else 1
        if not isinstance(subjects, list) or len(subjects) != expected_subjects:
            raise sources.SourceError("Invalid Heritage checklist subjects")
        subjects = [_text(subject, "Heritage subject", 128) for subject in subjects]
        if len(set(subjects)) != len(subjects):
            raise sources.SourceError("Duplicate Heritage checklist subject")
        player = _text(" / ".join(subjects), "Heritage combined subjects")
        pages = row.get("sourcePages")
        if (not isinstance(pages, list) or not 0 < len(pages) <= 8
                or any(type(page) is not int or not 1 <= page <= 8 for page in pages)
                or len(set(pages)) != len(pages)):
            raise sources.SourceError("Invalid Heritage checklist evidence pages")
        note = _text(row.get("note"), "Heritage checklist note", optional=True)
        expected_note = _BACK_VARIATION_NOTE if number == 360 else ""
        if note != expected_note or (number == 360 and subjects != ["Owen Caissie"]):
            raise sources.SourceError("Unreviewed Heritage checklist note")
        native_id = f"{SET_ID}-{number}"
        record = sources._record(PROVIDER, SYSTEM_CODE, language_name, native_id,
            name=player, set_id=SET_ID, set_name=SET_NAME, card_number=str(number),
            source_url=DOWNLOAD_URL)
        record["details"] = {
            "player": player,
            "sport": "Baseball",
            "brand": "Topps Heritage",
            "manufacturer": "Topps",
            "source_record_id": native_id,
            "source_evidence_url": SOURCE_EVIDENCE_URL,
            "source_reviewed_at": SOURCE_REVIEWED_DATE,
            "source_page": ", ".join(str(page) for page in sorted(pages)),
            "source_year": "2026",
            "source_credit": SOURCE_CREDIT,
            "source_license": SOURCE_LICENSE,
            "checklist_section": section,
            "reference_scope": REFERENCE_SCOPE,
        }
        if note:
            record["details"]["source_note"] = note
        result.append(record)
    return sorted(result, key=lambda record: record["provider_id"])


async def fetch_topps_heritage(client: httpx.AsyncClient,
                              descriptor: sources.SourceDescriptor) -> sources.FetchedSource:
    """One credential-free bounded GET; changed exports require a new review.

    No redirects, denial retries, linked-document reads or fallback providers.
    The old Bowman descriptor, manifest and reference keys remain untouched.
    """
    expected = sources.SourceDescriptor(PROVIDER, SYSTEM_CODE, DOWNLOAD_URL,
        SOURCE_REVISION, PERMISSION_REF, "METADATA_ACCESS_DOCUMENTED", DOWNLOAD_URL, MAX_BYTES)
    if descriptor != expected:
        raise sources.SourcePermissionError("Heritage source descriptor does not match the reviewed export")
    sources._assert_public_client(client)
    try:
        async with asyncio.timeout(sources.TOTAL_DOWNLOAD_TIMEOUT_SECONDS):
            content = await sources._download(client, DOWNLOAD_URL, MAX_BYTES)
    except TimeoutError as exc:
        raise sources.SourceError("Heritage source exceeded its total download time bound") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != REVIEWED_EXPORT_SHA256:
        raise sources.SourceError("Heritage export changed; source review required")
    records = normalize_topps_heritage(sources._decode_json(content))
    if len(records) != EXPECTED_ROWS:
        raise sources.SourceError("Incomplete reviewed Heritage checklist export")
    return sources.FetchedSource(PROVIDER, SYSTEM_CODE, DOWNLOAD_URL,
        "sha256:" + digest, digest, records)
