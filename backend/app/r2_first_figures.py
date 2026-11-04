"""Bounded local curation, not an automated Funko API or bulk-data licence.

The four Funko product pages were individually reviewed for short product
facts. Two previously reviewed Good Smile references remain in the canonical
catalogue: they are neither re-imported nor duplicated here. This four-reference
partial starter contains no artwork, prices or descriptive prose. Its source-
access status documents this manual compilation only. Adding other products or
a network refresh requires another explicit source-access review.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import date
import hashlib
from pathlib import Path
import re
from types import MappingProxyType
import unicodedata

import httpx

from . import r2_first_sources as sources


PROVIDER = "reviewed_figures"
SYSTEM_CODE = "FIGURES"
CATALOGUE_LANGUAGE = "Not applicable"
SOURCE_URL = "https://github.com/pulltheorytcg/drop-rate-backend/blob/main/backend/data/r2_figure_starter_20261104.json"
PERMISSION_REF = "https://github.com/pulltheorytcg/drop-rate-backend/blob/main/docs/R2_CATALOGUE_EXPANSION_20261104.md"
SOURCE_REVISION = "reviewed-figures-2026-11-04-metadata-v1"
REVIEWED_AT = "2026-11-04"
REFERENCE_SCOPE = "CURATED_REFERENCE_ONLY_PHYSICAL_IDENTITY_UNVERIFIED"
SCHEMA = "drop-rate-reviewed-figure-starter-v1"
MAX_BYTES = 131_072
EXPECTED_ROWS = 4
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_STARTER_PATH = _DATA_DIR / "r2_figure_starter_20261104.json"
_FUNKO_SOURCES = MappingProxyType({
    "funko:43263": ("https://www.funko.com/lt/pop-pikachu/43263.html", "funko-pop-pokemon"),
    "funko:5305": ("https://funko.com/ch/pop-monkey.-d.-luffy/5305.html", "funko-pop-one-piece"),
    "funko:80341": ("https://funko.com/gg/pop-naruto-uzumaki-with-scroll/80341.html", "funko-pop-naruto"),
    "funko:90617": ("https://funko.com/gb/pop-temari-with-tessen/90617.html", "funko-pop-naruto"),
})
_FUNKO_FIELDS = frozenset({
    "source_id", "product_type", "name", "manufacturer", "franchise", "character",
    "product_line", "manufacturer_sku", "box_number", "source_url", "source_checked_at",
})


def _text(value, label: str, maximum: int = 256) -> str:
    result = sources._text(value, label, max_length=maximum)
    if result != value or any(unicodedata.category(char).startswith("C") for char in result):
        raise sources.SourceError(f"Invalid {label}")
    return result


def _checked_date(value, expected: str) -> str:
    parsed = sources._date(value)
    if parsed != expected or date.fromisoformat(parsed) > date.fromisoformat(REVIEWED_AT):
        raise sources.SourceError("Figure review date is outside the reviewed source version")
    return parsed


def _reference(native_id: str, *, name: str, set_id: str, set_name: str,
               evidence_url: str, reviewed_at: str, details: dict) -> dict:
    record = sources._record(
        PROVIDER, SYSTEM_CODE, CATALOGUE_LANGUAGE, native_id,
        name=name, set_id=set_id, set_name=set_name, source_url=SOURCE_URL,
    )
    record["product_type"] = "FIGURE"
    record["details"] = {
        **details,
        "source_record_id": native_id,
        "source_evidence_url": evidence_url,
        "source_reviewed_at": reviewed_at,
        "source_credit": details["manufacturer"],
        "reference_scope": REFERENCE_SCOPE,
    }
    return record


def _funko(row: Mapping) -> dict:
    if set(row) != _FUNKO_FIELDS:
        raise sources.SourceError("Unexpected or missing reviewed Funko fields")
    native_id = _text(row.get("source_id"), "figure source ID")
    if native_id not in _FUNKO_SOURCES:
        raise sources.SourceError("Unreviewed Funko reference")
    evidence_url, set_id = _FUNKO_SOURCES[native_id]
    if (row.get("product_type") != "FIGURE" or row.get("manufacturer") != "Funko"
            or row.get("product_line") != "Pop!" or row.get("source_url") != evidence_url):
        raise sources.SourceError("Funko product type or reviewed provenance mismatch")
    reviewed_at = _checked_date(row.get("source_checked_at"), REVIEWED_AT)
    sku = _text(row.get("manufacturer_sku"), "Funko manufacturer SKU")
    box_number = _text(row.get("box_number"), "Funko box number")
    if "funko:" + sku != native_id or not re.fullmatch(r"[1-9][0-9]{0,7}", box_number):
        raise sources.SourceError("Invalid Funko product SKU or box number")
    details = {field: _text(row.get(field), "figure " + field) for field in (
        "manufacturer", "franchise", "character", "product_line")}
    details.update(manufacturer_sku=sku, box_number=box_number)
    return _reference(native_id, name=_text(row.get("name"), "figure name", 512),
        set_id=set_id, set_name=" · ".join((details["manufacturer"],
            details["product_line"], details["franchise"])),
        evidence_url=evidence_url, reviewed_at=reviewed_at, details=details)


def normalize_figures(starter, language: str = CATALOGUE_LANGUAGE) -> list[dict]:
    """Offline four-reference curation; never claims physical-copy approval.

    English is accepted only as the dispatcher's historical default argument.
    The resulting partition always uses 'Not applicable', never a guessed
    packaging or physical-item language. The two existing canonical Good Smile
    references are deliberately not duplicated into this R2 source partition.
    """
    if language not in (CATALOGUE_LANGUAGE, "English"):
        raise sources.SourceError("Reviewed figure catalogue language is not applicable")
    if (not isinstance(starter, Mapping) or starter.get("schema") != SCHEMA
            or starter.get("reference_scope") != REFERENCE_SCOPE):
        raise sources.SourceError("Invalid reviewed figure starter version")
    _checked_date(starter.get("reviewed_at"), REVIEWED_AT)
    new_rows = starter.get("figures")
    if not isinstance(new_rows, list) or len(new_rows) != len(_FUNKO_SOURCES):
        raise sources.SourceError("Incomplete or unreviewed figure starter selection")
    records, seen = [], set()
    for row in new_rows:
        if not isinstance(row, Mapping):
            raise sources.SourceError("Invalid reviewed Funko row")
        record = _funko(row)
        if record["provider_id"] in seen:
            raise sources.SourceError("Duplicate reviewed figure source ID")
        seen.add(record["provider_id"])
        records.append(record)
    if len(records) != EXPECTED_ROWS:
        raise sources.SourceError("Incomplete reviewed figure starter")
    return sorted(records, key=lambda record: record["provider_id"])


def _read_local(path: Path) -> bytes:
    try:
        with path.open("rb") as source_file:
            content = source_file.read(MAX_BYTES + 1)
    except OSError as exc:
        raise sources.SourceError("Reviewed figure starter file is unavailable") from exc
    if not content or len(content) > MAX_BYTES:
        raise sources.SourceError("Empty or oversized reviewed figure starter file")
    return content


def _load_local() -> tuple[list[dict], str]:
    starter_bytes = _read_local(_STARTER_PATH)
    records = normalize_figures(sources._decode_json(starter_bytes))
    digest = hashlib.sha256(starter_bytes).hexdigest()
    return records, digest


async def fetch_figures(client: httpx.AsyncClient, descriptor: sources.SourceDescriptor) -> sources.FetchedSource:
    """Load one fixed repository file. The HTTP client is deliberately unused."""
    expected = sources.SourceDescriptor(PROVIDER, SYSTEM_CODE, SOURCE_URL, SOURCE_REVISION,
        PERMISSION_REF, "METADATA_ACCESS_DOCUMENTED", SOURCE_URL, MAX_BYTES,
        catalogue_language=CATALOGUE_LANGUAGE)
    if descriptor != expected:
        raise sources.SourcePermissionError("Figure descriptor does not match the reviewed local starter")
    records, digest = await asyncio.to_thread(_load_local)
    return sources.FetchedSource(PROVIDER, SYSTEM_CODE, SOURCE_URL, "sha256:" + digest, digest, records)
