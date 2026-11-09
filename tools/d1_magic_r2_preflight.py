"""Signed, read-only MTGJSON R2 source verification ahead of any D1 writes.

This first Magic stage reads EXACT original R2 manifest and every verified
part through the Railway service's owner-free, read-only OIDC-bound route.
It recomputes immutable source and projection SHA256; touches NO D1, no
ownership, prices, Shopify, Supabase writes or R2 writes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time

import httpx
from app import r2_first_catalogue as source_codec

from d1_r2_real_shadow import (
    _oidc_token, load_verified_source, fetch_bytes, MigrationGuard,
    SOURCE_PATH,
)

EXPECTED_SCOPE = ("mtgjson", "MAGIC_THE_GATHERING", "English")
EXPECTED_ROWS = 153_679
EXPECTED_MANIFEST_SHA = "e3bda5f54affe0055ec64d7ffb943cb5cae23df8108e74f29e250f7ec63e662a"
MAX_TOTAL_BYTES = 110_000_000
MAX_PARTS = 512
SOURCE_PATH_MAGIC = SOURCE_PATH + "/magic"
REPORT = "d1-magic-r2-preflight-report.json"


def _precheck_magic_manifest(client: httpx.Client, identity: str) -> None:
    """Read one signed manifest first; diagnose counts, not printing identities.

    Changed provider scope, a revised source digest, unexpected record growth,
    excess parts/bytes or corrupt bytes must remain blocked. No R2 parts
    fetched and no Cloudflare D1 token is needed for rejected generations.
    """
    raw=fetch_bytes(client,SOURCE_PATH_MAGIC+"/manifest",identity,
                    1_000_000,source_path=SOURCE_PATH_MAGIC)
    manifest=source_codec.validate_manifest(source_codec._decode(raw))
    digest=source_codec.manifest_digest(manifest)
    if hashlib.sha256(raw).hexdigest()!=digest:
        raise MigrationGuard("Magic R2 manifest digest does not match exact source bytes")
    scope_ok=tuple(manifest[k] for k in ("provider","system_code","language"))==EXPECTED_SCOPE
    observations={
        "current_rows":manifest["record_count"],
        "approved_rows":EXPECTED_ROWS,
        "current_parts":len(manifest["parts"]),
        "parts_limit":MAX_PARTS,
        "current_source_bytes":manifest["raw_bytes"],
        "bytes_limit":MAX_TOTAL_BYTES,
        "scope_matches":scope_ok,
        "manifest_sha_matches":digest==EXPECTED_MANIFEST_SHA,
    }
    if (not scope_ok or manifest["record_count"]!=EXPECTED_ROWS
            or len(manifest["parts"])>MAX_PARTS or manifest["raw_bytes"]>MAX_TOTAL_BYTES
            or digest!=EXPECTED_MANIFEST_SHA):
        # Log only verified aggregate manifest counts and fixed booleans.
        # No IDs, card subjects, raw source, URLs or bearer tokens.
        raise MigrationGuard(
            "Magic published R2 manifest revision needs manual review: "
            +json.dumps(observations,sort_keys=True))


def audit_magic_source(*, client: httpx.Client | None = None):
    """Fail closed; never allow arbitrary scope, URL or source digest."""
    if client is None:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(25)) as http:
            return audit_magic_source(client=http)
    for attempt in range(30):
        identity = _oidc_token()
        try:
            _precheck_magic_manifest(client,identity)
            projection, manifest = load_verified_source(
                client, identity,
                source_path=SOURCE_PATH_MAGIC,
                allowed_scope=EXPECTED_SCOPE,
                min_rows=EXPECTED_ROWS,
                max_rows=EXPECTED_ROWS,
                max_parts=MAX_PARTS,
                max_bytes=MAX_TOTAL_BYTES,
            )
            break
        except MigrationGuard as exc:
            # A new Railway deploy is not necessarily live when a main-branch
            # workflow starts. Retry only its temporary 404/503. Invalid JWT,
            # wrong manifest, mismatched source digest or spoofed redirect
            # never retry or leak authentication to a different host.
            if str(exc) not in ("R2 export rejected: HTTP 404",
                                "R2 export rejected: HTTP 503") or attempt == 29:
                raise
            time.sleep(10)
    if (projection.scope != EXPECTED_SCOPE
            or projection.expected_rows != EXPECTED_ROWS
            or projection.manifest_sha != EXPECTED_MANIFEST_SHA
            or manifest["content_sha256"] != projection.source_content_sha):
        raise MigrationGuard("Magic published source is not approved immutable generation")
    return {
        "status": "MAGIC_R2_SOURCE_PREPARED_FOR_D1",
        "source_provider": EXPECTED_SCOPE[0],
        "source_system": EXPECTED_SCOPE[1],
        "source_language": EXPECTED_SCOPE[2],
        "r2_source_manifest_sha": projection.manifest_sha,
        "r2_source_content_sha": projection.source_content_sha,
        "d1_candidate_projection_sha": projection.projection_sha,
        "source_rows_verified": projection.expected_rows,
        "source_parts_verified": len(manifest["parts"]),
        "r2_source_bytes": manifest["raw_bytes"],
        "verified_d1_rows": 0,
        "d1_database_created": False,
        "d1_writes": 0,
        "production_reads_switched": False,
        "market_value_writes": 0,
        "owner_and_settlement_writes": 0,
        "supabase_writes": 0,
        "r2_writes": 0,
    }


def main() -> int:
    try:
        report = audit_magic_source()
    except (MigrationGuard, ValueError, httpx.HTTPError) as exc:
        # Never print raw credentials, request headers, object URLs or HTTP
        # provider response bodies.
        print("Magic R2 source preflight safely blocked: " + str(exc))
        return 1
    Path(REPORT).write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
