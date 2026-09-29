from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from .shopify_client import ShopifyAdminClient

DEFAULT_RECONCILIATION_LOOKBACK = timedelta(days=7)


async def reconcile_shopify_orders(
    connection: asyncpg.Connection,
    *,
    client: ShopifyAdminClient,
    now: datetime | None = None,
    lookback: timedelta = DEFAULT_RECONCILIATION_LOOKBACK,
) -> dict[str, Any]:
    if lookback < timedelta(hours=1) or lookback > timedelta(days=30):
        raise ValueError("Shopify reconciliation lookback must be between 1 hour and 30 days")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_start = current - lookback

    # Fetch Shopify completely before any reconciliation writes. If Shopify is
    # unavailable or pagination is incomplete, the run fails closed and leaves
    # existing alerts untouched.
    remote_orders = await client.list_orders_for_reconciliation(
        created_at_gte=window_start,
    )

    remote_by_ref: dict[str, dict[str, Any]] = {}
    for order in remote_orders:
        source_reference = str(order.get("source_reference") or "").strip()
        if source_reference in remote_by_ref:
            raise RuntimeError(
                "Shopify reconciliation returned a duplicate order reference"
            )
        remote_by_ref[source_reference] = order

    async with connection.transaction():
        local_rows = await connection.fetch(
            """
            select id,source_reference,order_number,status,placed_at
            from tcg.orders
            where source='SHOPIFY'
              and placed_at >= $1
            order by placed_at,id
            """,
            window_start,
        )
        local_by_ref = {
            str(row["source_reference"]): row
            for row in local_rows
        }

        remote_refs = set(remote_by_ref)
        local_refs = set(local_by_ref)
        remote_only_refs = sorted(remote_refs - local_refs)
        local_only_refs = sorted(local_refs - remote_refs)
        matched_refs = sorted(remote_refs & local_refs)

        remote_only = [
            remote_by_ref[source_reference]
            for source_reference in remote_only_refs
        ]
        local_only_ids = [
            local_by_ref[source_reference]["id"]
            for source_reference in local_only_refs
        ]

        result = await connection.fetchrow(
            """
            select *
            from tcg.record_shopify_order_reconciliation(
              $1::jsonb,
              $2::uuid[],
              $3::text[]
            )
            """,
            json.dumps(remote_only, sort_keys=True, separators=(",", ":")),
            local_only_ids,
            matched_refs,
        )
        if result is None:
            raise RuntimeError("Shopify reconciliation persistence returned no result")

    return {
        "window_start": window_start,
        "remote_count": len(remote_orders),
        "local_count": len(local_rows),
        "remote_only_count": len(remote_only_refs),
        "local_only_count": len(local_only_refs),
        "matched_count": len(matched_refs),
        "opened_alerts": int(result["opened_alerts"] or 0),
        "resolved_alerts": int(result["resolved_alerts"] or 0),
        "remote_only_refs": remote_only_refs,
        "local_only_refs": local_only_refs,
    }
