"""Display-only community covers for unchanged, imported Open Library editions.

The source's current edition cover is not proof of a physical copy or publisher
approval. These URLs are embedded directly by the browser; never fetch, mirror,
fingerprint, approve, or publish them through the canonical media pipeline.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .comic_identity import ComicPrintingCreate


KIND = "OPEN_LIBRARY_EDITION_REFERENCE"
METADATA_LICENSE = "https://openlibrary.org/developers/licensing"


def _object(value):
    value = json.loads(value) if isinstance(value, str) else value
    return value if isinstance(value, dict) else {}


@lru_cache(maxsize=1)
def _excluded_editions():
    data = json.loads((Path(__file__).parent / "data/book_community_cover_exclusions.json").read_text())
    if data.get("version") != "book-community-cover-exclusions-v1":
        raise ValueError("Invalid community cover exclusions")
    records = data["records"]
    if not isinstance(records, list) or len(records) > 5000:
        raise ValueError("Invalid community cover exclusions")
    excluded = set()
    for row in records:
        edition_id = row["edition_id"]
        if (not re.fullmatch(r"OL[1-9][0-9]*M", edition_id)
                or row["source_url"] != "https://openlibrary.org/books/" + edition_id
                or not row.get("reason") or not row.get("review_note")):
            raise ValueError("Invalid community cover exclusion")
        excluded.add(edition_id)
    return frozenset(excluded)


def eligible_import(book):
    """Cheap prefilter; the complete hash and mapping check happens below."""
    try:
        attrs = _object(book.get("attributes"))
        receipt = attrs.get("catalogue_import")
        return (book.get("identity_status") == "STRUCTURED"
                and book.get("profile_status") == "STRUCTURED"
                and attrs.get("identity_source") == "OPEN_LIBRARY_CATALOGUE"
                and isinstance(receipt, dict)
                and receipt.get("version") == "book-bulk-v1"
                and receipt.get("provider") == "OPEN_LIBRARY"
                and receipt.get("metadata_license") == METADATA_LICENSE
                and bool(re.fullmatch(r"[a-f0-9]{64}", str(receipt.get("record_digest", ""))))
                and attrs.get("cover_rights_status") not in {"REVOKED", "REJECTED"}
                and attrs.get("cover_source_status") not in {"REVOKED", "INACTIVE"})
    except (ValueError, TypeError):
        return False


def community_cover_reference(row):
    """Bind a public OLID lookup to the exact immutable metadata import.

Rebuild the original import digest from today's canonical edition and product.
Matching-looking receipt fields alone cannot authorize a changed ISBN, title,
language, binding, source, release date, or printing. An OLID still cannot
guarantee the source's attached image is correct: keep the reference label.
"""
    if not eligible_import(row):
        return None
    try:
        # Lazy imports avoid the catalogue/recognition adapter import cycle.
        from .book_catalogue_sources import _normalise_adapted
        from .book_openlibrary_bulk import reviewed_hold_registry, reviewed_identity_hold

        attrs = _object(row.get("attributes"))
        receipt = attrs["catalogue_import"]
        mapping = _object(row.get("mapping_metadata"))
        edition_id = receipt.get("record_id")
        if not isinstance(edition_id, str) or not re.fullmatch(r"OL[1-9][0-9]*M", edition_id):
            return None
        source = "https://openlibrary.org/books/" + edition_id
        if (edition_id in _excluded_editions()
                or attrs.get("source_url") != source
                or row.get("mapping_provider_id") != edition_id
                or row.get("mapping_source_reference") != source
                or row.get("mapping_status") not in {"REVIEW", "VERIFIED"}
                or row.get("mapping_verification_basis") != "DETERMINISTIC_EXACT"
                or mapping.get("import_version") != "book-bulk-v1"
                or mapping.get("metadata_license") != METADATA_LICENSE):
            return None
        fields = {key: row.get(key) for key in ComicPrintingCreate.model_fields}
        fields.update(publisher=attrs.get("publisher"), book_format=attrs.get("book_format"))
        released = row.get("profile_release_date")
        entry = _normalise_adapted(dict(
            provider="OPEN_LIBRARY", record_id=edition_id, book=fields,
            language=row["language"], source_url=source,
            release_date=released.isoformat() if hasattr(released, "isoformat") else released,
            observed_on=attrs.get("source_checked_at"), image_url=None,
            evidence_url=receipt.get("source_snapshot")))
        if (entry["record_digest"] != receipt["record_digest"]
                or entry["record_digest"] != mapping.get("record_digest")
                or entry["identity_key"] != mapping.get("identity_key")
                or entry["identity_key"] != row.get("identity_key")
                or entry["catalogue"] != _object(row.get("catalogue_product"))):
            return None
        reviewed, _ = reviewed_hold_registry()
        if reviewed_identity_hold(isbn=entry["book"]["barcode_gtin"], source_id=edition_id, reviewed=reviewed):
            return None
        base = "https://covers.openlibrary.org/b/olid/" + edition_id
        return dict(kind=KIND, provider="OPEN_LIBRARY", edition_id=edition_id,
                    language=entry["catalogue"]["language"],
                    image_url=base + "-M.jpg?default=false",
                    detail_image_url=base + "-M.jpg?default=false",
                    source_url=source, scope="COMMUNITY_EDITION", status="REFERENCE_ONLY")
    except (ValueError, TypeError, KeyError, OSError):
        # Incomplete/stale provenance or review data leaves the placeholder.
        return None


async def community_book_covers(connection, catalogue_ids):
    """One bounded, read-only query over the requested page's exact IDs."""
    if not catalogue_ids:
        return {}
    rows = await connection.fetch("""select b.*,p.language,p.identity_key,
          to_jsonb(p)-array['id','identity_key','created_at'] as catalogue_product,
          pr.identity_status as profile_status,pr.release_date as profile_release_date,
          m.provider_id as mapping_provider_id,m.source_reference as mapping_source_reference,
          m.match_status as mapping_status,m.verification_basis as mapping_verification_basis,
          m.metadata as mapping_metadata
        from tcg.catalogue_products p
        join tcg.comic_printing_details b on b.catalogue_id=p.id
        join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
          and pr.system_code=b.system_code and pr.collectible_type='COMIC'
        join tcg.provider_catalogue_mappings m on m.catalogue_id=p.id
          and m.system_code=b.system_code and m.source_provider='OPEN_LIBRARY'
          and m.provider_entity_type='COMIC_PRINTING'
          and m.provider_variant_key='' and m.provider_language=''
        where p.id=any($1::uuid[]) and p.product_type='COMIC'
          and b.identity_status='STRUCTURED' and pr.identity_status='STRUCTURED'
          and b.attributes->>'identity_source'='OPEN_LIBRARY_CATALOGUE'""", list(set(catalogue_ids)))
    candidates = {}
    for row in rows:
        cover = community_cover_reference(dict(row))
        if cover:
            candidates.setdefault(str(row["catalogue_id"]), []).append(cover)
    # Ambiguous provider mappings must not pick an arbitrary image.
    return {key: covers[0] for key, covers in candidates.items() if len(covers) == 1}
