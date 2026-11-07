"""Verify the complete legacy R2 shared catalogue before D1 migration.

Five immutable owner-free relations:
  reference_cards, reference_sets, reference_sealed_products,
  catalogue_products, catalogue_product_profiles

No Postgres DML, D1 API token, owner/settlement records, Shopify writes,
retail prices or traffic cutover. Original source generation is pinned.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time

import httpx

from app import catalogue_r2_live as legacy
from d1_r2_real_shadow import _oidc_token, fetch_bytes, MigrationGuard, SOURCE_PATH

SOURCE_PATH_LEGACY = SOURCE_PATH + "/legacy"
EXPECTED_GENERATION = 122500
EXPECTED_COUNTS = {
    "reference_cards": 69697,
    "reference_sets": 1472,
    "reference_sealed_products": 3893,
    "catalogue_products": 2062,
    "catalogue_product_profiles": 2062,
}
EXPECTED_RAW_BYTES = 29_831_680
EXPECTED_PARTS = 161
MAX_MANIFEST_BYTES = 120_000
REPORT = "d1-legacy-r2-source-preflight-report.json"


def _fetch(client: httpx.Client, path: str, identity: str, limit: int) -> bytes:
    return fetch_bytes(client, path, identity, limit, source_path=SOURCE_PATH_LEGACY)


def audit_legacy_source(*, client: httpx.Client | None = None):
    if client is None:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(25)) as http:
            return audit_legacy_source(client=http)
    for attempt in range(30):
        oidc = _oidc_token()
        try:
            raw_manifest = _fetch(
                client, SOURCE_PATH_LEGACY + "/manifest", oidc,
                MAX_MANIFEST_BYTES,
            )
            break
        except MigrationGuard as exc:
            if str(exc) not in ("R2 export rejected: HTTP 404",
                                "R2 export rejected: HTTP 503") or attempt == 29:
                raise
            time.sleep(10)
    try:
        manifest = legacy.validate_manifest(
            json.loads(raw_manifest), EXPECTED_GENERATION,
        )
    except (TypeError, ValueError, legacy.ObjectStorageError) as exc:
        raise MigrationGuard("Legacy R2 manifest failed structural verification") from exc
    if (manifest["counts"] != EXPECTED_COUNTS
            or manifest["raw_bytes"] != EXPECTED_RAW_BYTES
            or len(manifest["parts"]) != EXPECTED_PARTS):
        raise MigrationGuard("Legacy R2 published source changed; human review required")

    raws = []
    for index, part in enumerate(manifest["parts"]):
        raw = _fetch(client, f"{SOURCE_PATH_LEGACY}/part/{index}", oidc, 4_000_000)
        try:
            legacy.parse_part(
                raw, part["relation"], part["sha256"],
                part["raw_bytes"], part["rows"],
            )
        except (ValueError, TypeError, legacy.ObjectStorageError) as exc:
            raise MigrationGuard("Legacy R2 part failed content integrity") from exc
        raws.append(raw)
    try:
        snapshot = legacy.assemble(manifest, raws)
    except (ValueError, TypeError, legacy.ObjectStorageError) as exc:
        raise MigrationGuard("Legacy R2 full source identities did not assemble") from exc

    by_relation = {}
    for relation, source in snapshot.rows.items():
        digest = hashlib.sha256()
        for row in source:
            digest.update(json.dumps(
                row, sort_keys=True, ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n")
        by_relation[relation] = {
            "rows": len(source),
            "source_sha256": digest.hexdigest(),
        }
    if {name: val["rows"] for name, val in by_relation.items()} != EXPECTED_COUNTS:
        raise MigrationGuard("Legacy R2 reconstructed relation totals differ")
    return {
        "status": "LEGACY_R2_SOURCE_PREPARED_FOR_D1",
        "schema": manifest["schema"],
        "generation": manifest["generation"],
        "r2_manifest_sha256": legacy.manifest_digest(manifest),
        "r2_source_bytes": manifest["raw_bytes"],
        "r2_parts_verified": len(raws),
        "verified_relations": by_relation,
        "source_rows_verified": sum(v["rows"] for v in by_relation.values()),
        "verified_d1_rows": 0,
        "d1_database_created": False,
        "d1_writes": 0,
        "supabase_writes": 0,
        "r2_writes": 0,
        "production_reads_switched": False,
        "market_value_writes": 0,
        "owner_and_settlement_writes": 0,
    }


def main() -> int:
    try:
        report = audit_legacy_source()
    except (MigrationGuard, ValueError, TypeError, httpx.HTTPError) as exc:
        print("Legacy R2 catalogue source preflight safely blocked: "
              + str(exc))
        return 1
    Path(REPORT).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
