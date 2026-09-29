from __future__ import annotations

import json
from uuid import UUID

import pytest

from app.shopify_copy_groups import (
    MAX_COPY_HANDLES,
    copy_group_metafields,
    product_handle_for_inventory,
    sync_shopify_copy_group_metadata,
)
from app.shopify_client import ShopifyAdminClient


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def fetch(self, query: str, *args):
        self.calls.append((query, args))
        return self.rows


class FakeClient:
    def __init__(self):
        self.calls = []

    async def set_product_metafields(self, *, product_id, metafields):
        self.calls.append((product_id, metafields))
        return metafields


def test_product_handle_for_inventory_is_deterministic() -> None:
    assert product_handle_for_inventory("INV-PKM-001 247") == "drop-rate-inv-pkm-001-247"
    with pytest.raises(ValueError, match="Inventory code"):
        product_handle_for_inventory("")


def test_copy_group_metafields_are_typed_and_bounded() -> None:
    rows = copy_group_metafields(
        catalogue_id="29e6be41-c8a4-407d-a12a-6cfbbfb19ae1",
        handles=["drop-rate-inv-1", "drop-rate-inv-2"],
        total_count=2,
    )
    by_key = {row["key"]: row for row in rows}

    assert by_key["catalogue_id"]["type"] == "single_line_text_field"
    assert by_key["copy_handles"]["type"] == "list.single_line_text_field"
    assert json.loads(by_key["copy_handles"]["value"]) == [
        "drop-rate-inv-1",
        "drop-rate-inv-2",
    ]
    assert by_key["copy_group_size"]["value"] == "2"
    assert by_key["copy_group_truncated"]["value"] == "false"

    with pytest.raises(ValueError, match="safety limit"):
        copy_group_metafields(
            catalogue_id="29e6be41-c8a4-407d-a12a-6cfbbfb19ae1",
            handles=[f"drop-rate-inv-{index}" for index in range(MAX_COPY_HANDLES + 1)],
            total_count=MAX_COPY_HANDLES + 1,
        )


@pytest.mark.asyncio
async def test_copy_group_sync_updates_every_published_sibling() -> None:
    connection = FakeConnection(
        [
            {
                "shopify_product_gid": "gid://shopify/Product/1",
                "inventory_code": "INV-OP-001",
                "store_price_minor": 124,
                "linked_at": None,
            },
            {
                "shopify_product_gid": "gid://shopify/Product/2",
                "inventory_code": "INV-OP-002",
                "store_price_minor": 150,
                "linked_at": None,
            },
        ]
    )
    client = FakeClient()

    result = await sync_shopify_copy_group_metadata(
        connection,
        client,  # type: ignore[arg-type]
        catalogue_id=UUID("29e6be41-c8a4-407d-a12a-6cfbbfb19ae1"),
    )

    assert result == {
        "status": "SYNCED",
        "catalogue_id": "29e6be41-c8a4-407d-a12a-6cfbbfb19ae1",
        "copies": 2,
        "updated_products": 2,
        "truncated": False,
    }
    assert len(client.calls) == 2

    for product_id, metafields in client.calls:
        assert product_id in {
            "gid://shopify/Product/1",
            "gid://shopify/Product/2",
        }
        by_key = {row["key"]: row for row in metafields}
        assert json.loads(by_key["copy_handles"]["value"]) == [
            "drop-rate-inv-op-001",
            "drop-rate-inv-op-002",
        ]
        assert by_key["copy_group_size"]["value"] == "2"

    query, args = connection.calls[0]
    assert "sil.sync_state='PUBLISHED'" in query
    assert "i.sale_intent='FOR_SALE'" in query
    assert "sil.sold_at is null" in query
    assert args == ("29e6be41-c8a4-407d-a12a-6cfbbfb19ae1",)


@pytest.mark.asyncio
async def test_copy_group_sync_keeps_current_copy_when_group_exceeds_liquid_limit() -> None:
    rows = [
        {
            "shopify_product_gid": f"gid://shopify/Product/{index}",
            "inventory_code": f"INV-{index:03d}",
            "store_price_minor": 100 + index,
            "linked_at": None,
        }
        for index in range(1, MAX_COPY_HANDLES + 2)
    ]
    connection = FakeConnection(rows)
    client = FakeClient()

    result = await sync_shopify_copy_group_metadata(
        connection,
        client,  # type: ignore[arg-type]
        catalogue_id="29e6be41-c8a4-407d-a12a-6cfbbfb19ae1",
    )

    assert result["truncated"] is True
    assert result["copies"] == MAX_COPY_HANDLES + 1

    last_product_id, last_metafields = client.calls[-1]
    assert last_product_id == f"gid://shopify/Product/{MAX_COPY_HANDLES + 1}"
    copy_handles = json.loads(
        {row["key"]: row for row in last_metafields}["copy_handles"]["value"]
    )
    assert len(copy_handles) == MAX_COPY_HANDLES
    assert f"drop-rate-inv-{MAX_COPY_HANDLES + 1:03d}" in copy_handles


@pytest.mark.asyncio
async def test_shopify_client_sets_metafields_without_exposing_credentials() -> None:
    client = ShopifyAdminClient(
        shop_domain="example.myshopify.com",
        client_id="client",
        client_secret="secret",
        api_version="2026-07",
    )
    captured = {}

    async def fake_graphql(*, query, variables=None):
        captured["query"] = query
        captured["variables"] = variables
        return {
            "metafieldsSet": {
                "metafields": [
                    {
                        "id": "gid://shopify/Metafield/1",
                        "namespace": "drop_rate",
                        "key": "copy_group_size",
                        "type": "number_integer",
                        "value": "2",
                    }
                ],
                "userErrors": [],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    rows = await client.set_product_metafields(
        product_id="gid://shopify/Product/1",
        metafields=[
            {
                "namespace": "drop_rate",
                "key": "copy_group_size",
                "type": "number_integer",
                "value": "2",
            }
        ],
    )

    assert rows[0]["key"] == "copy_group_size"
    assert captured["variables"]["metafields"][0] == {
        "ownerId": "gid://shopify/Product/1",
        "namespace": "drop_rate",
        "key": "copy_group_size",
        "type": "number_integer",
        "value": "2",
    }
    assert "client" not in json.dumps(captured)
    assert "secret" not in json.dumps(captured)
