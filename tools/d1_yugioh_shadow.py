"""Resumable, strictly source-scoped REAL Yu-Gi-Oh! R2 -> isolated D1 shadow.

Trusted GitHub main push or schedule; each run budgets only 8,000 new reference
rows, well below the D1 Free daily row-write limit even with index fanout.
D1 staging is NOT storefront publication. Never access money, owners or prices.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import httpx

from app import d1_shadow_catalogue as codec
from d1_remote_catalogue_pilot import D1Client, PilotError
from d1_r2_real_shadow import (
    API_ORIGIN, SOURCE_PATH, _oidc_token, _query, _schema,
    load_verified_source, verify_d1_projection, MigrationGuard,
)

SCOPE = ("ygoprodeck", "YUGIOH", "English")
SOURCE_PATH_YUGIOH = SOURCE_PATH + "/yugioh"
EXACT_DATABASE_NAME = "drop-rate-d1-real-yugioh-shadow"
EXPECTED_RECORDS = 45_418
MAX_ROWS = 50_000
MAX_SOURCE_BYTES = 30_000_000
MAX_SOURCE_PARTS = 128
DAILY_NEW_ROWS = 8_000
MAX_D1_DATABASES = 9
REPORT_FILE = "d1-yugioh-real-shadow-report.json"

BUDGET_SCHEMA = """create table if not exists shadow_daily_write_budget(
    utc_day text primary key,
    manifest_sha text not null references shadow_generations(manifest_sha),
    run_id text not null,
    rows_limit integer not null check(rows_limit between 0 and 8000)
)"""

BUDGET_INSERT = """insert into shadow_daily_write_budget(
    utc_day,manifest_sha,run_id,rows_limit) values(?,?,?,?)"""

D1_READBACK_SQL = ("select " + ",".join(codec.SQLITE_COLUMNS) +
    " from shadow_cards where manifest_sha=? order by card_key limit ? offset ?")


def _stable_source_projection(source: codec.Projection) -> codec.Projection:
    """D1 readback is card_key ordered. Catalogue browse is name ordered.

    Hash the SAME sorted tuple sequence that D1 later returns; never rely
    on search pagination's default sort for integrity or day-to-day resume.
    """
    ordered = tuple(sorted(source.rows, key=lambda item: item[1]))
    if len(ordered) != source.expected_rows or len({r[1] for r in ordered}) != len(ordered):
        raise MigrationGuard("R2 projection rows are not unique and complete")
    digest = hashlib.sha256()
    for item in ordered:
        digest.update(json.dumps(item,ensure_ascii=False,
            separators=(",",":")).encode("utf-8")+bytes((10,)))
    return replace(source,rows=ordered,projection_sha=digest.hexdigest())


def _database(client: D1Client):
    databases = client.list_databases()
    if not isinstance(databases, list) or len(databases) > MAX_D1_DATABASES:
        raise MigrationGuard("D1 account database budget guard; no writes")
    matched = [db for db in databases if db.get("name") == EXACT_DATABASE_NAME]
    if len(matched) > 1:
        raise MigrationGuard("Ambiguous D1 source database; no writes")
    if matched:
        uid = matched[0].get("uuid")
    else:
        result, _ = client.call("POST", client.path, {"name": EXACT_DATABASE_NAME})
        if not isinstance(result, dict) or result.get("name") != EXACT_DATABASE_NAME:
            raise MigrationGuard("Cloudflare did not create exact bounded Yu-Gi-Oh shadow")
        uid = result.get("uuid")
    if (not isinstance(uid, str) or not
            re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", uid)):
        raise MigrationGuard("Invalid D1 UUID")
    return uid


def _existing_generation(cloud: D1Client, dbid: str, source: codec.Projection):
    rows = _query(cloud, dbid,
                  """select manifest_sha,provider,system_code,language,expected_rows,
                            projection_sha,source_content_sha,source_revision
                     from shadow_generations""")
    if len(rows) > 1:
        raise MigrationGuard("Multiple shadow generations need manual migration review")
    expected = (
        source.manifest_sha, *source.scope, source.expected_rows,
        source.projection_sha, source.source_content_sha, source.source_revision,
    )
    if rows:
        found = rows[0]
        actual = tuple(found[k] for k in (
            "manifest_sha","provider","system_code","language","expected_rows",
            "projection_sha","source_content_sha","source_revision"))
        if actual != expected:
            raise MigrationGuard("Existing D1 generation differs from immutable R2 source")
    else:
        statement = codec.generation_statement(source)
        _query(cloud, dbid, statement["sql"], statement["params"])


def _verify_staged_prefix(cloud: D1Client, dbid: str, source: codec.Projection):
    counts = _query(cloud, dbid,
                    "select count(*) as n from shadow_cards where manifest_sha=?",
                    (source.manifest_sha,))
    if len(counts) != 1 or type(counts[0].get("n")) is not int:
        raise MigrationGuard("Unknown current D1 source row count")
    count = counts[0]["n"]
    if not 0 <= count <= source.expected_rows:
        raise MigrationGuard("D1 staged row count outside original source")
    offset = 0
    while offset < count:
        rows = _query(cloud, dbid, D1_READBACK_SQL,
                      (source.manifest_sha, min(100,count-offset), offset))
        if len(rows) != min(100,count-offset):
            raise MigrationGuard("Missing staged source row")
        for i, row in enumerate(rows):
            if (not isinstance(row, dict) or set(row) != set(codec.SQLITE_COLUMNS)
                    or tuple(row[k] for k in codec.SQLITE_COLUMNS)
                       != source.rows[offset+i]):
                raise MigrationGuard("D1 staged prefix does not match R2 source")
        offset += len(rows)
    return count


def _daily_receipt(cloud: D1Client, dbid: str, today: str):
    rows = _query(cloud, dbid,
                  "select utc_day,manifest_sha,run_id,rows_limit "
                  "from shadow_daily_write_budget where utc_day=?", (today,))
    if len(rows) > 1:
        raise MigrationGuard("Duplicate daily D1 quota receipt")
    return rows[0] if rows else None


def run(account: str, token: str, run_id: str, run_attempt: str, *,
        client: httpx.Client | None = None, now: datetime | None = None):
    if (not re.fullmatch(r"[0-9]{1,20}", run_id) or
            not re.fullmatch(r"[0-9]{1,4}", run_attempt)):
        raise MigrationGuard("Trusted GitHub Actions run required")
    if client is None:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(20)) as http:
            return run(account, token, run_id, run_attempt, client=http, now=now)
    identity = _oidc_token()
    source, manifest = load_verified_source(
        client, identity, source_path=SOURCE_PATH_YUGIOH,
        allowed_scope=SCOPE, min_rows=EXPECTED_RECORDS, max_rows=MAX_ROWS,
        max_parts=MAX_SOURCE_PARTS, max_bytes=MAX_SOURCE_BYTES,
    )
    if source.expected_rows != EXPECTED_RECORDS or source.scope != SCOPE:
        raise MigrationGuard("Unreviewed Yu-Gi-Oh catalogue count changed; no D1 writes")
    source = _stable_source_projection(source)
    cloud = D1Client(account, token)
    dbid = _database(cloud)
    _schema(cloud, dbid)
    _query(cloud, dbid, BUDGET_SCHEMA)
    _existing_generation(cloud, dbid, source)
    current = _verify_staged_prefix(cloud, dbid, source)
    published = _query(cloud, dbid,
                       "select provider,system_code,language,manifest_sha "
                       "from shadow_active_partitions")
    if published and (
        len(published) != 1 or
        tuple(published[0][k] for k in ("provider","system_code","language","manifest_sha"))
            != (*SCOPE, source.manifest_sha) or current != source.expected_rows
    ):
        raise MigrationGuard("Unexpected early D1 shadow active generation")

    utc_day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
    remaining = source.expected_rows - current
    if remaining:
        prior = _daily_receipt(cloud, dbid, utc_day)
        if prior:
            if prior["manifest_sha"] != source.manifest_sha:
                raise MigrationGuard("Another source used this D1 daily budget")
            return {"status":"YUGIOH_D1_SHADOW_DAILY_BUDGET_ALREADY_USED",
                    "source_rows":source.expected_rows,"d1_staged_rows":current,
                    "d1_database_name":EXACT_DATABASE_NAME,
                    "no_public_catalogue_cutover":True,"market_value_writes":0,
                    "owner_and_settlement_writes":0}
        limit = min(DAILY_NEW_ROWS, remaining)
        # A durable receipt is written BEFORE any card inserts. A crash or
        # network acknowledgement loss can resume on the NEXT UTC day only.
        receipt = {"sql":BUDGET_INSERT,
                   "params":[utc_day,source.manifest_sha,run_id,limit]}
        _query(cloud, dbid, receipt["sql"], receipt["params"])
        subset = replace(source, rows=source.rows[current:current+limit],
                         expected_rows=limit)
        statements = list(codec.insert_statements(subset))
        for i in range(0, len(statements), codec.MAX_BATCH_STATEMENTS):
            cloud.batch(dbid, statements[i:i+codec.MAX_BATCH_STATEMENTS])
        # Verify all prior/current rows as exact prefix before reporting
        # progress, not just a count or last-record guess.
        staged = _verify_staged_prefix(cloud, dbid, source)
        if staged != current + limit:
            raise MigrationGuard("Daily D1 staged count not equal to bounded receipt")
    else:
        staged = current

    if staged < source.expected_rows:
        return {"status":"YUGIOH_D1_SHADOW_PARTIAL_VERIFIED",
                "source_rows":source.expected_rows,"d1_staged_rows":staged,
                "new_rows_this_run":staged-current,
                "d1_database_name":EXACT_DATABASE_NAME,
                "no_public_catalogue_cutover":True,"market_value_writes":0,
                "owner_and_settlement_writes":0}

    # Full byte-proven row identity parity, then activation in the isolated D1.
    # This is NOT a FastAPI/catalogue/Shopify production read switch.
    if verify_d1_projection(cloud, dbid, source) != source.expected_rows:
        raise MigrationGuard("Complete D1 source checksum not proven")
    if not published:
        activation = codec.activation_statement(source)
        _query(cloud, dbid, activation["sql"], activation["params"])
    check = _query(cloud, dbid,
                   "select manifest_sha from shadow_active_partitions where "
                   "provider=? and system_code=? and language=?", SCOPE)
    if len(check) != 1 or check[0]["manifest_sha"] != source.manifest_sha:
        raise MigrationGuard("Isolated D1 activation pointer mismatch")
    if verify_d1_projection(cloud, dbid, source) != source.expected_rows:
        raise MigrationGuard("Activated D1 partition failed checksum verification")
    return {"status":"REAL_R2_YUGIOH_TO_ISOLATED_D1_VERIFIED",
            "r2_source_manifest_sha":source.manifest_sha,
            "d1_projection_sha":source.projection_sha,
            "source_rows":source.expected_rows,"d1_verified_rows":staged,
            "d1_database_name":EXACT_DATABASE_NAME,
            "no_public_catalogue_cutover":True,"market_value_writes":0,
            "owner_and_settlement_writes":0,"supabase_writes":0,"r2_writes":0}


def main():
    try:
        report = run(
            os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
            os.getenv("CLOUDFARE_D1_PILOT_TOKEN", ""),
            os.getenv("GITHUB_RUN_ID", ""),
            os.getenv("GITHUB_RUN_ATTEMPT", ""),
        )
    except (MigrationGuard, PilotError, ValueError, httpx.HTTPError) as exc:
        print("Isolated Yu-Gi-Oh D1 shadow blocked: " + str(exc), file=sys.stderr)
        return 1
    Path(REPORT_FILE).write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
