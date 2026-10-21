"""Stage, inspect, check covers, and apply authorised comic/manga snapshots.

Default operations are offline. Only `covers` reads publisher images; only
`apply` writes Postgres, after capacity checks. No paid provider or cron enabled.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os

import asyncpg
from PIL import Image

from app.book_bulk_import import (ImportPaused, apply_stage, capacity_plan, open_stage,
                                  stage_file, stage_report)
from app.book_catalogue_sources import canonical_json, cover_receipt, validate_entry
from app.recognition_images import reference_image_bytes


async def check_covers(state, limit=100, fetch=reference_image_bytes):
    """A bounded request per cover. Failure keeps metadata and a pending image.

    The source URL and exact edition/image pair must pass before network access.
    No background retry, generated artwork, or GCD image hotlinking.
    """
    if not 1 <= limit <= 1000:
        raise ValueError("Cover limit must be 1–1000")
    checked = failed = 0
    for row in state.execute("select line,entry from records where status='READY' and cover_attempted=0 order by line"):
        entry = json.loads(row["entry"])
        validate_entry(entry)
        if not entry.get("image_url") or entry.get("reference"):
            continue
        payload = await fetch(entry["image_url"])
        if payload:
            try:
                with Image.open(io.BytesIO(payload.data)) as image:
                    width, height = image.size
                    image.verify()
                entry["reference"] = cover_receipt(entry, hashlib.sha256(payload.data).hexdigest(), width, height)
            except (ValueError, OSError, Image.DecompressionBombError):
                payload = None
        with state:
            state.execute("update records set cover_attempted=1 where line=?", (row["line"],))
            if payload:
                state.execute("update records set entry=? where line=?", (canonical_json(entry), row["line"]))
        if payload:
            checked += 1
        else:
            failed += 1
        if checked + failed >= limit:
            break
    return {**stage_report(state), "cover_checks": {"checked": checked, "pending": failed}}


async def run(args):
    state = open_stage(args.state)
    try:
        if args.command == "stage":
            return stage_file(state, args.input, args.provider)
        if args.command == "report":
            return stage_report(state)
        if args.command == "review":
            if not 1 <= args.limit <= 1000:
                raise ValueError("Review limit must be 1–1000")
            return [dict(row) for row in state.execute("select line,source_key,reason from records where status='REVIEW' order by line limit ?", (args.limit,))]
        if args.command == "covers":
            if args.retry_failed:
                with state:
                    state.execute("update records set cover_attempted=0 where json_extract(entry,'$.reference') is null")
            return await check_covers(state, args.limit)
        # This separate operator DSN is never read from user input or logged.
        dsn = os.environ.get("BOOK_IMPORT_DATABASE_URL")
        if not dsn:
            raise ImportPaused("BOOK_IMPORT_DATABASE_URL_REQUIRED")
        db = await asyncpg.connect(dsn, command_timeout=45)
        try:
            if args.command == "plan":
                return await capacity_plan(db, state, args.database_limit_bytes)
            return await apply_stage(db, state, batch_size=args.batch_size, max_batches=args.max_batches,
                                     database_limit_bytes=args.database_limit_bytes)
        finally:
            await db.close()
    finally:
        state.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="Durable SQLite staging/checkpoint path")
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("--provider", choices=["GCD", "PRH", "PUBLISHER"], required=True)
    stage.add_argument("--input", required=True, help="Immutable UTF-8 JSONL snapshot")
    commands.add_parser("report")
    review = commands.add_parser("review")
    review.add_argument("--limit", type=int, default=100)
    covers = commands.add_parser("covers")
    covers.add_argument("--limit", type=int, default=100)
    covers.add_argument("--retry-failed", action="store_true", help="Explicitly retry previous unavailable images")
    plan = commands.add_parser("plan")
    plan.add_argument("--database-limit-bytes", type=int, default=500_000_000, help="Verified current Postgres quota; change only after the upgrade is confirmed")
    apply = commands.add_parser("apply")
    apply.add_argument("--batch-size", type=int, default=50)
    apply.add_argument("--max-batches", type=int, default=20)
    apply.add_argument("--database-limit-bytes", type=int, default=500_000_000, help="Same verified quota used for plan; does not change or purchase storage")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(run(args)), indent=2))
    except (ImportPaused, ValueError, OSError, asyncpg.PostgresError):
        # Connection exceptions can contain credentials or full SQL arguments.
        # Emit only the stable safe reason for known pauses, otherwise fail closed.
        import sys
        exc = sys.exc_info()[1]
        print(json.dumps({"status": "PAUSED", "reason": str(exc) if isinstance(exc, ImportPaused) else "IMPORT_FAILED_CHECK_SOURCE_OR_DATABASE"}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
