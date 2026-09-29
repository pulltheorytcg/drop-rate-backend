from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from app.shopify_client import ShopifyAdminClient, ShopifyApiError
from app.shopify_reconciliation import reconcile_shopify_orders


ROOT = Path(__file__).parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260929021000_shopify_order_reconciliation.sql"
)
RUNNER = ROOT / "backend" / "scripts" / "reconcile_shopify_orders.py"
MONITOR = ROOT / "backend" / "scripts" / "run_operations_monitor.py"


@pytest.mark.asyncio
async def test_shopify_reconciliation_order_query_paginates_and_excludes_customer_pii() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    calls: list[tuple[str, dict | None]] = []

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        calls.append((query, variables))
        if (variables or {}).get("after") is None:
            return {
                "orders": {
                    "nodes": [{
                        "id": "gid://shopify/Order/1001",
                        "name": "#1001",
                        "createdAt": "2026-09-24T23:04:48Z",
                        "cancelledAt": "2026-09-24T23:20:36Z",
                        "displayFinancialStatus": "PENDING",
                    }],
                    "pageInfo": {"hasNextPage": True, "endCursor": "next"},
                }
            }
        return {
            "orders": {
                "nodes": [{
                    "id": "gid://shopify/Order/1002",
                    "name": "#1002",
                    "createdAt": "2026-09-24T23:38:57Z",
                    "cancelledAt": None,
                    "displayFinancialStatus": "REFUNDED",
                }],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    orders = await client.list_orders_for_reconciliation(
        created_at_gte=datetime(2026, 9, 22, tzinfo=timezone.utc),
    )

    assert [item["source_reference"] for item in orders] == ["1001", "1002"]
    assert calls[0][1] == {
        "first": 100,
        "after": None,
        "query": "created_at:>='2026-09-22T00:00:00Z'",
    }
    assert calls[1][1]["after"] == "next"
    query = calls[0][0].casefold()
    for pii_field in ("customer", "email", "shippingaddress", "billingaddress", "phone"):
        assert pii_field not in query


@pytest.mark.asyncio
async def test_shopify_reconciliation_pagination_fails_closed() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        return {
            "orders": {
                "nodes": [],
                "pageInfo": {"hasNextPage": True, "endCursor": "loop"},
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    with pytest.raises(ShopifyApiError, match="safety limit"):
        await client.list_orders_for_reconciliation(
            created_at_gte=datetime(2026, 9, 22, tzinfo=timezone.utc),
            max_pages=2,
        )


class FakeClient:
    async def list_orders_for_reconciliation(self, *, created_at_gte):
        return [
            {
                "source_reference": "1001",
                "order_number": "#1001",
                "created_at": "2026-09-24T23:04:48Z",
                "cancelled_at": "2026-09-24T23:20:36Z",
                "financial_status": "PENDING",
            },
            {
                "source_reference": "1002",
                "order_number": "#1002",
                "created_at": "2026-09-24T23:38:57Z",
                "cancelled_at": "2026-09-26T15:33:02Z",
                "financial_status": "REFUNDED",
            },
            {
                "source_reference": "1003",
                "order_number": "#1003",
                "created_at": "2026-09-25T10:00:00Z",
                "cancelled_at": None,
                "financial_status": "PAID",
            },
            {
                "source_reference": "1004",
                "order_number": "#1004",
                "created_at": "2026-09-25T11:00:00Z",
                "cancelled_at": None,
                "financial_status": "PENDING",
            },
        ]


class FakeConnection:
    def __init__(self):
        self.persisted = None
        self.window_start = None
        self.webhook_refs = None

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetch(self, query: str, *args):
        if "from tcg.orders" in query:
            self.window_start = args[0]
            return [
                {
                    "id": UUID("11111111-1111-1111-1111-111111111111"),
                    "source_reference": "1002",
                    "order_number": "#1002",
                    "status": "CANCELLED",
                    "placed_at": datetime(2026, 9, 24, 23, 38, tzinfo=timezone.utc),
                },
                {
                    "id": UUID("22222222-2222-2222-2222-222222222222"),
                    "source_reference": "9000",
                    "order_number": "#9000",
                    "status": "PAID",
                    "placed_at": datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
                },
            ]
        if "from tcg.shopify_webhook_events" in query:
            self.webhook_refs = args[0]
            return [
                {
                    "resource_id": "1001",
                    "topic": "orders/cancelled",
                    "status": "PROCESSED",
                },
                {
                    "resource_id": "1004",
                    "topic": "orders/create",
                    "status": "PROCESSED",
                },
            ]
        raise AssertionError("unexpected query")

    async def fetchrow(self, query: str, *args):
        assert "record_shopify_order_reconciliation" in query
        self.persisted = args
        return {"opened_alerts": 6, "resolved_alerts": 0}


@pytest.mark.asyncio
async def test_reconciliation_is_payment_and_webhook_aware() -> None:
    connection = FakeConnection()
    result = await reconcile_shopify_orders(
        connection,  # type: ignore[arg-type]
        client=FakeClient(),  # type: ignore[arg-type]
        now=datetime(2026, 9, 29, tzinfo=timezone.utc),
    )

    assert connection.window_start == datetime(2026, 8, 30, tzinfo=timezone.utc)
    assert result["remote_only_refs"] == ["1001", "1003", "1004"]
    assert result["remote_anomaly_refs"] == ["1001", "1003"]
    assert result["expected_pending_refs"] == ["1004"]
    assert result["expected_pending_count"] == 1
    assert result["local_only_refs"] == ["9000"]
    assert result["matched_count"] == 2
    assert result["opened_alerts"] == 6

    assert connection.persisted is not None
    remote_alerts = json.loads(connection.persisted[0])
    assert [item["source_reference"] for item in remote_alerts] == ["1001", "1003"]
    assert remote_alerts[0]["alert_code"] == "SHOPIFY_ORDER_WEBHOOK_GAP"
    assert remote_alerts[0]["severity"] == "HIGH"
    assert remote_alerts[1]["alert_code"] == "SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE"
    assert remote_alerts[1]["severity"] == "CRITICAL"
    assert connection.persisted[1] == [
        UUID("22222222-2222-2222-2222-222222222222")
    ]
    assert connection.persisted[2] == ["1002", "1004"]


@pytest.mark.asyncio
async def test_reconciliation_shopify_failure_performs_no_database_work() -> None:
    class FailedClient:
        async def list_orders_for_reconciliation(self, *, created_at_gte):
            raise ShopifyApiError("upstream failed", retryable=True)

    class UntouchedConnection:
        def transaction(self):
            raise AssertionError("database transaction must not start after Shopify failure")

    with pytest.raises(ShopifyApiError):
        await reconcile_shopify_orders(
            UntouchedConnection(),  # type: ignore[arg-type]
            client=FailedClient(),  # type: ignore[arg-type]
            now=datetime(2026, 9, 29, tzinfo=timezone.utc),
        )


def test_reconciliation_lookback_fails_closed_outside_bounds() -> None:
    with pytest.raises(ValueError, match="between 1 hour and 60 days"):
        import asyncio
        asyncio.run(
            reconcile_shopify_orders(
                FakeConnection(),  # type: ignore[arg-type]
                client=FakeClient(),  # type: ignore[arg-type]
                lookback=timedelta(days=61),
            )
        )


def test_reconciliation_migration_is_founder_scoped_and_api_only() -> None:
    sql = MIGRATION.read_text().casefold()
    compact = sql.replace(" ", "").replace("\n", "")

    assert "security definer" in sql
    assert "shopify_paid_order_missing_in_drop_rate" in sql
    assert "shopify_order_webhook_gap" in sql
    assert "drop_rate_order_missing_in_shopify" in sql
    assert "owner_type='founder'" in compact
    assert "fromservice_role" in compact
    assert (
        "grantexecuteonfunctiontcg.record_shopify_order_reconciliation"
        "(jsonb,uuid[],text[])totcg_api"
    ) in compact


def test_reconciliation_runner_does_not_log_secrets_or_customer_data() -> None:
    source = RUNNER.read_text()
    assert "SHOPIFY_ORDER_RECONCILIATION_COMPLETE" in source
    assert "database_url_configured" in source
    assert "shopify_client_secret_configured" in source
    assert "print(database_url)" not in source
    assert '"detail": str(exc)' not in source
    assert "customer_email" not in source
    assert "shipping_address" not in source


def test_operations_monitor_runs_both_checks_without_embedding_business_logic() -> None:
    source = MONITOR.read_text()
    assert 'check_payout_scheduler_heartbeat.py' in source
    assert 'reconcile_shopify_orders.py' in source
    assert "subprocess.run" in source
    assert "tcg.orders" not in source
    assert "ShopifyAdminClient" not in source
