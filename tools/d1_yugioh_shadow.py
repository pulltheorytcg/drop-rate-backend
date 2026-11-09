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
import time

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
# Founder explicitly upgraded Workers Paid on 9 Nov 2026. This is ONE
# reviewed, date-locked supplement, not an unrestricted daily quota bypass.
PAID_EXTRA_MAX_ROWS = 40_000
PAID_EXTRA_UTC_DAY = "2026-11-09"
PAID_EXTRA_APPROVAL = "FOUNDER_APPROVED_WORKERS_PAID_20261109"
MAX_REVIEWED_NAME_ONLY_CORRECTIONS = 10
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

# An immutable supplementary receipt reserves at most 40,000 additional
# **new rows**, never edits the original 8k/day Free-plan receipt. Same run
# can retry after partial Cloudflare acknowledgement loss using exact prefix.
PAID_EXTRA_SCHEMA = """create table if not exists shadow_paid_catchup_receipts(
    utc_day text primary key,
    manifest_sha text not null references shadow_generations(manifest_sha),
    run_id text not null,
    start_rows integer not null check(start_rows>=0),
    rows_limit integer not null check(rows_limit between 1 and 40000)
)"""
PAID_EXTRA_INSERT = """insert into shadow_paid_catchup_receipts(
    utc_day,manifest_sha,run_id,start_rows,rows_limit) values(?,?,?,?,?)"""

D1_READBACK_SQL = ("select " + ",".join(codec.SQLITE_COLUMNS) +
    " from shadow_cards where manifest_sha=? and card_key>? "
    "order by card_key limit ?")


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
    """Retain an older partial generation when the reviewed R2 source grows.

    Never relabel rows under a new source hash. Only up to ten verified,
    name/name_fold-only corrections in staged cards can pass the bounded guard;
    missing keys or all other changed fields block. Old rows stay immutable,
    and every current-source row must still be staged and checksum-verified
    under the new manifest. At most two generations may coexist.
    """
    rows = _query(cloud, dbid,
                  """select manifest_sha,provider,system_code,language,expected_rows,
                            projection_sha,source_content_sha,source_revision
                     from shadow_generations""")
    if len(rows) > 2:
        raise MigrationGuard("More than two Yu-Gi-Oh generations require review")
    expected = (
        source.manifest_sha, *source.scope, source.expected_rows,
        source.projection_sha, source.source_content_sha, source.source_revision,
    )
    columns = ("manifest_sha","provider","system_code","language","expected_rows",
               "projection_sha","source_content_sha","source_revision")
    matching = [row for row in rows if row.get("manifest_sha") == source.manifest_sha]
    if matching:
        if len(matching) != 1 or tuple(matching[0].get(k) for k in columns) != expected:
            raise MigrationGuard("Existing D1 generation differs from immutable R2 source")
        return rows
    if rows:
        if len(rows) != 1:
            raise MigrationGuard("Another incomplete Yu-Gi-Oh refresh requires review")
        previous = rows[0]
        if (tuple(previous.get(k) for k in ("provider","system_code","language"))
                != source.scope or type(previous.get("expected_rows")) is not int
                or not 1 <= previous["expected_rows"] <= source.expected_rows):
            raise MigrationGuard("Old Yu-Gi-Oh generation scope/count differs from R2 source")
        old_sha = previous.get("manifest_sha")
        if not isinstance(old_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", old_sha):
            raise MigrationGuard("Invalid retained Yu-Gi-Oh generation")
        wanted = {row[1]: row for row in source.rows}
        if len(wanted) != source.expected_rows:
            raise MigrationGuard("Current Yu-Gi-Oh identities are not unique")
        count_rows = _query(cloud, dbid,
            "select count(*) as n from shadow_cards where manifest_sha=?", (old_sha,))
        if (len(count_rows) != 1 or type(count_rows[0].get("n")) is not int
                or not 0 <= count_rows[0]["n"] <= previous["expected_rows"]):
            raise MigrationGuard("Retained Yu-Gi-Oh generation count is invalid")
        count = count_rows[0]["n"]
        seen = set()
        cursor = ""
        missing_keys = 0
        changed_rows = 0
        changed_columns = {}
        for offset in range(0, count, 100):
            old_rows = _query(cloud, dbid, D1_READBACK_SQL,
                              (old_sha, cursor, min(100, count-offset)))
            if len(old_rows) != min(100, count-offset):
                raise MigrationGuard("Retained Yu-Gi-Oh generation is incomplete")
            for row in old_rows:
                # Report fixed-schema column counts only. Card keys, subjects,
                # per-row data, provider contents and tokens never enter logs.
                if not isinstance(row, dict) or set(row) != set(codec.SQLITE_COLUMNS):
                    raise MigrationGuard("Invalid retained Yu-Gi-Oh D1 row shape")
                key = row["card_key"]
                if not isinstance(key,str) or not key or key <= cursor or key in seen:
                    raise MigrationGuard("Duplicate/unordered retained Yu-Gi-Oh D1 identity")
                seen.add(key)
                cursor = key
                expected_row = wanted.get(key)
                if expected_row is None:
                    missing_keys += 1
                    continue
                changed = [
                    column for i, column in enumerate(codec.SQLITE_COLUMNS)
                    if column != "manifest_sha" and row[column] != expected_row[i]
                ]
                if changed:
                    # A genuinely renamed card must have a consistent name
                    # search fold in both immutable generations.
                    if ("name" in changed or "name_fold" in changed) and (
                        type(row["name"]) is not str
                        or type(row["name_fold"]) is not str
                        or row["name_fold"] != row["name"].casefold()
                        or type(expected_row[7]) is not str
                        or type(expected_row[8]) is not str
                        or expected_row[8] != expected_row[7].casefold()
                    ):
                        raise MigrationGuard(
                            "Yu-Gi-Oh name search normalization mismatch; no D1 refresh"
                        )
                    changed_rows += 1
                    for column in changed:
                        changed_columns[column] = changed_columns.get(column, 0) + 1
        if len(seen) != count:
            raise MigrationGuard("Retained Yu-Gi-Oh readback count mismatch")
        if missing_keys or changed_rows:
            # Immutable source evidence may legitimately correct a card name.
            # Only the coupled name/name_fold pair is eligible. Never reuse
            # or mutate old rows, permit changed keys, or relax other fields.
            # Require a *small* reviewed correction set, not mass renames.
            safe_counts = {
                "source_rows": source.expected_rows,
                "retained_rows": count,
                "missing_keys": missing_keys,
                "changed_rows": changed_rows,
                "changed_fields": dict(sorted(changed_columns.items())),
            }
            name_only = (
                missing_keys == 0
                and 0 < changed_rows <= MAX_REVIEWED_NAME_ONLY_CORRECTIONS
                and changed_columns == {
                    "name": changed_rows, "name_fold": changed_rows
                }
            )
            if not name_only:
                raise MigrationGuard(
                    "Old Yu-Gi-Oh identities changed; manual review required: "
                    + json.dumps(safe_counts, sort_keys=True)
                )
            print("YUGIOH_RETAINED_NAME_ONLY_CORRECTIONS_VERIFIED "
                  + json.dumps(safe_counts, sort_keys=True), flush=True)
    statement = codec.generation_statement(source)
    _query(cloud, dbid, statement["sql"], statement["params"])
    return rows + [dict(zip(columns, expected))]


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
    cursor = ""
    while offset < count:
        rows = _query(cloud, dbid, D1_READBACK_SQL,
                      (source.manifest_sha, cursor, min(100,count-offset)))
        if len(rows) != min(100,count-offset):
            raise MigrationGuard("Missing staged source row")
        for i, row in enumerate(rows):
            if (not isinstance(row, dict) or set(row) != set(codec.SQLITE_COLUMNS)
                    or not isinstance(row["card_key"],str)
                    or not row["card_key"] or row["card_key"] <= cursor
                    or tuple(row[k] for k in codec.SQLITE_COLUMNS)
                       != source.rows[offset+i]):
                raise MigrationGuard("D1 staged prefix does not match R2 source")
            cursor = row["card_key"]
        offset += len(rows)
    return count


def _daily_receipt(cloud: D1Client, dbid: str, today: str):
    rows = _query(cloud, dbid,
                  "select utc_day,manifest_sha,run_id,rows_limit "
                  "from shadow_daily_write_budget where utc_day=?", (today,))
    if len(rows) > 1:
        raise MigrationGuard("Duplicate daily D1 quota receipt")
    return rows[0] if rows else None


def _paid_one_time_catchup(
    cloud: D1Client, dbid: str, source: codec.Projection,
    staged: int, run_id: str, utc_day: str,
):
    """Bounded one-time additional staging from *approved* paid capacity.

    The immutable original daily receipt is retained. An independent,
    date/manifest/run-pinned receipt is written BEFORE additional rows.
    An acknowledgement-lost retry is allowed only for the SAME GitHub run
    and only up to the reserved prefix target; it cannot mint more budget.
    """
    if utc_day != PAID_EXTRA_UTC_DAY:
        raise MigrationGuard("Paid staging approval date has expired")
    _query(cloud, dbid, PAID_EXTRA_SCHEMA)
    rows = _query(cloud, dbid,
        "select utc_day,manifest_sha,run_id,start_rows,rows_limit "
        "from shadow_paid_catchup_receipts where utc_day=?", (utc_day,))
    if len(rows)>1:
        raise MigrationGuard("Ambiguous paid D1 catch-up receipt")
    if rows:
        receipt=rows[0]
        if receipt.get("manifest_sha") != source.manifest_sha:
            raise MigrationGuard("Paid catch-up source manifest changed; no writes")
        if receipt.get("run_id") != run_id:
            # Different runs cannot reuse/change a previous paid reservation.
            # The original GitHub workflow may be rerun (same GITHUB_RUN_ID).
            return staged, "PAID_CATCHUP_RESERVED_BY_DIFFERENT_RUN"
        start=receipt.get("start_rows")
        limit=receipt.get("rows_limit")
        if (type(start) is not int or type(limit) is not int
                or not 0 <= start <= staged <= start + limit
                or not 1 <= limit <= PAID_EXTRA_MAX_ROWS
                or start+limit > source.expected_rows):
            raise MigrationGuard("Paid catch-up receipt/prefix inconsistent")
    else:
        remaining=source.expected_rows-staged
        if remaining<=0:
            return staged, "PAID_CATCHUP_NOT_NEEDED"
        limit=min(PAID_EXTRA_MAX_ROWS,remaining)
        start=staged
        _query(cloud, dbid, PAID_EXTRA_INSERT,
               (utc_day,source.manifest_sha,run_id,start,limit))
    target=start+limit
    if staged < target:
        # At most 40,000 source rows; preserve immutable order and row keys.
        subset=replace(source,rows=source.rows[staged:target],
                       expected_rows=target-staged)
        statements=list(codec.insert_statements(subset))
        for i in range(0,len(statements),codec.MAX_BATCH_STATEMENTS):
            cloud.batch(dbid,statements[i:i+codec.MAX_BATCH_STATEMENTS])
        confirmed=_verify_staged_prefix(cloud,dbid,source)
        if confirmed != target:
            raise MigrationGuard("Paid D1 source prefix differs from receipt")
        staged=confirmed
    return staged, "PAID_CATCHUP_PREFIX_VERIFIED"


def run(account: str, token: str, run_id: str, run_attempt: str, *,
        client: httpx.Client | None = None, now: datetime | None = None):
    if (not re.fullmatch(r"[0-9]{1,20}", run_id) or
            not re.fullmatch(r"[0-9]{1,4}", run_attempt)):
        raise MigrationGuard("Trusted GitHub Actions run required")
    if client is None:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(20)) as http:
            return run(account, token, run_id, run_attempt, client=http, now=now)
    # The trusted GitHub workflow and Railway backend deploy independently.
    # Never retry unauthorized 401/403 or corrupted source bytes; only the
    # fixed endpoint's temporary 404/503 while its new code rolls out.
    for source_attempt in range(30):
        identity = _oidc_token()
        try:
            source, manifest = load_verified_source(
                client, identity, source_path=SOURCE_PATH_YUGIOH,
                allowed_scope=SCOPE, min_rows=EXPECTED_RECORDS, max_rows=MAX_ROWS,
                max_parts=MAX_SOURCE_PARTS, max_bytes=MAX_SOURCE_BYTES,
            )
            break
        except MigrationGuard as exc:
            if str(exc) not in {"R2 export rejected: HTTP 404",
                                "R2 export rejected: HTTP 503"} or source_attempt == 29:
                raise
            time.sleep(10)
    if not EXPECTED_RECORDS <= source.expected_rows <= MAX_ROWS or source.scope != SCOPE:
        raise MigrationGuard("Unreviewed Yu-Gi-Oh catalogue count changed; no D1 writes")
    source = _stable_source_projection(source)
    cloud = D1Client(account, token)
    dbid = _database(cloud)
    _schema(cloud, dbid)
    _query(cloud, dbid, BUDGET_SCHEMA)
    registry = _existing_generation(cloud, dbid, source)
    current = _verify_staged_prefix(cloud, dbid, source)
    published = _query(cloud, dbid,
                       "select provider,system_code,language,manifest_sha "
                       "from shadow_active_partitions")
    if published:
        if (len(published) != 1 or
                tuple(published[0][k] for k in ("provider","system_code","language")) != SCOPE):
            raise MigrationGuard("Unexpected D1 active Yu-Gi-Oh partition")
        active_sha = published[0]["manifest_sha"]
        if active_sha != source.manifest_sha:
            previous = [row for row in registry if row["manifest_sha"] == active_sha]
            if len(previous) != 1:
                raise MigrationGuard("Unrecognised active Yu-Gi-Oh generation")
            count_rows = _query(cloud, dbid,
                "select count(*) as n from shadow_cards where manifest_sha=?", (active_sha,))
            if len(count_rows) != 1 or count_rows[0]["n"] != previous[0]["expected_rows"]:
                raise MigrationGuard("Incomplete previously active Yu-Gi-Oh generation")
        elif current != source.expected_rows:
            raise MigrationGuard("Active Yu-Gi-Oh generation is incomplete")

    utc_day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
    paid_approved = (
        utc_day == PAID_EXTRA_UTC_DAY and
        os.getenv("DR_D1_PAID_CATCHUP_APPROVAL", "") == PAID_EXTRA_APPROVAL
    )
    remaining = source.expected_rows - current
    staged = current
    if remaining:
        prior = _daily_receipt(cloud, dbid, utc_day)
        if prior and prior.get("manifest_sha") != source.manifest_sha:
            raise MigrationGuard("Existing daily receipt is for another source; no writes")
        if not prior:
            limit = min(DAILY_NEW_ROWS, remaining)
            # The legacy, independently enforced 8k/day receipt stays intact.
            receipt = {"sql":BUDGET_INSERT,
                       "params":[utc_day,source.manifest_sha,run_id,limit]}
            _query(cloud, dbid, receipt["sql"], receipt["params"])
            subset = replace(source, rows=source.rows[current:current+limit],
                             expected_rows=limit)
            statements = list(codec.insert_statements(subset))
            for i in range(0, len(statements), codec.MAX_BATCH_STATEMENTS):
                cloud.batch(dbid, statements[i:i+codec.MAX_BATCH_STATEMENTS])
            staged = _verify_staged_prefix(cloud, dbid, source)
            if staged != current + limit:
                raise MigrationGuard("Daily D1 staged count not equal to bounded receipt")
        elif not paid_approved:
            return {"status":"YUGIOH_D1_SHADOW_DAILY_BUDGET_ALREADY_USED",
                    "source_rows":source.expected_rows,"d1_staged_rows":current,
                    "d1_database_name":EXACT_DATABASE_NAME,
                    "no_public_catalogue_cutover":True,"market_value_writes":0,
                    "owner_and_settlement_writes":0}
        if paid_approved and staged < source.expected_rows:
            staged,paid_status = _paid_one_time_catchup(
                cloud,dbid,source,staged,run_id,utc_day)
            if paid_status == "PAID_CATCHUP_RESERVED_BY_DIFFERENT_RUN":
                return {"status":"YUGIOH_D1_SHADOW_PAID_RECEIPT_RESERVED",
                        "source_rows":source.expected_rows,
                        "d1_staged_rows":staged,
                        "d1_database_name":EXACT_DATABASE_NAME,
                        "no_public_catalogue_cutover":True,"market_value_writes":0,
                        "owner_and_settlement_writes":0}

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
    elif published[0]["manifest_sha"] != source.manifest_sha:
        _query(cloud, dbid,
            "update shadow_active_partitions set manifest_sha=? "
            "where provider=? and system_code=? and language=? and manifest_sha=?",
            (source.manifest_sha, *SCOPE, published[0]["manifest_sha"]))
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
