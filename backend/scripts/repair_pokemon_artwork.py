"""Explicit TCGdex manifest artwork probe; dry-run unless --apply is supplied.

--rows-json permits a read-only network probe without database credentials.
--from-settings uses the existing trusted maintenance administrator identity.
"""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from app.pokemon_artwork_repair import MAX_ROWS, probe_rows, repair


def progress(report):
    print("POKEMON_ARTWORK_PROGRESS " + json.dumps(report, sort_keys=True), flush=True)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--actor-user-id", type=UUID)
    identity.add_argument("--from-settings", action="store_true")
    parser.add_argument("--rows-json", type=Path)
    parser.add_argument("--report-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=MAX_ROWS)
    parser.add_argument("--max-seconds", type=int, default=120)
    parser.add_argument("--after", nargs=3, metavar=("LANGUAGE", "SET_ID", "PROVIDER_ID"))
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_ROWS:
        parser.error("--limit must be between 1 and 5000")
    if not 1 <= args.max_seconds <= 240:
        parser.error("--max-seconds must be between 1 and 240")
    if args.rows_json:
        if args.apply or args.actor_user_id or args.from_settings or args.after:
            parser.error("--rows-json is read-only and cannot use database/apply options")
        if args.rows_json.stat().st_size > 8_000_000:
            parser.error("Input snapshot is too large")
        rows = json.loads(args.rows_json.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            parser.error("Input must be a bounded list of existing reference rows")
        verified, report = await probe_rows(rows[:args.limit], progress=progress, max_seconds=args.max_seconds)
        report.update(apply=False, updated=0, verified_items=verified)
    else:
        if not (args.actor_user_id or args.from_settings):
            parser.error("Choose --actor-user-id or --from-settings")
        from app.db import create_pool
        from app.settings import get_settings
        settings = get_settings()
        actor = args.actor_user_id or UUID(settings.catalogue_maintenance_actor_user_id)
        pool = await create_pool(settings)
        try:
            report = await repair(pool, actor, apply=args.apply, limit=args.limit, progress=progress, max_seconds=args.max_seconds, after=args.after)
        finally:
            await pool.close()
    if args.report_file:
        args.report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "verified_items"}
    print("POKEMON_ARTWORK_REPAIR " + json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
