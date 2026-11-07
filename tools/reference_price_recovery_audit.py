"""Offline classification of existing quote backups; never publishes Market Value."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

from app import reference_quote_source_backup as backup
from app.object_storage import ObjectStorageError, sha256_file

GUIDE_SOURCES = frozenset({
    "CARDMARKET_BULK_SINGLES", "TCGDEX_CARDMARKET", "TCGDEX_CARDMARKET_VARIANT",
})
MAX_MANIFEST_BYTES = 64_000


def timestamp(value):
    try:
        return backup._timestamp(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ObjectStorageError("Invalid audit timestamp") from exc


def evidence_class(quotes):
    # No source name, amount or legacy eligibility flag proves permitted sold evidence.
    if not quotes:
        return "MISSING_EVIDENCE"
    if all(isinstance(q.get("source"), str) and q["source"] in GUIDE_SOURCES for q in quotes):
        return "GUIDE_ONLY"
    return "REVIEW_REQUIRED"


def audit_archive(manifest_path: Path, archive_path: Path, *, expected_manifest_sha256: str,
                  as_of: datetime) -> dict:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ObjectStorageError("Audit time must be timezone-aware")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ObjectStorageError("Manifest exceeds limit")
    data = manifest_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_manifest_sha256:
        raise ObjectStorageError("Manifest digest differs from trusted receipt")
    try:
        manifest = json.loads(data, object_pairs_hook=backup._unique_object,
                              parse_constant=backup._reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise ObjectStorageError("Invalid manifest JSON") from exc
    name = "reference_market_prices"
    if (not isinstance(manifest, dict) or manifest.get("schema") != backup.SCHEMA
            or manifest.get("source") != f"tcg.{name}"
            or manifest.get("fields") != list(backup.TABLE_FIELDS[name])
            or manifest.get("full_table_snapshot") is not True):
        raise ObjectStorageError("Unsupported market-price archive")
    for field, maximum in (("row_count", backup.MAX_ROWS), ("raw_bytes", backup.MAX_RAW_BYTES),
                           ("gzip_bytes", backup.MAX_RAW_BYTES)):
        if type(manifest.get(field)) is not int or not 0 < manifest[field] <= maximum:
            raise ObjectStorageError("Invalid archive bounds")
    if archive_path.stat().st_size != manifest["gzip_bytes"] or sha256_file(archive_path) != (
            manifest.get("gzip_sha256"), manifest["gzip_bytes"]):
        raise ObjectStorageError("Archive bytes differ from manifest")
    counts, groups, sources = Counter(), Counter(), Counter()
    root, ndjson = hashlib.sha256(), hashlib.sha256()
    previous = None
    count = raw_size = 0
    earliest = latest = None
    try:
        with gzip.open(archive_path, "rb") as stream:
            while raw := stream.readline(backup.MAX_LINE_BYTES + 1):
                if len(raw) > backup.MAX_LINE_BYTES or not raw.endswith(b"\n"):
                    raise ObjectStorageError("Invalid archive line")
                count += 1
                raw_size += len(raw)
                if count > manifest["row_count"] or raw_size > manifest["raw_bytes"]:
                    raise ObjectStorageError("Archive exceeds declared bounds")
                line = raw[:-1]
                identity = backup.validate_row(line, name)
                if previous is not None and identity <= previous:
                    raise ObjectStorageError("Duplicate or unordered identity")
                previous = identity
                root.update(hashlib.sha256(line).hexdigest().encode("ascii"))
                ndjson.update(raw)
                row = json.loads(line)
                checked = timestamp(row["checked_at"])
                priced = timestamp(row["pricing_updated_at"]) if row["pricing_updated_at"] else None
                expiry = timestamp(row["expires_at"])
                quote_times = [timestamp(q["observed_at"]) for q in row["quotes"]
                               if q.get("observed_at") is not None]
                future = checked > as_of or (priced is not None and priced > as_of) or any(
                    t > as_of for t in quote_times)
                freshness = "TIMESTAMP_REVIEW" if future else (
                    "EXPIRED" if expiry <= as_of else "UNEXPIRED_CACHE_ONLY")
                category = evidence_class(row["quotes"])
                counts[freshness] += 1
                counts[category] += 1
                counts["STORED_AMOUNT" if row["market_value_minor"] is not None else "NO_AMOUNT"] += 1
                groups[(row["system_code"], freshness, category)] += 1
                for quote in row["quotes"]:
                    source = quote.get("source")
                    sources[source if isinstance(source, str) and source in GUIDE_SOURCES else "OTHER_REVIEW_REQUIRED"] += 1
                earliest = min(earliest, checked) if earliest else checked
                latest = max(latest, checked) if latest else checked
    except (OSError, EOFError) as exc:
        raise ObjectStorageError("Cannot decompress archive") from exc
    if (count != manifest["row_count"] or raw_size != manifest["raw_bytes"]
            or root.hexdigest() != manifest.get("content_root_sha256")
            or ndjson.hexdigest() != manifest.get("ndjson_sha256")):
        raise ObjectStorageError("Archive content proof differs")
    return {
        "schema": "drop-rate-price-recovery-audit-v1", "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "manifest_sha256": expected_manifest_sha256, "archive_sha256": manifest["gzip_sha256"],
        "ndjson_sha256": ndjson.hexdigest(), "content_root_sha256": root.hexdigest(),
        "archive_integrity": "VERIFIED", "current_sql_parity": "NOT_VERIFIED",
        "typed_restore_this_run": False, "row_count": count, "raw_bytes": raw_size,
        "checked_at_min": earliest.isoformat(), "checked_at_max": latest.isoformat(),
        "counts": dict(sorted(counts.items())), "quote_occurrences": dict(sorted(sources.items())),
        "groups": [{"system_code": s, "freshness": f, "evidence": e, "rows": n}
                   for (s, f, e), n in sorted(groups.items())],
        "eligible_market_values": 0, "requires_permitted_sold_evidence_review": count,
        "archive_retention_candidates": count, "deletion_authorized": False,
        "database_mutations": 0, "provider_requests": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--as-of", required=True, help="Explicit timezone-aware evaluation timestamp")
    args = parser.parse_args()
    try:
        result = audit_archive(args.manifest, args.archive,
                               expected_manifest_sha256=args.manifest_sha256,
                               as_of=timestamp(args.as_of))
    except (ObjectStorageError, OSError) as exc:
        parser.exit(1, f"Recovery audit refused: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
