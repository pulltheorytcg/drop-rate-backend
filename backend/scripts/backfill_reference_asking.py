"""Plan missing reference searches, or explicitly collect/apply asking estimates.

Default is database-read-only planning. --run creates a durable run receipt and
makes at most 25 Browse searches (override <=500). --apply additionally writes
only validated READY estimates to separate asking history/cache. No scheduling.
--resume-run skips all previously reserved references, including uncertain calls.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import create_pool
from app.ebay_official_client import EbayOfficialClient
from app.reference_asking_backfill import GAMES, backfill_reference_asking
from app.settings import get_settings


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actor = parser.add_mutually_exclusive_group(required=True)
    actor.add_argument("--actor-user-id", type=UUID)
    actor.add_argument("--from-settings", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-queries", type=int, default=25)
    parser.add_argument("--resume-run", type=UUID)
    parser.add_argument("--system-code", choices=sorted(GAMES))
    parser.add_argument("--language", choices=("English", "Japanese", "Chinese", "Korean", "French", "German", "Italian", "Spanish", "Portuguese"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.max_queries <= 500:
        parser.error("--max-queries must be 1..500")
    if (args.apply or args.resume_run) and not args.run:
        parser.error("--apply and --resume-run require explicit --run")
    if args.output is not None and args.output.exists():
        parser.error("Output already exists; use a new checkpoint filename")
    return args


async def run_cli(args):
    path, started = args.output, False
    invocation = uuid4().hex[:8]

    def checkpoint(report):
        nonlocal path, started
        if path is None:
            path = Path(tempfile.gettempdir()) / ("reference-asking-" + report["run_id"] + "-" + invocation + ".json")
        if not started:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as handle:
                handle.write("{}\n")
            started = True
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    pool = None
    try:
        settings = get_settings()
        actor = args.actor_user_id or UUID(settings.catalogue_maintenance_actor_user_id or "")
        client = None
        if args.run:
            if settings.ebay_marketplace_id != "EBAY_GB":
                raise ValueError("The backfill requires the configured UK marketplace")
            client = EbayOfficialClient(client_id=settings.ebay_client_id or "", client_secret=settings.ebay_client_secret or "",
                marketplace_id="EBAY_GB", timeout_seconds=20,
                buyer_country="GB", buyer_postal_code=settings.ebay_origin_postcode)
        pool = await create_pool(settings)
        report = await backfill_reference_asking(pool, actor, client, run=args.run, apply=args.apply,
            max_queries=args.max_queries, resume_run=args.resume_run, system_code=args.system_code,
            language=args.language, postcode=settings.ebay_origin_postcode, checkpoint=checkpoint)
    except Exception as exc:
        report = {"status": "FAILED", "run_id": str(args.resume_run or uuid4()),
                  "stop_reason": getattr(exc, "code", "BACKFILL_START_FAILED"), "error_class": type(exc).__name__}
        checkpoint(report)
    finally:
        if pool is not None:
            await pool.close()
    summary = {key: report[key] for key in ("status", "run_id", "requests", "session_requests", "stats", "stop_reason", "receipt_persistence_error") if key in report}
    summary["checkpoint_file"] = str(path)
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if report["status"] in {"PLAN_ONLY", "COMPLETE", "INCOMPLETE"} and not report.get("receipt_persistence_error") else 2


def main():
    return asyncio.run(run_cli(arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
