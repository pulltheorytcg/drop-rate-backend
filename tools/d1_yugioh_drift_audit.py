"""Read-only, bounded diagnosis of Yu-Gi-Oh R2 source vs retained D1 rows.

Never stage, mutate, relabel or activate a D1 generation. The only output is
aggregate changed-field counts; no actual card identifiers, auth secrets,
private owner records, store prices or monetary data enter the report.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import sys

import httpx

from app import d1_shadow_catalogue as codec
from d1_remote_catalogue_pilot import D1Client, PilotError
from d1_r2_real_shadow import _oidc_token, load_verified_source, _query, MigrationGuard
from d1_yugioh_shadow import (
    SCOPE, SOURCE_PATH_YUGIOH, EXACT_DATABASE_NAME, EXPECTED_RECORDS,
    MAX_ROWS, MAX_SOURCE_PARTS, MAX_SOURCE_BYTES, D1_READBACK_SQL,
    _stable_source_projection,
)

ACCOUNT = "e4d4b363540e991048d2e1812d5ef53e"
IDENTITY_FIELDS = frozenset({
    "card_key", "provider", "system_code", "language", "provider_id",
    "product_type", "set_id", "card_number", "finish", "cardmarket_product_id",
})
METADATA_FIELDS = frozenset(codec.SQLITE_COLUMNS) - IDENTITY_FIELDS - {"manifest_sha"}
REPORT_FILE = "d1-yugioh-source-drift-audit.json"
DB_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def audit(account: str, token: str, *, http: httpx.Client | None = None):
    if account != ACCOUNT:
        raise MigrationGuard("Wrong account for protected read-only Yu-Gi-Oh source audit")
    if http is None:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(25)) as client:
            return audit(account, token, http=client)
    source, _manifest = load_verified_source(
        http, _oidc_token(), source_path=SOURCE_PATH_YUGIOH,
        allowed_scope=SCOPE, min_rows=EXPECTED_RECORDS, max_rows=MAX_ROWS,
        max_parts=MAX_SOURCE_PARTS, max_bytes=MAX_SOURCE_BYTES,
    )
    if source.scope != SCOPE or not EXPECTED_RECORDS <= source.expected_rows <= MAX_ROWS:
        raise MigrationGuard("Unexpected Yu-Gi-Oh source scope or record count")
    source = _stable_source_projection(source)
    wanted = {record[1]: record for record in source.rows}
    if len(wanted) != source.expected_rows:
        raise MigrationGuard("Unverified or duplicate current R2 source identities")

    cloud = D1Client(account, token)
    visible = cloud.list_databases()
    if not isinstance(visible, list) or len(visible) > 10:
        raise MigrationGuard("Unexpected Cloudflare D1 database inventory")
    records = [db for db in visible if db.get("name") == EXACT_DATABASE_NAME]
    if len(records) != 1:
        raise MigrationGuard("Missing or ambiguous retained Yu-Gi-Oh D1 database")
    uid = records[0].get("uuid")
    if not isinstance(uid, str) or not DB_UUID.fullmatch(uid):
        raise MigrationGuard("Invalid protected D1 database identity")

    generations = _query(cloud, uid,
        "select manifest_sha,provider,system_code,language,expected_rows "
        "from shadow_generations")
    if len(generations) != 1:
        raise MigrationGuard("Only a single existing retained generation may be audited")
    old = generations[0]
    if (not isinstance(old.get("manifest_sha"),str)
            or not DIGEST.fullmatch(old["manifest_sha"])
            or tuple(old.get(k) for k in ("provider","system_code","language")) != SCOPE
            or type(old.get("expected_rows")) is not int
            or not EXPECTED_RECORDS <= old["expected_rows"] <= source.expected_rows):
        raise MigrationGuard("Retained Yu-Gi-Oh generation metadata invalid")
    old_sha = old["manifest_sha"]
    counts = _query(cloud, uid,
        "select count(*) as n from shadow_cards where manifest_sha=?", (old_sha,))
    if len(counts) != 1 or type(counts[0].get("n")) is not int:
        raise MigrationGuard("Retained D1 staged count missing")
    staged = counts[0]["n"]
    if not 0 <= staged <= old["expected_rows"]:
        raise MigrationGuard("Retained D1 staged count outside old generation")

    by_field = Counter()
    changed_records = 0
    identity_changed_records = 0
    metadata_only_records = 0
    missing_old_keys = 0
    unchanged_records = 0
    seen = set()
    for offset in range(0, staged, 100):
        batch_size = min(100, staged-offset)
        rows = _query(cloud, uid, D1_READBACK_SQL, (old_sha, batch_size, offset))
        if len(rows) != batch_size:
            raise MigrationGuard("Retained D1 readback page incomplete")
        for row in rows:
            if (not isinstance(row,dict) or set(row) != set(codec.SQLITE_COLUMNS)
                    or row.get("manifest_sha") != old_sha):
                raise MigrationGuard("Retained D1 row malformed")
            key = row.get("card_key")
            if not isinstance(key, str) or not key or key in seen:
                raise MigrationGuard("Duplicate/missing D1 stable printing identity")
            seen.add(key)
            current = wanted.get(key)
            if current is None:
                missing_old_keys += 1
                continue
            fields = {column for i,column in enumerate(codec.SQLITE_COLUMNS)
                      if column != "manifest_sha" and row[column] != current[i]}
            if not fields:
                unchanged_records += 1
                continue
            if not fields <= IDENTITY_FIELDS | METADATA_FIELDS:
                raise MigrationGuard("Unclassified Yu-Gi-Oh projection field")
            by_field.update(fields)
            changed_records += 1
            if fields & IDENTITY_FIELDS:
                identity_changed_records += 1
            else:
                metadata_only_records += 1
    if len(seen) != staged:
        raise MigrationGuard("Unaccounted D1 retained rows")

    return {
        "status": "YU_GI_OH_SOURCE_DRIFT_READ_ONLY",
        "old_source_rows": old["expected_rows"],
        "current_r2_source_rows": source.expected_rows,
        "existing_d1_staged_rows": staged,
        "unchanged_records": unchanged_records,
        "changed_records": changed_records,
        "identity_changed_records": identity_changed_records,
        "metadata_only_records": metadata_only_records,
        "missing_old_keys": missing_old_keys,
        "changed_fields": dict(sorted(by_field.items())),
        "automatic_identity_reuse_permitted": (
            identity_changed_records == 0 and missing_old_keys == 0
        ),
        "source_d1_rows_written": 0,
        "catalogue_reads_switched": False,
        "owner_or_settlement_writes": 0,
        "supabase_writes": 0,
    }


def main() -> int:
    try:
        result = audit(
            os.environ.get("CLOUDFLARE_ACCOUNT_ID",""),
            os.environ.get("CLOUDFARE_D1_PILOT_TOKEN",""),
        )
    except (MigrationGuard, PilotError, httpx.HTTPError, ValueError) as exc:
        print("Read-only Yu-Gi-Oh source drift audit failed safely: " + str(exc),file=sys.stderr)
        return 1
    Path(REPORT_FILE).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
