"""Read-only Cloudflare D1 quota/disk readiness for the full R2 catalogue.

Measures *actual* D1 databases and SQLite page usage from the scoped account,
and whether the real Yu-Gi-Oh! isolated staging pointer has completed.
No DELETE, DROP, CREATE, account upgrade, R2 IO or financial data access.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from d1_remote_catalogue_pilot import D1Client, PilotError
from d1_r2_real_shadow import _query, MigrationGuard

ACCOUNT = "e4d4b363540e991048d2e1812d5ef53e"
YGO = "drop-rate-d1-real-yugioh-shadow"
YGO_SCOPE = ("ygoprodeck", "YUGIOH", "English")
YGO_MANIFEST_SHA = "e85fb49e5cf81427cec68b24749de5e273845f1b2245536e4879ded0e4b0a9dd"
YGO_TOTAL = 45_418
MAX_FREE_DATABASES = 10
FREE_MAX_DB_BYTES = 500_000_000
SHADOW_SAFETY_BYTES = 390_000_000
REPORT = "d1-full-catalogue-capacity-report.json"


def _one_scalar(client: D1Client, uuid: str, sql: str, field: str) -> int:
    rows = _query(client, uuid, sql)
    if (len(rows) != 1 or field not in rows[0]
            or type(rows[0][field]) is not int):
        raise MigrationGuard("D1 did not provide verified page usage")
    return rows[0][field]


def inspect_capacity(account: str, token: str):
    if account != ACCOUNT:
        raise MigrationGuard("D1 account differs from approved migration scope")
    cloud = D1Client(account, token)
    visible = cloud.list_databases()
    if not isinstance(visible, list) or len(visible) > MAX_FREE_DATABASES:
        raise MigrationGuard("Unexpected D1 account database inventory")
    names = [x.get("name") for x in visible]
    if any(type(name) is not str or not name for name in names):
        raise MigrationGuard("D1 returned unidentifiable database")
    if len(set(names)) != len(names):
        raise MigrationGuard("D1 duplicate database names")
    budgets = []
    ygo = None
    for record in visible:
        name = record["name"]
        uuid = record.get("uuid")
        if not isinstance(uuid, str) or len(uuid) != 36:
            raise MigrationGuard("D1 returned malformed database identity")
        pages = _one_scalar(cloud, uuid, "pragma page_count", "page_count")
        page_size = _one_scalar(cloud, uuid, "pragma page_size", "page_size")
        if pages < 0 or not 512 <= page_size <= 65536:
            raise MigrationGuard("D1 returned implausible size")
        bytes_used = pages * page_size
        budgets.append({"bytes_used":bytes_used,
                        "storage_warning":bytes_used >= SHADOW_SAFETY_BYTES})
        if name == YGO:
            ygo = uuid

    ygo_rows = 0
    ygo_complete = False
    if ygo is not None:
        ygo_rows = _one_scalar(
            cloud, ygo,
            "select count(*) as n from shadow_cards where manifest_sha='"
            + YGO_MANIFEST_SHA + "'",
            "n",
        )
        if ygo_rows > YGO_TOTAL:
            raise MigrationGuard("YGO D1 staged source exceeds original published count")
        pointers = _query(
            cloud, ygo,
            "select manifest_sha from shadow_active_partitions "
            "where provider=? and system_code=? and language=?", YGO_SCOPE,
        )
        ygo_complete = (
            ygo_rows == YGO_TOTAL
            and len(pointers) == 1
            and pointers[0].get("manifest_sha") == YGO_MANIFEST_SHA
        )
        if pointers and not ygo_complete:
            raise MigrationGuard("YGO D1 active generation disagrees with source")

    # This is only a *preflight*. It cannot certify account-wide daily D1
    # rows already consumed by other applications or account plan. Never
    # claim quota is free based solely on the count or file usage.
    room_for_one = len(visible) < MAX_FREE_DATABASES
    total_storage = sum(x["bytes_used"] for x in budgets)
    storage_safe = (
        all(x["bytes_used"] < SHADOW_SAFETY_BYTES for x in budgets)
        and total_storage < 4_000_000_000
    )
    return {
        "status": "READ_ONLY_D1_ACCOUNT_INVENTORY_VERIFIED",
        "visible_database_count": len(visible),
        "total_database_storage_bytes": total_storage,
        "largest_database_bytes": max((x["bytes_used"] for x in budgets), default=0),
        "free_plan_single_database_max_bytes": FREE_MAX_DB_BYTES,
        "has_space_for_one_new_database_by_count": room_for_one,
        "existing_database_storage_under_safety_threshold": storage_safe,
        "yugioh_source_rows": YGO_TOTAL,
        "yugioh_staged_rows": ygo_rows,
        "yugioh_full_active_parity": ygo_complete,
        "subsequent_import_allowed_by_static_readiness": (
            room_for_one and storage_safe and ygo_complete
        ),
        "daily_account_write_quota_measured": False,
        "warning": "D1 row metrics and account tier must be verified separately",
        "d1_writes": 0,
        "production_reads_switched": False,
        "owner_or_settlement_writes": 0,
        "market_value_writes": 0,
    }


def main() -> int:
    try:
        report = inspect_capacity(
            os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
            os.getenv("CLOUDFARE_D1_PILOT_TOKEN", ""),
        )
    except (MigrationGuard, PilotError) as exc:
        print("Read-only D1 capacity audit blocked safely: " + str(exc))
        return 1
    Path(REPORT).write_text(json.dumps(report,sort_keys=True,indent=2) + "\n")
    print(json.dumps(report,sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
