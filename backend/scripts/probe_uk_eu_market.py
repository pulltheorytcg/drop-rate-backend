"""Bounded, transient Browse/Cardmarket probe. No database price or run writes.

The default is a zero-I/O plan. --run reads exact references under founder
authorization, takes the shared acquisition lock, and consumes at most 25
Browse GETs after checking the provider quota. It never invokes backfill writes
or changes the database-capacity guard.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.access_control import require_platform_admin
from app.db import create_pool, user_connection
from app.ebay_official_client import EbayApiError, EbayOfficialClient
from app.reference_asking_backfill import (
    BackfillStop, GROUP_COUNT, LOCK_NAME, allow_quota_request,
    bounded_item_detail, item_detail_candidates, quota_windows,
    read_browse_quota, search_query,
)
from app.reference_asking_estimator import (
    estimate_reference_asking_price, reference_asking_eligibility,
)
from app.settings import Settings

KEYS = ("provider", "system_code", "language", "provider_id")
MAX_REFERENCES = 3
MAX_REQUESTS = 25
READ_SQL = f"""select r.*,s.name as set_name,{GROUP_COUNT},
 coalesce(p.quotes,'[]'::jsonb) as quotes,
 coalesce(b.quotes,'[]'::jsonb) as catalogue_quotes
from jsonb_to_recordset($1::jsonb) as k(
 provider text,system_code text,language text,provider_id text)
join tcg.reference_cards r using(provider,system_code,language,provider_id)
join tcg.reference_sets s using(provider,system_code,language,set_id)
left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
where s.release_date is null or s.release_date<=current_date"""


def utcnow():
    return datetime.now(timezone.utc)


def reference_keys(values):
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_REFERENCES:
        raise ValueError("Select between one and three exact reference keys")
    result = []
    for value in values:
        key = json.loads(value) if isinstance(value, str) else value
        if (not isinstance(key, list) or len(key) != 4
                or any(not isinstance(v, str) or not v.strip() or v != v.strip()
                       or len(v) > 512 or any(ord(c) < 32 for c in v) for v in key)):
            raise ValueError("Each reference key must be a four-part JSON text array")
        if key in result:
            raise ValueError("Duplicate reference keys are not allowed")
        result.append(key)
    return result


def report_base(keys, max_requests, *, run):
    if type(max_requests) is not int or not 1 <= max_requests <= MAX_REQUESTS:
        raise ValueError("max_requests must be between 1 and 25")
    return {"status": "RUNNING" if run else "PLAN_ONLY", "reference_keys": keys,
            "max_requests": max_requests, "requests": 0, "search_requests": 0,
            "detail_requests": 0, "database_writes": 0, "price_writes": 0,
            "inventory_writes": 0, "store_price_writes": 0, "results": []}


def model_estimate(reference, browse_report, *, now):
    from app.uk_eu_reference_display import estimate_from_reference
    return estimate_from_reference(reference, browse_report, now=now)


async def probe_references(references, client, *, max_requests=25,
                           quota_reader=read_browse_quota, clock=utcnow,
                           sleep=asyncio.sleep, monotonic=time.monotonic,
                           estimator=estimate_reference_asking_price,
                           model=model_estimate):
    """Finite network-only probe; no connection or storage capability is passed."""
    keys = reference_keys([[r.get(k) for k in KEYS] for r in references])
    report = report_base(keys, max_requests, run=True)
    next_request = monotonic()
    windows = []

    async def request(operation, kind):
        nonlocal next_request
        if report["requests"] >= max_requests:
            raise BackfillStop("REQUEST_LIMIT")
        delay = next_request - monotonic()
        if delay > 0:
            await sleep(delay)
        allow_quota_request(windows, report["requests"], clock())
        # Reserve the operation before calling the client. Failed calls remain
        # counted; neither the client nor this probe retries a Browse request.
        report["requests"] += 1
        report[kind] += 1
        next_request = monotonic() + 1.0
        return await operation()

    try:
        windows = quota_windows(await quota_reader(client), now=clock())
        report["quota"] = [{k: w[k] for k in ("remaining", "limit", "reset")}
                           for w in windows]
        for reference in references:
            entry = {"reference_key": [reference[k] for k in KEYS],
                     "status": "PENDING", "summaries": 0, "details": 0}
            report["results"].append(entry)
            reason = reference_asking_eligibility(reference)
            if reason:
                entry.update(status="IDENTITY_UNSUPPORTED", reason=reason)
                continue
            payload = await request(lambda: client.search_items(
                query=search_query(reference), limit=100,
                item_location_country="GB", fixed_price_only=True), "search_requests")
            observed = clock()
            summaries = payload.get("itemSummaries", []) if isinstance(payload, dict) else None
            if not isinstance(summaries, list) or len(summaries) > 100:
                raise BackfillStop("INVALID_BROWSE_SUMMARIES")
            entry["summaries"] = len(summaries)
            details = []
            for item_id in item_detail_candidates(reference, summaries):
                payload = await request(lambda: client.get_item(item_id), "detail_requests")
                detail = bounded_item_detail(payload, item_id)
                if detail is not None:
                    details.append(detail)
            entry["details"] = len(details)
            estimate = estimator(reference, details, observed_at=observed, now=clock())
            entry.update(status=estimate["status"], observed_at=estimate.get("observed_at"),
                         sample_count=estimate.get("sample_count", 0),
                         seller_count=estimate.get("seller_count", 0),
                         selected_finish=estimate.get("selected_finish"),
                         rejection_counts=estimate.get("rejection_counts", {}))
            if estimate["status"] == "READY":
                entry["asking_delivered_minor"] = estimate["estimate_minor"]
                combined = model(reference, estimate, now=clock())
                entry["model_status"] = combined.get("status") if isinstance(combined, dict) else "NO_COMPARABLE_CARDMARKET_GUIDE"
                if isinstance(combined, dict) and combined.get("status") == "READY":
                    entry["model"] = {k: combined[k] for k in (
                        "method", "method_version", "estimate_minor", "estimate_low_minor",
                        "estimate_high_minor", "confidence", "observed_at", "expires_at",
                        "shipping_basis", "physical_valuation_eligible") if k in combined}
        report["status"] = "COMPLETE"
    except BackfillStop as exc:
        report.update(status="STOPPED", stop_reason=exc.code)
    except EbayApiError as exc:
        report.update(status="STOPPED", stop_reason="EBAY_PROVIDER_ERROR",
                      provider_status=exc.status_code,
                      retry_after_seconds=exc.retry_after_seconds)
    except Exception as exc:
        report.update(status="FAILED", stop_reason="PROBE_OPERATION_FAILED",
                      error_class=type(exc).__name__)
    report["finished_at"] = clock().isoformat()
    return report


async def run_probe(settings, keys, *, max_requests):
    actor = UUID(settings.catalogue_maintenance_actor_user_id or "")
    if settings.ebay_marketplace_id != "EBAY_GB":
        raise ValueError("The UK probe requires EBAY_GB")
    client = EbayOfficialClient(client_id=settings.ebay_client_id or "",
        client_secret=settings.ebay_client_secret or "", marketplace_id="EBAY_GB",
        buyer_country="GB", buyer_postal_code=settings.ebay_origin_postcode)
    pool = await create_pool(settings)
    try:
        # Complete the actor-scoped read before HTTP, avoiding a long idle
        # transaction and working even when the configured pool has one slot.
        async with user_connection(pool, actor, "uk-eu-readonly-probe", readonly_snapshot=True) as connection:
            await require_platform_admin(connection)
            rows = await connection.fetch(READ_SQL, json.dumps([dict(zip(KEYS, k)) for k in keys]))
        by_key = {tuple(row[k] for k in KEYS): dict(row) for row in rows}
        if len(by_key) != len(keys) or any(tuple(k) not in by_key for k in keys):
            report = report_base(keys, max_requests, run=True)
            return dict(report, status="STOPPED", stop_reason="EXACT_REFERENCE_UNAVAILABLE")
        async with pool.acquire() as connection:
            locked = await connection.fetchval("select pg_try_advisory_lock(hashtextextended($1,0))", LOCK_NAME)
            if not locked:
                return dict(report_base(keys, max_requests, run=True), status="STOPPED",
                            stop_reason="BACKFILL_ALREADY_RUNNING")
            try:
                return await probe_references([by_key[tuple(k)] for k in keys], client,
                                              max_requests=max_requests)
            finally:
                await connection.fetchval("select pg_advisory_unlock(hashtextextended($1,0))", LOCK_NAME)
    finally:
        await pool.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-key", action="append", required=True,
                        help='JSON array: [provider,system_code,language,provider_id]')
    parser.add_argument("--max-requests", type=int, default=25)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    try:
        keys = reference_keys(args.reference_key)
        report = report_base(keys, args.max_requests, run=args.run)
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))
    if args.run:
        try:
            report = asyncio.run(run_probe(Settings.from_env(), keys, max_requests=args.max_requests))
        except Exception as exc:
            report.update(status="FAILED", stop_reason="PROBE_SETUP_FAILED", error_class=type(exc).__name__)
    print(json.dumps(report, sort_keys=True, default=str))
    return 0 if report["status"] in {"PLAN_ONLY", "COMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
