"""Permitted, bounded sports-checklist references for the R2-first catalogue.

Card Collector Capital explicitly licenses its compilation and annotations
under CC BY 4.0 at https://cardcollectorcapital.com/data. The reviewed export
contains 1,722 rows from three selected Bowman checklists, not an all-sports
catalogue. Its licence does not relicense the linked Topps documents or artwork.

Only factual reference fields and attribution leave this adapter. A checklist
row does not approve a physical item's variant, language, condition, ownership,
authenticity or value. No image, document, price or arbitrary URL is fetched.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import re
from types import MappingProxyType
import unicodedata

import httpx

from . import r2_first_sources as sources


PROVIDER = "cardcollectorcapital"
SYSTEM_CODE = "SPORTS_CARDS"
DOWNLOAD_URL = "https://cardcollectorcapital.com/data/bowman-checklist-lookup-2026-10-27.json"
PERMISSION_REF = "https://cardcollectorcapital.com/data"
SOURCE_REVISION = "bowman-checklist-2026-10-27-metadata-v1"
SOURCE_REVIEWED_DATE = "2026-10-27"
SOURCE_CREDIT = "Card Collector Capital"
SOURCE_LICENSE = "https://creativecommons.org/licenses/by/4.0/"
REFERENCE_SCOPE = "CHECKLIST_REFERENCE_ONLY_PHYSICAL_IDENTITY_UNVERIFIED"
MAX_BYTES = 2_000_000
EXPECTED_ROWS = 1722


@dataclass(frozen=True, slots=True)
class _Product:
    slug: str
    evidence_url: str
    product_url: str
    sections: frozenset[str]


_PRODUCTS = MappingProxyType({
    (2026, "Bowman Baseball"): _Product(
        "2026-bowman-baseball",
        "https://cdn.shopify.com/s/files/1/0662/9749/5709/files/2026_Bowman_Baseball_Checklist.pdf?v=1775743176",
        "https://www.topps.com/pages/bowman-baseball",
        frozenset({"Paper Prospects", "Chrome Prospects",
            "Chrome Prospect Packfractor Variation", "Paper Prospect Retail Autograph",
            "Chrome Prospects Autograph Variation", "Chrome Prospects Autographs Gold Ink Variation",
            "Chrome Prospect Packfractor Autograph Variation"})),
    (2026, "Bowman Chrome Baseball"): _Product(
        "2026-bowman-chrome-baseball",
        "https://cdn.shopify.com/s/files/1/0662/9749/5709/files/2026_Bowman_Chrome_Baseball_Checklist_1.pdf?v=1786458901",
        "https://uk.topps.com/pages/bowman-chrome-baseball",
        frozenset({"Bowman Chrome Prospects", "International Refractor Variation",
            "Chrome Prospect Packfractor Variation", "Bowman Chrome Prospect Autographs",
            "Chrome Prospect Autographs Gold Ink Variation", "Chrome Prospect Packfractor Autograph Variation",
            "International Refractor Autograph Variation"})),
    (2025, "Bowman Draft Baseball"): _Product(
        "2025-bowman-draft-baseball",
        "https://cdn.shopify.com/s/files/1/0662/9749/5709/files/2025_Bowman_Draft_Baseball_Checklist.pdf?v=1766089735",
        "https://www.topps.com/pages/bowman-draft-baseball",
        frozenset({"Base Cards", "Chrome Base Cards", "Etched In Glass Variation",
            "Image Variations", "Chrome Prospect College Variations",
            "Chrome Prospect Autograph Variation", "Chrome Prospect Autographs Gold Ink Variation",
            "Image Variations Autographs"})),
})
_FAMILIES = frozenset({"Paper prospect", "Chrome prospect", "Checklist variation", "Prospect autograph"})
_SOURCE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_CARD_CODE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\Z")


def _text(value, label: str, maximum: int = 256, *, optional: bool = False) -> str:
    result = sources._text(value, label, optional=optional, max_length=maximum)
    if any(unicodedata.category(char).startswith("C") for char in result):
        raise sources.SourceError(f"Invalid {label}")
    return result


def normalize_sports(payload, language: str = "English") -> list[dict]:
    """Normalize a reviewed checklist subset without inventing printings.

    Offline fixtures may contain a subset. The network entry point additionally
    requires the complete pinned export's row count before returning any data.
    Source record IDs are preserved exactly, never reconstructed from player or
    card code: different players can share a checklist autograph code.
    """
    language_code, language_name = sources._language(language)
    if language_code != "en":
        raise sources.SourceError("Sports checklist catalogue-language scope is English-only")
    if (not isinstance(payload, Mapping)
            or payload.get("license") != SOURCE_LICENSE
            or payload.get("creator") != SOURCE_CREDIT
            or payload.get("reviewedDate") != SOURCE_REVIEWED_DATE):
        raise sources.SourceError("Sports source licence or reviewed-version evidence mismatch")
    rows = payload.get("records")
    if not isinstance(rows, list) or not 0 < len(rows) <= EXPECTED_ROWS:
        raise sources.SourceError("Empty or oversized sports checklist snapshot")
    result, seen_ids = [], set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise sources.SourceError("Invalid sports checklist row")
        year = row.get("year")
        product_name = _text(row.get("product"), "sports product")
        product = _PRODUCTS.get((year, product_name)) if type(year) is int else None
        if product is None:
            raise sources.SourceError("Unreviewed sports checklist product")
        native_id = _text(row.get("id"), "sports source record ID")
        page = row.get("sourcePage")
        if (native_id != row.get("id") or not _SOURCE_ID.fullmatch(native_id)
                or not native_id.startswith(product.slug + "-")
                or type(page) is not int or not 1 <= page <= 100
                or not native_id.endswith("-" + str(page))):
            raise sources.SourceError("Invalid sports checklist identity or page")
        if native_id in seen_ids:
            raise sources.SourceError("Duplicate sports source record ID")
        seen_ids.add(native_id)
        if (row.get("sourceUrl") != product.evidence_url
                or row.get("productUrl") != product.product_url
                or row.get("reviewedDate") != SOURCE_REVIEWED_DATE):
            raise sources.SourceError("Sports checklist source provenance mismatch")
        section = _text(row.get("checklistSection"), "sports checklist section")
        family = _text(row.get("family"), "sports checklist family")
        if section not in product.sections or family not in _FAMILIES:
            raise sources.SourceError("Unreviewed sports checklist section")
        player = _text(row.get("player"), "sports player")
        team = _text(row.get("team"), "sports team", optional=True)
        card_code = _text(row.get("cardCode"), "sports card code", 128)
        if not _CARD_CODE.fullmatch(card_code):
            raise sources.SourceError("Invalid sports card code")
        record = sources._record(
            PROVIDER, SYSTEM_CODE, language_name, native_id,
            name=player, set_id=product.slug, set_name=f"{year} {product_name}",
            card_number=card_code, source_url=DOWNLOAD_URL,
        )
        record["details"] = {
            "player": player,
            "sport": "Baseball",
            "brand": "Bowman",
            "manufacturer": "Topps",
            "variant": section,
            "source_record_id": native_id,
            "source_evidence_url": product.evidence_url,
            "source_reviewed_at": SOURCE_REVIEWED_DATE,
            "source_page": str(page),
            "source_year": str(year),
            "source_credit": SOURCE_CREDIT,
            "source_license": SOURCE_LICENSE,
            "checklist_section": section,
            "reference_scope": REFERENCE_SCOPE,
        }
        if team:
            record["details"]["team"] = team
        result.append(record)
    return sorted(result, key=lambda record: record["provider_id"])


async def fetch_sports(client: httpx.AsyncClient, descriptor: sources.SourceDescriptor) -> sources.FetchedSource:
    """One bounded, credential-free GET to the fixed reviewed JSON export.

    The public dispatcher must first enforce its source opt-in registry. The exact
    descriptor check also prevents direct calls from supplying a new target or
    raising the reviewed byte limit. Redirects/access denials are not retried.
    """
    expected = sources.SourceDescriptor(
        PROVIDER, SYSTEM_CODE, DOWNLOAD_URL, SOURCE_REVISION,
        PERMISSION_REF, "METADATA_ACCESS_DOCUMENTED", DOWNLOAD_URL, MAX_BYTES,
    )
    if descriptor != expected:
        raise sources.SourcePermissionError("Sports source descriptor does not match the reviewed export")
    sources._assert_public_client(client)
    try:
        async with asyncio.timeout(sources.TOTAL_DOWNLOAD_TIMEOUT_SECONDS):
            content = await sources._download(client, DOWNLOAD_URL, MAX_BYTES)
    except TimeoutError as exc:
        raise sources.SourceError("Sports source exceeded its total download time bound") from exc
    records = normalize_sports(sources._decode_json(content))
    if len(records) != EXPECTED_ROWS:
        raise sources.SourceError("Incomplete reviewed sports checklist export")
    digest = hashlib.sha256(content).hexdigest()
    return sources.FetchedSource(
        PROVIDER, SYSTEM_CODE, DOWNLOAD_URL, "sha256:" + digest, digest, records,
    )
