"""Resumable immutable MTGJSON Magic R2 -> isolated D1 shadow.

This writer will NEVER run until the fully-verified 45,418-row Yu-Gi-Oh D1
generation is active and its last-day receipt is past. Stage at most 5,000
Magic reference rows per UTC day, with exact R2 source and D1 SHA-256 parity.
No production routes, prices, owner records, refunds or Shopify writes.
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
import time

import httpx

from app import d1_shadow_catalogue as codec
from d1_remote_catalogue_pilot import D1Client, PilotError
from d1_r2_real_shadow import (
    API_ORIGIN, SOURCE_PATH, _oidc_token, _query, _schema,
    load_verified_source, verify_d1_projection, MigrationGuard,
)

SCOPE = ("mtgjson", "MAGIC_THE_GATHERING", "English")
SOURCE_PATH_MAGIC = SOURCE_PATH + "/magic-d1"
EXACT_DATABASE_NAME = "drop-rate-d1-real-magic-shadow"
EXPECTED_RECORDS = 153_662
EXPECTED_MANIFEST_SHA = "be5af5e84d3a10bcac32a996f0dc8779fdf33c95fac89669381a8bbd32fcad28"
MAX_ROWS = 155_000
MAX_SOURCE_BYTES = 110_000_000
MAX_SOURCE_PARTS = 512
DAILY_NEW_ROWS = 5_000
MAX_D1_DATABASES = 8  # reserve capacity for legacy and non-TCG partitions
REPORT_FILE = "d1-magic-real-shadow-report.json"
ACCOUNT_ID = "e4d4b363540e991048d2e1812d5ef53e"
YGO_DATABASE_NAME = "drop-rate-d1-real-yugioh-shadow"
YGO_MANIFEST_SHA = "e85fb49e5cf81427cec68b24749de5e273845f1b2245536e4879ded0e4b0a9dd"
YGO_SCOPE = ("ygoprodeck", "YUGIOH", "English")
YGO_EXPECTED_ROWS = 45_418
D1_DISK_SAFETY_BYTES = 390_000_000

BUDGET_SCHEMA = """create table if not exists shadow_daily_write_budget(
    utc_day text primary key,
    manifest_sha text not null references shadow_generations(manifest_sha),
    run_id text not null,
    rows_limit integer not null check(rows_limit between 0 and 5000)
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



def _account_and_yugioh_gate(cloud: D1Client, today: str) -> dict | None:
    """Fail-closed Cloudflare D1 read-only gate, BEFORE any Magic source fetch.

    Do not treat an imported source with no active verified YGO pointer as a
    completed preceding migration. Do not create a new DB on a busy free
    account; Yu-Gi-Oh completion-day writes require at least a day boundary.
    """
    records = cloud.list_databases()
    if not isinstance(records, list) or len(records) > 10:
        raise MigrationGuard("Unverified D1 database inventory")
    names = [row.get("name") for row in records]
    if any(not isinstance(x, str) or not x for x in names) or len(names) != len(set(names)):
        raise MigrationGuard("Ambiguous D1 database inventory")
    def waiting(status: str, ygo_rows: int = 0) -> dict:
        return {
            "status": status, "source_rows": EXPECTED_RECORDS,
            "d1_staged_rows": 0, "yugioh_staged_rows": ygo_rows,
            "d1_database_name": EXACT_DATABASE_NAME,
            "no_public_catalogue_cutover": True,
            "market_value_writes": 0, "owner_and_settlement_writes": 0,
            "supabase_writes": 0, "r2_writes": 0,
        }
    total_bytes = 0
    for record in records:
        uid = record.get("uuid")
        if not isinstance(uid, str) or not re.fullmatch(
                r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", uid):
            raise MigrationGuard("D1 returned invalid database UUID")
        a = _query(cloud, uid, "pragma page_count")
        b = _query(cloud, uid, "pragma page_size")
        if (len(a) != 1 or len(b) != 1
                or type(a[0].get("page_count")) is not int
                or type(b[0].get("page_size")) is not int
                or a[0]["page_count"] < 0
                or not 512 <= b[0]["page_size"] <= 65536):
            raise MigrationGuard("Cannot establish D1 storage headroom")
        used = a[0]["page_count"] * b[0]["page_size"]
        if used >= D1_DISK_SAFETY_BYTES:
            return waiting("MAGIC_WAITING_FOR_D1_DISK_HEADROOM")
        total_bytes += used
    if total_bytes >= 4_000_000_000:
        return waiting("MAGIC_WAITING_FOR_D1_DISK_HEADROOM")
    if YGO_DATABASE_NAME not in names:
        return waiting("MAGIC_WAITING_FOR_YUGIOH_D1_PARITY")
    ygo_db = records[names.index(YGO_DATABASE_NAME)]["uuid"]
    rows = _query(cloud, ygo_db,
                  "select count(*) as n from shadow_cards where manifest_sha=?",
                  (YGO_MANIFEST_SHA,))
    if len(rows) != 1 or type(rows[0].get("n")) is not int:
        raise MigrationGuard("Cannot verify preceding YGO source count")
    count = rows[0]["n"]
    if count > YGO_EXPECTED_ROWS or count < 0:
        raise MigrationGuard("YGO staged count exceeds registered R2 source")
    pointer = _query(cloud, ygo_db,
                     "select manifest_sha from shadow_active_partitions "
                     "where provider=? and system_code=? and language=?", YGO_SCOPE)
    if pointer and (
        len(pointer) != 1 or pointer[0].get("manifest_sha") != YGO_MANIFEST_SHA
        or count != YGO_EXPECTED_ROWS
    ):
        raise MigrationGuard("YGO active pointer disagrees with full source")
    if count != YGO_EXPECTED_ROWS or len(pointer) != 1:
        return waiting("MAGIC_WAITING_FOR_YUGIOH_D1_PARITY", count)
    generation = _query(
        cloud, ygo_db,
        "select expected_rows,projection_sha from shadow_generations "
        "where manifest_sha=?", (YGO_MANIFEST_SHA,),
    )
    if (len(generation) != 1
            or generation[0].get("expected_rows") != YGO_EXPECTED_ROWS
            or not isinstance(generation[0].get("projection_sha"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", generation[0]["projection_sha"])):
        raise MigrationGuard("YGO active generation missing immutable proof")
    last_ygo_writes = _query(
        cloud, ygo_db,
        "select count(*) as n from shadow_daily_write_budget where utc_day=?",
        (today,),
    )
    if len(last_ygo_writes) != 1 or type(last_ygo_writes[0].get("n")) is not int:
        raise MigrationGuard("Cannot establish YGO last-day D1 write receipt")
    if last_ygo_writes[0]["n"] != 0:
        return waiting("MAGIC_WAITING_FOR_YUGIOH_DAILY_BUDGET", count)
    if EXACT_DATABASE_NAME not in names and len(records) >= MAX_D1_DATABASES:
        return waiting("MAGIC_WAITING_FOR_D1_DATABASE_CAPACITY", count)
    return None

def run(account: str, token: str, run_id: str, run_attempt: str, *,
        client: httpx.Client | None = None, now: datetime | None = None):
    if (not re.fullmatch(r"[0-9]{1,20}", run_id) or
            not re.fullmatch(r"[0-9]{1,4}", run_attempt)):
        raise MigrationGuard("Trusted GitHub Actions run required")
    if client is None:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(20)) as http:
            return run(account, token, run_id, run_attempt, client=http, now=now)
    if account != ACCOUNT_ID:
        raise MigrationGuard("Magic migration account differs from verified Cloudflare scope")
    day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
    cloud = D1Client(account, token)
    waiting = _account_and_yugioh_gate(cloud, day)
    if waiting is not None:
        return waiting
    # The trusted GitHub workflow and Railway backend deploy independently.
    # Never retry unauthorized 401/403 or corrupted source bytes; only the
    # fixed endpoint's temporary 404/503 while its new code rolls out.
    for source_attempt in range(30):
        identity = _oidc_token()
        try:
            source, manifest = load_verified_source(
                client, identity, source_path=SOURCE_PATH_MAGIC,
                allowed_scope=SCOPE, min_rows=EXPECTED_RECORDS, max_rows=MAX_ROWS,
                max_parts=MAX_SOURCE_PARTS, max_bytes=MAX_SOURCE_BYTES,
            )
            break
        except MigrationGuard as exc:
            if str(exc) not in {"R2 export rejected: HTTP 404",
                                "R2 export rejected: HTTP 503"} or source_attempt == 29:
                raise
            time.sleep(10)
    if (source.expected_rows != EXPECTED_RECORDS or source.scope != SCOPE
            or source.manifest_sha != EXPECTED_MANIFEST_SHA):
        raise MigrationGuard("Unreviewed Magic catalogue generation; no D1 writes")
    source = _stable_source_projection(source)
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
            return {"status":"MAGIC_D1_SHADOW_DAILY_BUDGET_ALREADY_USED",
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
        return {"status":"MAGIC_D1_SHADOW_PARTIAL_VERIFIED",
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
    return {"status":"REAL_R2_MAGIC_TO_ISOLATED_D1_VERIFIED",
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
        print("Isolated Magic D1 shadow blocked: " + str(exc), file=sys.stderr)
        return 1
    Path(REPORT_FILE).write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
