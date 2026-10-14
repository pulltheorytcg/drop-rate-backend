"""Verify a bounded, read-only history export and produce a gzip archive chunk.

The transport passphrase is a public constant for pgcrypto compression compatibility,
not a credential or archive security control. The durable archive is ordinary gzip.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

FIELDS = {
    "id", "reference_kind", "provider", "system_code", "language", "provider_id",
    "quotes", "quote_digest", "market_value_minor", "market_value_high_minor",
    "pricing_updated_at", "recorded_at",
}


def verify_export(source: Path) -> dict:
    manifest = json.loads(source.read_text())
    encrypted = base64.b64decode(manifest.pop("compressed_pgp"), validate=False)
    result = subprocess.run(
        ["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase",
         "drop-rate-archive-transport-v1", "--decrypt"],
        input=encrypted, capture_output=True, check=True,
    )
    data = result.stdout
    if hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise ValueError("Export SHA-256 does not match database bytes")
    rows = [json.loads(line) for line in data.splitlines()]
    ids = [row["id"] for row in rows]
    if len(rows) != manifest["row_count"] or len(data) != manifest["raw_bytes"]:
        raise ValueError("Export row count or size mismatch")
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("IDs are not unique")
    if manifest.get("ordering", "id") == "id" and ids != sorted(ids):
        raise ValueError("IDs are not strictly ordered")
    if min(ids) != manifest["first_id"] or max(ids) != manifest["last_id"]:
        raise ValueError("Export boundaries differ from database")
    if any(set(row) != FIELDS for row in rows):
        raise ValueError("Export schema differs from reviewed history schema")
    if any(row["reference_kind"] not in ("CARD", "SEALED") or not isinstance(row["quotes"], list) for row in rows):
        raise ValueError("Invalid history row")
    compressed = gzip.compress(data, compresslevel=9, mtime=0)
    if gzip.decompress(compressed) != data:
        raise ValueError("Gzip round-trip failed")
    target = source.with_suffix(".ndjson.gz")
    target.write_bytes(compressed)
    manifest.update(
        file_name=target.name,
        gzip_bytes=len(compressed),
        gzip_sha256=hashlib.sha256(compressed).hexdigest(),
        gzip_md5=hashlib.md5(compressed).hexdigest(),
        verified=True,
    )
    source.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("transport_json", type=Path)
    print(json.dumps(verify_export(parser.parse_args().transport_json)))
