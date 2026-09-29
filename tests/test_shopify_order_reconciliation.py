from __future__ import annotations

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
    def __init__(
        self,
        *,
        financial_status: str = "PENDING",
        source_reference: str = "8488414282075",
    ) -> None:
        self.financial_status = financial_status
        self.source_reference = source_reference

    async def list_orders_for_reconciliation(self, *, created_at_gte):
        return [
            {
                "source_reference": self.source_reference,
                "order_number": "#1001",
                "created_at": "2026-09-24T23:04:48Z",
                "cancelled_at": "2026-09-24T23:20:36Z",
                "financial_status": self.financial_status,
            }
        ]


class FakeConnection:
    def __init__(self, *, processed_create: bool = False, include_local: bool = True):
        self.persisted = None
        self.window_start = None
        self.processed_create = processed_create
        self.include_local = include_local
        self.fetch_queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetch(self, query: str, *args):
        self.fetch_queries.append(query)
        if "from tcg.shopify_webhook_events" in query:
            if self.processed_create:
                return [{
                    "resource_id": "8488414282075",
                    "topic": "orders/create",
                    "status": "PROCESSED",
                }]
            return []
        if "from tcg.shopify_orders_for_reconciliation" in query:
            self.window_start = args[0]
            if not self.include_local:
                return []
            return [{
                "id": UUID("11111111-1111-1111-1111-111111111111"),
                "source_reference": "8488435581275",
                "order_number": "#1002",
                "status": "CANCELLED",
                "placed_at": datetime(2026, 9, 24, 23, 38, tzinfo=timezone.utc),
            }]
        raise AssertionError(f"Unexpected query: {query}")

    async def fetchrow(self, query: str, *args):
        self.persisted = args
        return {"opened_alerts": 4, "resolved_alerts": 0}


@pytest.mark.asyncio
async def test_reconciliation_classifies_unpaid_missing_order_as_webhook_gap() -> None:
    connection = FakeConnection()
    result = await reconcile_shopify_orders(
        connection,  # type: ignore[arg-type]
        client=FakeClient(),  # type: ignore[arg-type]
        now=datetime(2026, 9, 29, tzinfo=timezone.utc),
        lookback=timedelta(days=7),
    )

    assert result["remote_only_refs"] == ["8488414282075"]
    assert result["remote_anomaly_refs"] == ["8488414282075"]
    assert result["expected_pending_refs"] == []
    assert result["local_only_refs"] == ["8488435581275"]
    assert connection.persisted is not None
    assert "SHOPIFY_ORDER_WEBHOOK_GAP" in connection.persisted[0]
    assert connection.persisted[1] == [
        UUID("11111111-1111-1111-1111-111111111111")
    ]
    assert connection.persisted[2] == []


@pytest.mark.asyncio
async def test_reconciliation_treats_processed_unpaid_create_as_expected_pending() -> None:
    connection = FakeConnection(processed_create=True, include_local=False)
    result = await reconcile_shopify_orders(
        connection,  # type: ignore[arg-type]
        client=FakeClient(),  # type: ignore[arg-type]
        now=datetime(2026, 9, 29, tzinfo=timezone.utc),
    )

    assert result["remote_only_refs"] == ["8488414282075"]
    assert result["remote_anomaly_refs"] == []
    assert result["expected_pending_refs"] == ["8488414282075"]
    assert result["remote_anomaly_count"] == 0
    assert result["expected_pending_count"] == 1
    assert connection.persisted is not None
    assert connection.persisted[0] == "[]"
    assert connection.persisted[1] == []
    assert connection.persisted[2] == ["8488414282075"]


@pytest.mark.asyncio
async def test_reconciliation_paid_like_missing_order_is_critical_even_with_create_webhook() -> None:
    connection = FakeConnection(processed_create=True, include_local=False)
    result = await reconcile_shopify_orders(
        connection,  # type: ignore[arg-type]
        client=FakeClient(financial_status="REFUNDED"),  # type: ignore[arg-type]
        now=datetime(2026, 9, 29, tzinfo=timezone.utc),
    )

    assert result["remote_anomaly_count"] == 1
    assert result["expected_pending_count"] == 0
    assert connection.persisted is not None
    assert "SHOPIFY_PAID_ORDER_MISSING_IN_DROP_RATE" in connection.persisted[0]
    assert '"severity":"CRITICAL"' in connection.persisted[0]


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


def test_reconciliation_rls_read_migration_is_narrow_and_api_only() -> None:
    migration = (
        ROOT
        / "database"
        / "migrations"
        / "20260929022000_shopify_reconciliation_rls_read.sql"
    )
    sql = migration.read_text().casefold()
    compact = sql.replace(" ", "").replace("\n", "")

    assert "security definer" in sql
    assert "stable" in sql
    assert "from tcg.orders o" in sql
    assert "where o.source='shopify'" in sql
    assert "owner_id" not in sql
    assert "customer" not in sql
    assert "billing" not in sql
    assert "shipping" not in sql
    assert "fromservice_role" in compact
    assert (
        "grantexecuteonfunctiontcg.shopify_orders_for_reconciliation"
        "(timestamptz)totcg_api"
    ) in compact


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
    assert '"remote_anomaly_count": result["remote_anomaly_count"]' in source
    assert '"expected_pending_count": result["expected_pending_count"]' in source
    assert "database_url_configured" in source
    assert "shopify_client_secret_configured" in source
    assert "print(database_url)" not in source
    assert '"detail": str(exc)' not in source
    assert "customer_email" not in source
    assert "shipping_address" not in source
