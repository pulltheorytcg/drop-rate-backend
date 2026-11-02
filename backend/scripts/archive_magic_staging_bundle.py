"""Validate and optionally archive the reviewed Foundations (FDN) MTGJSON bundle.

The GitHub read-only source workflow emits one immutable, closed-schema file for
each 100-card source window and an input index. This tool requires the complete
verified set before it will make any network call. By default it only validates
the extracted artifact directory; an operator must explicitly pass --apply and
enable TCG_MAGIC_METADATA_R2_ARCHIVE_ENABLED=true in an R2-configured runtime.

All uploads are PRIVATE, immutable reference-input archives. No public feed,
Postgres row, Shopify product, image or market value is created.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.collectible_source_adapters import ReferenceSourceError
from app.object_storage import ObjectStorageConfig, ObjectStorageError, S3ObjectStorage
from scripts.pilot_expanded_catalogues import (
    archive_magic_private_snapshot, validate_magic_closed_snapshot,
)


INDEX_NAME = "magic-fdn-private-r2-input-index.json"
SET_CODE = "FDN"
SOURCE_URL = "https://mtgjson.com/api/v5/FDN.json"
SOURCE_ROWS = 771
PRINTING_REFS = 1179
WINDOW_OFFSETS = tuple(range(0, 800, 100))
MAX_INDEX_BYTES = 100_000
MAX_PART_BYTES = 2_000_000
INDEX_FIELDS = {
    "kind", "schema_version", "set_code", "provider", "license_url",
    "source_rows_examined", "validated_printing_refs", "quarantined_source_rows",
    "private", "r2_objects_uploaded", "supabase_rows_written",
    "shopify_products_created", "windows",
}
WINDOW_FIELDS = {
    "offset", "source_rows_examined", "validated_printings",
    "quarantined_source_rows", "artifact",
}
ARTIFACT_FIELDS = {
    "file_name", "sha256", "bytes", "private", "format", "r2_uploaded",
}


@dataclass(frozen=True)
class ValidatedPart:
    offset: int
    sha256: str
    payload: bytes


@dataclass(frozen=True)
class ValidatedBundle:
    index_sha256: str
    parts: tuple[ValidatedPart, ...]
    raw_bytes: int


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ReferenceSourceError("Duplicate JSON key in Magic staging bundle")
        obj[key] = value
    return obj


def _json_bytes(payload: bytes) -> dict:
    try:
        result = json.loads(payload, object_pairs_hook=_reject_duplicates)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ReferenceSourceError("Invalid JSON in Magic staging bundle") from exc
    if type(result) is not dict:
        raise ReferenceSourceError("Magic staging document must be an object")
    return result


def _closed_fields(record: object, fields: set[str], context: str) -> dict:
    if type(record) is not dict or set(record) != fields:
        raise ReferenceSourceError(f"Unreviewed {context} fields in Magic staging bundle")
    return record


def _bounded_file(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ReferenceSourceError("Magic staging bundle file missing or symbolic link")
    if not 0 < path.stat().st_size <= limit:
        raise ReferenceSourceError("Magic staging bundle file exceeds byte bound")
    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    if not 0 < len(payload) <= limit:
        raise ReferenceSourceError("Magic staging bundle file exceeded read bound")
    return payload


def _canonical_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def validate_bundle(directory: Path) -> ValidatedBundle:
    """Preflight *all* local inputs; no remote read/write or credentials accessed."""
    index_raw = _bounded_file(directory / INDEX_NAME, MAX_INDEX_BYTES)
    index = _closed_fields(_json_bytes(index_raw), INDEX_FIELDS, "index")
    if (index["kind"] != "PRIVATE_MTGJSON_R2_INPUT_BUNDLE_NOT_UPLOADED"
            or type(index["schema_version"]) is not int or index["schema_version"] != 1
            or index["set_code"] != SET_CODE or index["provider"] != "MTGJSON"
            or index["license_url"] != "https://www.mtgjson.com/license/"
            or type(index["source_rows_examined"]) is not int
            or index["source_rows_examined"] != SOURCE_ROWS
            or type(index["validated_printing_refs"]) is not int
            or index["validated_printing_refs"] != PRINTING_REFS
            or type(index["quarantined_source_rows"]) is not int
            or index["quarantined_source_rows"] != 0
            or index["private"] is not True
            or type(index["r2_objects_uploaded"]) is not int
            or index["r2_objects_uploaded"] != 0
            or type(index["supabase_rows_written"]) is not int
            or index["supabase_rows_written"] != 0
            or type(index["shopify_products_created"]) is not int
            or index["shopify_products_created"] != 0
            or type(index["windows"]) is not list
            or len(index["windows"]) != len(WINDOW_OFFSETS)):
        raise ReferenceSourceError("Magic FDN bundle identity or zero-write gate changed")

    parts = []
    identities = set()
    source_rows_count = 0
    printing_count = 0
    total_bytes = 0
    for expected_offset, candidate in zip(WINDOW_OFFSETS, index["windows"]):
        window = _closed_fields(candidate, WINDOW_FIELDS, "window")
        source_count = min(100, SOURCE_ROWS - expected_offset)
        if (type(window["offset"]) is not int or window["offset"] != expected_offset
                or type(window["source_rows_examined"]) is not int
                or window["source_rows_examined"] != source_count
                or type(window["validated_printings"]) is not int
                or not 1 <= window["validated_printings"] <= 800
                or type(window["quarantined_source_rows"]) is not int
                or window["quarantined_source_rows"] != 0):
            raise ReferenceSourceError("Magic FDN window count, order or quarantine changed")
        artifact = _closed_fields(window["artifact"], ARTIFACT_FIELDS, "artifact")
        digest = artifact["sha256"]
        if (type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or artifact["private"] is not True or artifact["r2_uploaded"] is not False
                or artifact["format"] != "CLOSED_MTGJSON_METADATA_V1"
                or type(artifact["bytes"]) is not int
                or not 0 < artifact["bytes"] <= MAX_PART_BYTES):
            raise ReferenceSourceError("Magic artifact identity or private boundary changed")
        expected_filename = f"mtgjson-FDN-{expected_offset}-100-{digest[:16]}.json"
        if artifact["file_name"] != expected_filename:
            raise ReferenceSourceError("Magic artifact filename does not match trusted identity")
        raw = _bounded_file(directory / expected_filename, MAX_PART_BYTES)
        if len(raw) != artifact["bytes"] or hashlib.sha256(raw).hexdigest() != digest:
            raise ReferenceSourceError("Magic artifact byte count or SHA-256 mismatch")
        _json_bytes(raw)  # Also rejects shadowing duplicate keys in otherwise valid JSON.
        validate_magic_closed_snapshot(raw)
        records = json.loads(raw)["records"]
        if len(records) != window["validated_printings"]:
            raise ReferenceSourceError("Magic artifact printing count mismatch")
        for row in records:
            set_data, card = row["set"], row["card"]
            evidence = card["evidence"]
            finish = card["finish"]
            printing_id = card["provider_id"]
            if (set_data["set_id"] != SET_CODE
                    or set_data["language"] != "English"
                    or set_data["source_url"] != SOURCE_URL
                    or card["source_url"] != SOURCE_URL
                    or evidence["set_code"] != SET_CODE
                    or evidence["artwork_status"] != "UNVERIFIED_EXACT_PRINTING"
                    or evidence["market_value_status"] != "NO_VERIFIED_SOLD_EVIDENCE"
                    or type(finish) is not str
                    or not re.fullmatch(r"[a-z][a-z0-9_-]{1,35}", finish)
                    or evidence["finish"] != finish
                    or not _canonical_uuid(evidence["provider_local_id"])
                    or printing_id != f"{evidence['provider_local_id']}:{finish}"
                    or (evidence["scryfall_id"] is not None
                        and not _canonical_uuid(evidence["scryfall_id"]))):
                raise ReferenceSourceError("Magic printing source, set or finish identity mismatch")
            if printing_id in identities:
                raise ReferenceSourceError("Duplicate Magic printing across source windows")
            identities.add(printing_id)
        parts.append(ValidatedPart(expected_offset, digest, raw))
        source_rows_count += source_count
        printing_count += len(records)
        total_bytes += len(raw)
    if source_rows_count != SOURCE_ROWS or printing_count != PRINTING_REFS:
        raise ReferenceSourceError("Magic bundle did not cover the reviewed FDN source")
    return ValidatedBundle(hashlib.sha256(index_raw).hexdigest(), tuple(parts), total_bytes)


async def archive_bundle(directory: Path, *, apply: bool = False,
                         storage: S3ObjectStorage | None = None) -> dict:
    """Dry-run by default; --apply privately uploads all parts then a final index."""
    bundle = validate_bundle(directory)
    common = {"set_code": SET_CODE, "source_rows_examined": SOURCE_ROWS,
              "validated_printing_refs": PRINTING_REFS,
              "validated_windows": len(bundle.parts), "raw_bytes": bundle.raw_bytes,
              "source_index_sha256": bundle.index_sha256, "private": True,
              "supabase_rows_written": 0, "shopify_products_created": 0,
              "images_mirrored": 0, "verified_market_prices": 0}
    if not apply:
        return {**common, "status": "DRY_RUN_VERIFIED", "r2_objects_uploaded": 0}
    if os.getenv("TCG_MAGIC_METADATA_R2_ARCHIVE_ENABLED", "false").lower() != "true":
        raise RuntimeError("Private Magic R2 archive is disabled; no objects uploaded")
    if storage is None:
        config = ObjectStorageConfig.from_env()
        if config is None:
            raise RuntimeError("R2 archive requested without configured private object storage")
        storage = S3ObjectStorage(config)

    remote_parts = []
    for part in bundle.parts:
        receipt = await archive_magic_private_snapshot(storage, part.payload)
        if receipt["sha256"] != part.sha256 or receipt["public"] is not False:
            raise ObjectStorageError("Private Magic archive receipt identity mismatch")
        remote_parts.append({"offset": part.offset, "sha256": part.sha256,
                             "key": receipt["key"],
                             "compressed_bytes": receipt["compressed_bytes"]})

    # Uploaded LAST. An interrupted transfer may leave immutable PRIVATE parts,
    # but never a completed bundle marker and never a live DB/public pointer.
    output_index = {
        "kind": "PRIVATE_MTGJSON_R2_VERIFIED_BUNDLE_V1", "schema_version": 1,
        "set_code": SET_CODE, "provider": "MTGJSON",
        "license_url": "https://www.mtgjson.com/license/",
        "source_index_sha256": bundle.index_sha256,
        "source_rows_examined": SOURCE_ROWS,
        "validated_printing_refs": PRINTING_REFS,
        "parts": remote_parts, "private": True, "public_feed_published": False,
        "supabase_rows_written": 0, "shopify_products_created": 0,
    }
    output_raw = json.dumps(output_index, sort_keys=True, separators=(",", ":")).encode()
    final_receipt = await asyncio.to_thread(storage.put_verified_reference_snapshot, output_raw)
    if (final_receipt.get("verified") is not True
            or final_receipt.get("sha256") != hashlib.sha256(output_raw).hexdigest()
            or await asyncio.to_thread(
                storage.read_verified_reference_snapshot, final_receipt["sha256"])
            != output_raw):
        raise ObjectStorageError("Magic bundle index failed private R2 readback")
    return {**common, "status": "PRIVATE_R2_ARCHIVED",
            "r2_objects_uploaded": len(bundle.parts) + 1,
            "private_r2_index_sha256": final_receipt["sha256"],
            "private_r2_index_key": final_receipt["key"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True,
                        help="Extracted trusted GitHub artifact directory containing FDN input index")
    parser.add_argument("--apply", action="store_true",
                        help="Explicit private R2 upload (requires separate enabled environment flag)")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(archive_bundle(args.directory, apply=args.apply)),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
