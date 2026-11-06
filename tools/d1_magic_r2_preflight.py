"""Signed, read-only MTGJSON R2 source verification ahead of any D1 writes.

This first Magic stage reads EXACT original R2 manifest and every verified
part through the Railway service's owner-free, read-only OIDC-bound route.
It recomputes immutable source and projection SHA256; touches NO D1, no
ownership, prices, Shopify, Supabase writes or R2 writes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import httpx

from d1_r2_real_shadow import (
    _oidc_token, load_verified_source, MigrationGuard,
    SOURCE_PATH,
)

EXPECTED_SCOPE = ("mtgjson", "MAGIC_THE_GATHERING", "English")
EXPECTED_ROWS = 153_662
EXPECTED_MANIFEST_SHA = "be5af5e84d3a10bcac32a996f0dc8779fdf33c95fac89669381a8bbd32fcad28"
MAX_TOTAL_BYTES = 110_000_000
MAX_PARTS = 512
SOURCE_PATH_MAGIC = SOURCE_PATH + "/magic"
REPORT = "d1-magic-r2-preflight-report.json"


def audit_magic_source(*, client: httpx.Client | None = None):
    """Fail closed; never allow arbitrary scope, URL or source digest."""
    if client is None:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(25)) as http:
            return audit_magic_source(client=http)
    for attempt in range(30):
        identity = _oidc_token()
        try:
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
