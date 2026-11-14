"""Append-only logical CardTrader preflight audit in the existing catalogue job ledger.

The audit row is the ONLY database write made by the probe. No write to
reference prices, inventory, Shopify, ownership, or sales is allowed.
The distinct job label prevents pollution of CARDTRADER_EXPANSION_GUIDES's
production apply/dry-run cursor and unlock logic.
"""
from __future__ import annotations

import json
from uuid import UUID

from .access_control import require_platform_admin
from .db import user_connection

JOB = "CARDTRADER_SOURCE_PREFLIGHT"


def safe_receipt(report):
    """Persist only the source preflight's already-sanitised aggregate report."""
    if not isinstance(report, dict):
        raise ValueError("Source receipt requires a structured report")
    if report.get("event") != "DROP_RATE_PRICING_SOURCE_PREFLIGHT":
        raise ValueError("Unknown receipt event")
    if report.get("status") not in {"RUNNING", "COMPLETE", "INCOMPLETE", "FAILED", "BLOCKED"}:
        raise ValueError("Unknown preflight status")
    if report.get("catalogue_price_writes", 0) != 0 or report.get("inventory_writes", 0) != 0:
        raise ValueError("Preflight may not publish prices")
    if report.get("store_price_writes", 0) != 0:
        raise ValueError("Preflight may not reprice Shopify")
    # Never accidentally record seller/token/raw-provider data on any path.
    allowed = {
        "event", "status", "source", "evidence_kind", "mode", "requested_expansions",
        "requests", "expansions", "canonical_references_examined", "exact_printings",
        "eligible_quotes", "provider_failures", "failure_class", "bulk_writer_hold_preserved",
        "cursor_moved", "by_release", "inventory_writes",
        "store_price_writes", "catalogue_price_writes", "error_class",
    }
    cleaned = {key: value for key, value in report.items() if key in allowed}
    if len(json.dumps(cleaned, ensure_ascii=False).encode()) > 8_000:
        raise ValueError("Source preflight receipt too large")
    return cleaned


async def begin_preflight_receipt(pool, actor: UUID, receipt_id: UUID, *, expansion_limit: int):
    if type(expansion_limit) is not int or not 1 <= expansion_limit <= 2:
        raise ValueError("Preflight receipt must be bounded")
    report = safe_receipt({
        "event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT", "status": "RUNNING",
        "source": "CARDTRADER_EXPANSION_ASKING", "mode": "DRY_RUN",
        "evidence_kind": "ACTIVE_ASKING_NOT_SOLD",
        "requested_expansions": expansion_limit,
        "bulk_writer_hold_preserved": True,
        "inventory_writes": 0, "store_price_writes": 0, "catalogue_price_writes": 0,
    })
    async with user_connection(pool, actor, "cardtrader-preflight-start-" + str(receipt_id)) as connection:
        await require_platform_admin(connection)
        await connection.execute("""
            insert into tcg.catalogue_job_runs
                (id,job,actor_user_id,status,report)
            values($1,$2,$3,'RUNNING',$4::jsonb)
        """, receipt_id, JOB, actor, json.dumps(report))
    return receipt_id


async def complete_preflight_receipt(pool, actor: UUID, receipt_id: UUID, report):
    verified = safe_receipt(report)
    state = verified["status"]
    db_status = "INCOMPLETE" if state == "BLOCKED" else state
    if db_status == "RUNNING":
        raise ValueError("Cannot complete an unfinished preflight")
    async with user_connection(pool, actor, "cardtrader-preflight-finish-" + str(receipt_id)) as connection:
        await require_platform_admin(connection)
        saved = await connection.fetchval("""
            update tcg.catalogue_job_runs
               set status=$3,finished_at=clock_timestamp(),report=$4::jsonb
             where id=$1 and job=$2 and actor_user_id=$5 and status='RUNNING'
             returning id
        """, receipt_id, JOB, db_status, json.dumps(verified), actor)
        if saved != receipt_id:
            raise RuntimeError("Preflight receipt missing or already terminal")
    return receipt_id
