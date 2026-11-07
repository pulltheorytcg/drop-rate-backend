"""Seller Hub to Shopify integration is gated and never broadens consent."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.seller_hub_shopify_sync import (
    SELLER_HUB_SHOPIFY_TAG,
    process_shopify_waitlist_batch,
    upsert_tagged_shopify_contact,
)
from app.shopify_client import ShopifyApiError


CUSTOMER_GID = "gid://shopify/Customer/12345"
MIGRATION = (Path(__file__).parents[1] / "database/migrations/20261031210000_seller_hub_shopify_contact_sync.sql")


class FakeShopify:
    def __init__(self, *, fail: str | None = None):
        self.calls = []
        self.fail = fail

    async def graphql(self, *, query, variables):
        self.calls.append((query, variables))
        if "customerSet" in query:
            if self.fail == "upsert":
                return {"customerSet": {"customer": None, "userErrors": [{"message": "bad email"}]}}
            if self.fail == "invalid_id":
                return {"customerSet": {"customer": {"id": "bad/customer"}, "userErrors": []}}
            return {"customerSet": {"customer": {"id": CUSTOMER_GID}, "userErrors": []}}
        if "tagsAdd" in query:
            if self.fail == "tag":
                return {"tagsAdd": {"node": None, "userErrors": [{"message": "API failure"}]}}
            if self.fail == "wrong_id":
                return {"tagsAdd": {"node": {"id": "gid://shopify/Customer/99"}, "userErrors": []}}
            return {"tagsAdd": {"node": {"id": CUSTOMER_GID}, "userErrors": []}}
        raise AssertionError("Unexpected Shopify mutation")


@pytest.mark.asyncio
async def test_shopify_customer_upsert_is_email_idempotent_and_tag_is_additive():
    shopify = FakeShopify()
    for _ in range(2):
        assert await upsert_tagged_shopify_contact(shopify, "seller@example.com") == CUSTOMER_GID
    assert len(shopify.calls) == 4
    upsert_query, upsert_vars = shopify.calls[0]
    tag_query, tag_vars = shopify.calls[1]
    assert upsert_vars == {"identifier": {"email": "seller@example.com"}, "input": {"email": "seller@example.com"}}
    assert "emailMarketingConsent" not in upsert_query
    assert "tags:" not in str(upsert_vars) and "firstName" not in str(upsert_vars)
    assert "tagsAdd" in tag_query
    assert tag_vars == {"id": CUSTOMER_GID, "tags": [SELLER_HUB_SHOPIFY_TAG]}


@pytest.mark.asyncio
@pytest.mark.parametrize("fail, expected_calls", [("upsert", 1), ("invalid_id", 1), ("tag", 2), ("wrong_id", 2)])
async def test_shopify_rejects_ambiguous_or_partial_mutation_without_false_ack(fail, expected_calls):
    shopify = FakeShopify(fail=fail)
    with pytest.raises(ShopifyApiError):
        await upsert_tagged_shopify_contact(shopify, "seller@example.com")
    assert len(shopify.calls) == expected_calls


class FakePool:
    def __init__(self, rows, *, ack: bool = True):
        self.rows = rows
        self.ack = ack
        self.operations = []

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def fetch(self, query, *args):
        self.operations.append((query, args))
        return self.rows

    async def fetchval(self, query, *args):
        self.operations.append((query, args))
        return self.ack


@pytest.mark.asyncio
async def test_durable_claim_and_ack_only_after_both_mutations_succeed():
    waitlist_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    token = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    pool = FakePool([{"waitlist_id": waitlist_id, "lease_token": token, "contact_email": "seller@example.com"}])
    claimed, success = await process_shopify_waitlist_batch(pool, FakeShopify())
    assert (claimed, success) == (1, 1)
    assert "claim_seller_hub_shopify_sync" in pool.operations[0][0]
    assert "finish_seller_hub_shopify_sync" in pool.operations[1][0]
    assert pool.operations[1][1] == (waitlist_id, token, CUSTOMER_GID)


@pytest.mark.asyncio
async def test_partial_failure_is_nacked_for_retry_and_stale_ack_not_counted():
    pool = FakePool([{"waitlist_id": UUID(int=1), "lease_token": UUID(int=2), "contact_email": "seller@example.com"}])
    assert await process_shopify_waitlist_batch(pool, FakeShopify(fail="tag")) == (1, 0)
    assert pool.operations[1][1][-1] is None
    pool.ack = False
    assert await process_shopify_waitlist_batch(pool, FakeShopify()) == (1, 0)


@pytest.mark.asyncio
async def test_empty_outbox_never_calls_shopify():
    pool = FakePool([])
    shopify = FakeShopify()
    assert await process_shopify_waitlist_batch(pool, shopify) == (0, 0)
    assert shopify.calls == []


def test_private_sql_only_newly_disclosed_optins_are_exportable():
    sql = MIGRATION.read_text().lower()
    assert "default 'not_requested'" in sql
    assert "register_seller_hub_interest_for_shopify" in sql
    assert "p_shopify_contact_consent is distinct from true" in sql
    assert "shopify_sync_state = 'not_requested'" in sql
    assert "for update skip locked" in sql
    assert "status <> 'unsubscribed'" in sql
    assert "shopify_lease_token = p_lease_token" in sql
    assert "revoke all on function tcg_private.claim_seller_hub_shopify_sync" in sql
    assert "grant execute on function tcg_private.finish_seller_hub_shopify_sync" in sql
    assert "drop table" not in sql and "disable row level security" not in sql
