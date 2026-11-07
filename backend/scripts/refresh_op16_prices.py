"""Preview exact OP-16 base-printing guides; --apply records committed readback."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.op16_price_refresh import refresh_op16


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--actor-user-id", type=UUID)
    identity.add_argument("--from-settings", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-seconds", type=int, default=90)
    parser.add_argument("--report-file", type=Path)
    args = parser.parse_args()
    if not 1 <= args.max_seconds <= 90:
        parser.error("--max-seconds must be between 1 and 90")
    from app.db import create_pool
    from app.fx import EcbHistoricalFxProvider
    from app.settings import get_settings
    settings = get_settings()
    if not settings.pokewallet_api_key:
        parser.error("The existing Pokewallet integration is not configured")
    actor = args.actor_user_id or UUID(settings.catalogue_maintenance_actor_user_id)
    pool = await create_pool(settings)
    try:
        report = await refresh_op16(pool, actor,
            EcbHistoricalFxProvider(timeout_seconds=8), settings.pokewallet_api_key,
            apply=args.apply, max_seconds=args.max_seconds)
    finally:
        await pool.close()
    if args.report_file:
        args.report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    for row in report.get("preview", []):
        print("OP16_PRICE_PREVIEW " + json.dumps(row, sort_keys=True), flush=True)
    for row in report.get("committed", []):
        print("OP16_PRICE_COMMITTED " + json.dumps(row, sort_keys=True), flush=True)
    summary = {key: value for key, value in report.items() if key not in {"preview", "committed"}}
    print("OP16_PRICE_FILL " + json.dumps(summary, sort_keys=True), flush=True)
    return 0 if report["status"] in {"VERIFIED", "COMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
