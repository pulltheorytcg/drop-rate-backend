from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from .shopify_client import ShopifyAdminClient

DEFAULT_RECONCILIATION_LOOKBACK = timedelta(days=30)
PAID_LIKE_STATUSES = frozenset(
    {"PAID", "PARTIALLY_PAID", "PARTIALLY_REFUNDED", "REFUNDED"}
)


async def reconcile_shopify_orders(
    connection: asyncpg.Connection,
    *,
    client: ShopifyAdminClient,
    now: datetime | None = None,
    lookback: timedelta = DEFAULT_RECONCILIATION_LOOKBACK,
) -> dict[str, Any]:
    if lookback < timedelta(hours=1) or lookback > timedelta(days=60):
        raise ValueError("Shopify reconciliation lookback must be between 1 hour and 60 days")

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
            from tcg.shopify_orders_for_reconciliation($1)
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
        matched_refs = set(remote_refs & local_refs)

        webhook_rows = []
        if remote_only_refs:
            webhook_rows = await connection.fetch(
                """
                select resource_id,topic,status
                from tcg.shopify_webhook_events
                where resource_id=any($1::text[])
                  and topic in ('orders/create','orders/paid','orders/cancelled')
                  and status in ('RECEIVED','PROCESSED','FAILED')
                order by resource_id,received_at,webhook_id
                """,
                remote_only_refs,
            )

        processed_create_refs = {
            str(row["resource_id"])
            for row in webhook_rows
            if row["topic"] == "orders/create" and row["status"] == "PROCESSED"
        }
        processed_cancelled_refs = {
            str(row["resource_id"])
            for row in webhook_rows
            if row["topic"] == "orders/cancelled" and row["status"] == "PROCESSED"
        }

        remote_alerts: list[dict[str, Any]] = []
        expected_pending_refs: list[str] = []
        acknowledged_cancelled_refs: list[str] = []
        for source_reference in remote_only_refs:
            order = remote_by_ref[source_reference]
            financial_status = str(order.get("financial_status") or "").upper()
            if financial_status in PAID_LIKE_STATUSES:
                remote_alerts.append(
                    {
                        **order,
                        "alert_code": "SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE",
                        "severity": "CRITICAL",
                    }
                )
                continue

            cancelled_at = str(order.get("cancelled_at") or "").strip()
            if cancelled_at and source_reference in processed_cancelled_refs:
                acknowledged_cancelled_refs.append(source_reference)
                matched_refs.add(source_reference)
                continue

            if source_reference not in processed_create_refs:
                remote_alerts.append(
                    {
                        **order,
                        "alert_code": "SHOPIFY_ORDER_WEBHOOK_GAP",
                        "severity": "HIGH",
                    }
                )
                continue

            # Unpaid Shopify orders are intentionally not inserted into tcg.orders.
            # A successfully processed orders/create webhook is the expected proof
            # that Drop Rate saw and reserved the order while payment is pending.
            expected_pending_refs.append(source_reference)
            matched_refs.add(source_reference)

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
            json.dumps(remote_alerts, sort_keys=True, separators=(",", ":")),
            local_only_ids,
            sorted(matched_refs),
        )
        if result is None:
            raise RuntimeError("Shopify reconciliation persistence returned no result")

    return {
        "window_start": window_start,
        "remote_count": len(remote_orders),
        "local_count": len(local_rows),
        "remote_only_count": len(remote_only_refs),
        "remote_anomaly_count": len(remote_alerts),
        "expected_pending_count": len(expected_pending_refs),
        "acknowledged_cancelled_count": len(acknowledged_cancelled_refs),
        "local_only_count": len(local_only_refs),
        "matched_count": len(matched_refs),
        "opened_alerts": int(result["opened_alerts"] or 0),
        "resolved_alerts": int(result["resolved_alerts"] or 0),
        "remote_only_refs": remote_only_refs,
        "remote_anomaly_refs": [
            str(item["source_reference"]) for item in remote_alerts
        ],
        "expected_pending_refs": expected_pending_refs,
        "acknowledged_cancelled_refs": acknowledged_cancelled_refs,
        "local_only_refs": local_only_refs,
    }
