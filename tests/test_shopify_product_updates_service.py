from __future__ import annotations

from uuid import UUID

import pytest

import app.shopify_pipeline as pipeline
from app.shopify_client import ShopifyApiError


LINK_ID = UUID("11111111-1111-1111-1111-111111111111")
OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")
INVENTORY_ID = UUID("33333333-3333-3333-3333-333333333333")
CATALOGUE_ID = UUID("44444444-4444-4444-4444-444444444444")


def _candidate() -> dict:
    return {
        "link_id": str(LINK_ID),
        "link_version": 4,
        "owner_id": str(OWNER_ID),
        "shopify_product_gid": "gid://shopify/Product/10",
        "shopify_variant_gid": "gid://shopify/ProductVariant/20",
        "synced_price_minor": 500,
        "last_synced_at": "2026-09-30T00:00:00+00:00",
        "inventory_id": str(INVENTORY_ID),
        "inventory_version": 7,
        "catalogue_id": str(CATALOGUE_ID),
        "inventory_code": "INV-PKM-000001",
        "store_price_minor": 650,
    }


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


class FakeConnection:
    def __init__(self, *, candidate_batches, finalize_result=None):
        self.candidate_batches = list(candidate_batches)
        self.finalize_result = finalize_result
        self.candidate_calls = 0
        self.finalize_calls = 0
        self.finalize_args = None

    async def fetchval(self, query: str, *args):
        normalized = " ".join(query.split())
        if "shopify_price_sync_candidates" in normalized:
            self.candidate_calls += 1
            if self.candidate_batches:
                return self.candidate_batches.pop(0)
            return []
        if "finalize_shopify_price_sync" in normalized:
            self.finalize_calls += 1
            self.finalize_args = args
            return self.finalize_result
        raise AssertionError(f"Unexpected SQL: {normalized}")


class FakeShopify:
    def __init__(
        self,
        *,
        variant_id: str = "gid://shopify/ProductVariant/20",
        price: str = "6.50",
        error: Exception | None = None,
    ):
        self.variant_id = variant_id
        self.price = price
        self.error = error
        self.calls = []

    async def update_variant_price(self, *, product_id, variant_id, price):
        self.calls.append(
            {
                "product_id": product_id,
                "variant_id": variant_id,
                "price": price,
            }
        )
        if self.error:
            raise self.error
        return {"id": self.variant_id, "price": self.price}


@pytest.mark.asyncio
async def test_dr02_duplicate_second_run_is_a_pure_noop() -> None:
    candidate = _candidate()
    connection = FakeConnection(
        candidate_batches=[[candidate], []],
        finalize_result={
            "status": "SYNCED",
            "inventory_id": str(INVENTORY_ID),
            "inventory_code": "INV-PKM-000001",
            "previous_price_minor": 500,
            "synced_price_minor": 650,
            "link_version": 5,
        },
    )
    pool = FakePool(connection)
    client = FakeShopify()

    first = await pipeline.reconcile_shopify_product_prices(
        pool,
        client=client,
        limit=50,
        request_id="request-1",
    )
    second = await pipeline.reconcile_shopify_product_prices(
        pool,
        client=client,
        limit=50,
        request_id="request-2",
    )

    assert first["candidate_count"] == 1
    assert first["synced_count"] == 1
    assert first["failed_count"] == 0
    assert second["candidate_count"] == 0
    assert second["synced_count"] == 0
    assert len(client.calls) == 1
    assert connection.finalize_calls == 1


@pytest.mark.asyncio
async def test_dr02_shopify_variant_mismatch_never_finalizes_database() -> None:
    connection = FakeConnection(candidate_batches=[[_candidate()]])
    client = FakeShopify(variant_id="gid://shopify/ProductVariant/999")

    result = await pipeline.reconcile_shopify_product_prices(
        FakePool(connection),
        client=client,
        limit=50,
        request_id="request-mismatch",
    )

    assert result["failed_count"] == 1
    assert result["synced_count"] == 0
    assert result["results"][0]["status"] == "SHOPIFY_MISMATCH"
    assert connection.finalize_calls == 0


@pytest.mark.asyncio
async def test_dr02_shopify_failure_is_observable_and_never_finalizes() -> None:
    connection = FakeConnection(candidate_batches=[[_candidate()]])
    client = FakeShopify(error=ShopifyApiError("timeout", retryable=True))

    result = await pipeline.reconcile_shopify_product_prices(
        FakePool(connection),
        client=client,
        limit=50,
        request_id="request-timeout",
    )

    assert result["failed_count"] == 1
    assert result["results"][0]["status"] == "SHOPIFY_ERROR"
    assert result["results"][0]["retryable"] is True
    assert connection.finalize_calls == 0


@pytest.mark.asyncio
async def test_dr02_stale_post_shopify_state_requires_retry() -> None:
    connection = FakeConnection(
        candidate_batches=[[_candidate()]],
        finalize_result={
            "status": "RETRY_REQUIRED",
            "reason": "STATE_CHANGED",
            "inventory_id": str(INVENTORY_ID),
            "inventory_code": "INV-PKM-000001",
        },
    )
    client = FakeShopify()

    result = await pipeline.reconcile_shopify_product_prices(
        FakePool(connection),
        client=client,
        limit=50,
        request_id="request-stale",
    )

    assert result["failed_count"] == 0
    assert result["synced_count"] == 0
    assert result["retry_required_count"] == 1
    assert connection.finalize_calls == 1


@pytest.mark.asyncio
async def test_dr02_success_finalizes_exact_snapshot_and_price() -> None:
    candidate = _candidate()
    connection = FakeConnection(
        candidate_batches=[[candidate]],
        finalize_result={
            "status": "SYNCED",
            "inventory_id": str(INVENTORY_ID),
            "inventory_code": "INV-PKM-000001",
            "previous_price_minor": 500,
            "synced_price_minor": 650,
            "link_version": 5,
        },
    )
    client = FakeShopify()

    result = await pipeline.reconcile_shopify_product_prices(
        FakePool(connection),
        client=client,
        limit=50,
        request_id="request-success",
    )

    assert result["synced_count"] == 1
    assert connection.finalize_calls == 1
    assert connection.finalize_args == (
        str(LINK_ID),
        str(OWNER_ID),
        4,
        str(INVENTORY_ID),
        7,
        650,
        "request-success",
    )
    assert client.calls == [
        {
            "product_id": "gid://shopify/Product/10",
            "variant_id": "gid://shopify/ProductVariant/20",
            "price": "6.50",
        }
    ]
