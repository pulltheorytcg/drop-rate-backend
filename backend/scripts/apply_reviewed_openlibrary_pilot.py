"""One reviewed Open Library metadata pilot, using the existing admin context.

Dry-run by default. No arbitrary source, actor, quota, credential or SQL input.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from app.access_control import require_platform_admin
from app.book_bulk_import import (ImportPaused, apply_stage, capacity_plan,
                                 open_stage, stage_file)
from app.db import create_pool, user_connection
from app.settings import get_settings

SNAPSHOT_SHA256 = "66fee0a07e5c43b3cf957f36f54e9382be4eaed2a1b8eb6fc3bc239235653b03"
SNAPSHOT_PATH = Path("backend/app/data/book_openlibrary_pilot_20261026.jsonl")
REVIEWED_COUNT = 32
MAX_SNAPSHOT_BYTES = 128 * 1024


def snapshot_spec(snapshot):
    if snapshot=="pilot":
        return SNAPSHOT_PATH,SNAPSHOT_SHA256,REVIEWED_COUNT
    if snapshot=="expansion":
        return (Path("backend/app/data/book_openlibrary_expansion_20261026.jsonl"),
                "5992ed846a0c10a356a31463bb29de567556c00821f193a3bb0559a74c49cdca",15)
    raise ImportPaused("BOOK_PILOT_SNAPSHOT_NOT_REGISTERED")


def stage_reviewed_snapshot(state,snapshot="pilot"):
    path,expected_sha,count=snapshot_spec(snapshot)
    with path.open("rb") as source:
        data = source.read(MAX_SNAPSHOT_BYTES + 1)
    if len(data)>MAX_SNAPSHOT_BYTES or hashlib.sha256(data).hexdigest()!=expected_sha:
        raise ImportPaused("BOOK_PILOT_SNAPSHOT_MISMATCH")
    # Stage an immutable byte copy, not a second read of a mutable input path.
    with TemporaryDirectory(prefix="drop-rate-book-pilot-") as folder:
        snapshot = Path(folder) / "reviewed.jsonl"
        snapshot.write_bytes(data)
        report = stage_file(state,snapshot,"OPEN_LIBRARY")
    if not report["complete"] or report["statuses"]!={"READY":count}:
        raise ImportPaused("BOOK_PILOT_REVIEWED_INPUT_INVALID")
    return report


async def run_with_pool(pool, actor, *, apply=False,snapshot='pilot'):
    _,expected_sha,count=snapshot_spec(snapshot)
    if type(apply) is not bool:
        raise ImportPaused("BOOK_PILOT_MODE_INVALID")
    state = open_stage(":memory:")
    try:
        stage_reviewed_snapshot(state,snapshot)
        async with user_connection(pool,UUID(str(actor)),str(uuid4())) as connection:
            await require_platform_admin(connection)
            plan = await capacity_plan(connection,state)
            if not plan["whole_stage_fits_reserve"]:
                raise ImportPaused("BOOK_PILOT_CAPACITY_PAUSED")
            report = dict(snapshot_sha256=expected_sha,reviewed_records=count,
                          dry_run=not apply,administrator_authorized=True,
                          database_role=await connection.fetchval("select current_user"),plan=plan)
            if apply:
                report["result"] = await apply_stage(connection,state,batch_size=count,max_batches=1)
        # user_connection's outer transaction has committed at this point.
        # Its nested importer checkpoint existed only in this ephemeral state.
        report["committed"] = apply
        return report
    finally:
        state.close()


async def run(*, apply=False,snapshot='pilot'):
    settings = get_settings()
    actor = settings.catalogue_maintenance_actor_user_id
    if not actor:
        raise ImportPaused("BOOK_PILOT_MAINTENANCE_ACTOR_REQUIRED")
    try:
        actor = UUID(actor)
    except ValueError:
        raise ImportPaused("BOOK_PILOT_MAINTENANCE_ACTOR_INVALID") from None
    pool = await create_pool(settings)
    try:
        return await run_with_pool(pool,actor,apply=apply,snapshot=snapshot)
    finally:
        await pool.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true",help="Apply the selected registered metadata snapshot as the configured maintenance administrator")
    parser.add_argument("--snapshot",choices=("pilot","expansion"),default="pilot")
    args = parser.parse_args()
    try:
        report = asyncio.run(run(apply=args.apply,snapshot=args.snapshot))
    except Exception as exc:
        # Database/config errors can include credential-bearing diagnostics.
        reason = str(exc) if isinstance(exc,ImportPaused) else "BOOK_PILOT_FAILED_CHECK_ADMIN_CAPACITY_AND_DATABASE"
        print(json.dumps({"status":"PAUSED","reason":reason},sort_keys=True))
        raise SystemExit(2)
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()

