from __future__ import annotations

import base64
import hashlib
import hmac

import pytest
from pathlib import Path

from app.shopify import (
    INITIAL_WEBHOOK_TOPICS,
    SHOPIFY_WEBHOOK_TOPIC_ENUMS,
    _resource_id,
    plan_webhook_registration,
    verify_shopify_hmac,
)
from app.shopify_client import ShopifyAdminClient


ROOT = Path(__file__).parents[1]
SHOPIFY = ROOT / "backend" / "app" / "shopify.py"
CLIENT = ROOT / "backend" / "app" / "shopify_client.py"
MIGRATION = ROOT / "migrations" / "005_shopify_webhook_events.sql"
MAIN = ROOT / "backend" / "app" / "main.py"


def test_shopify_hmac_accepts_exact_raw_body_signature() -> None:
    body = b'{"id":123,"name":"order"}'
    secret = "webhook-secret"
    signature = base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    assert verify_shopify_hmac(body, signature, secret) is True
    assert verify_shopify_hmac(body + b" ", signature, secret) is False
    assert verify_shopify_hmac(body, "wrong", secret) is False


def test_shopify_resource_id_is_metadata_only() -> None:
    assert _resource_id({"id": 123, "email": "private@example.com"}) == "123"
    assert _resource_id({"order_id": "456"}) == "456"
    assert _resource_id({"customer": {"id": 1}}) is None


def test_initial_webhook_topics_cover_order_refund_and_uninstall_boundaries() -> None:
    assert INITIAL_WEBHOOK_TOPICS == {
        "orders/create",
        "orders/paid",
        "orders/cancelled",
        "refunds/create",
        "app/uninstalled",
    }


def test_webhook_ledger_is_rls_protected_and_deduplicated() -> None:
    sql = MIGRATION.read_text().casefold()
    assert "webhook_id text not null unique" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "revoke all on table tcg.shopify_webhook_events from anon, authenticated" in sql
    assert "grant select, insert" in sql
    assert "payload_sha256" in sql


def test_webhook_intake_verifies_hmac_before_parsing_json_and_uses_delivery_id() -> None:
    source = SHOPIFY.read_text()
    hmac_pos = source.index("verify_shopify_hmac(")
    json_pos = source.index("json.loads(raw_body)")
    assert hmac_pos < json_pos
    assert "X-Shopify-Webhook-Id" in source
    assert "on conflict(webhook_id) do nothing" in source
    assert "payload_sha256 = hashlib.sha256(raw_body).hexdigest()" in source
    assert "raw_body" not in MIGRATION.read_text()


def test_unexpected_webhook_failures_are_logged_without_raw_payload() -> None:
    source = SHOPIFY.read_text()
    assert "logger.exception(" in source
    assert '"shopify_webhook_id": webhook_id' in source
    assert '"shopify_topic": topic' in source
    assert '"shopify_resource_id": _resource_id(payload)' in source
    logging_start = source.index("logger.exception(")
    logging_end = source.index("await connection.execute(", logging_start)
    logging_block = source[logging_start:logging_end]
    assert "raw_body" not in logging_block
    assert "payload_sha256" not in logging_block


def test_shopify_status_does_not_return_credentials() -> None:
    source = SHOPIFY.read_text()
    status_start = source.index('async def shopify_status(')
    status_end = source.index('@router.post("/probe", dependencies=[Depends(require_platform_admin_request)])')
    status_source = source[status_start:status_end]
    assert '"shopify_client_id"' not in status_source
    assert '"shopify_client_secret"' not in status_source
    assert '"client_id"' not in status_source
    assert '"client_secret"' not in status_source
    assert '"access_token"' not in status_source


@pytest.mark.asyncio
async def test_shopify_inventory_activation_sets_no_conflicting_quantities() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    captured: dict[str, object] = {}

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        captured["query"] = query
        captured["variables"] = variables
        return {
            "inventoryActivate": {
                "inventoryLevel": {"id": "gid://shopify/InventoryLevel/1"},
                "userErrors": [],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    await client.activate_inventory(
        inventory_item_id="gid://shopify/InventoryItem/123",
        location_id="gid://shopify/Location/456",
        idempotency_key="activate-test",
    )

    variables = captured["variables"]
    assert isinstance(variables, dict)
    assert variables == {
        "inventoryItemId": "gid://shopify/InventoryItem/123",
        "locationId": "gid://shopify/Location/456",
        "idempotencyKey": "activate-test",
    }
    query = str(captured["query"])
    assert "available:" not in query
    assert "onHand:" not in query
    assert "@idempotent" in query


@pytest.mark.asyncio
async def test_shopify_inventory_set_uses_2026_07_quantity_shape() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    captured: dict[str, object] = {}

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        captured["query"] = query
        captured["variables"] = variables
        return {
            "inventorySetQuantities": {
                "inventoryAdjustmentGroup": {"changes": []},
                "userErrors": [],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    await client.set_inventory_quantity(
        inventory_item_id="gid://shopify/InventoryItem/123",
        location_id="gid://shopify/Location/456",
        quantity=1,
        idempotency_key="quantity-test",
    )

    variables = captured["variables"]
    assert isinstance(variables, dict)
    input_data = variables["input"]
    assert isinstance(input_data, dict)
    assert "ignoreCompareQuantity" not in input_data
    quantities = input_data["quantities"]
    assert isinstance(quantities, list)
    assert quantities == [{
        "inventoryItemId": "gid://shopify/InventoryItem/123",
        "locationId": "gid://shopify/Location/456",
        "quantity": 1,
        "changeFromQuantity": None,
    }]
    assert variables["idempotencyKey"] == "quantity-test"
    assert "@idempotent" in str(captured["query"])


@pytest.mark.asyncio
async def test_shopify_collection_titles_paginate_deterministically() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    calls: list[dict | None] = []

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        calls.append(variables)
        after = (variables or {}).get("after")
        if after is None:
            return {
                "collections": {
                    "nodes": [{"id": "gid://shopify/Collection/1", "title": "Pokemon", "handle": "pokemon"}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "next"},
                }
            }
        return {
            "collections": {
                "nodes": [{"id": "gid://shopify/Collection/2", "title": "Trading Cards", "handle": "trading-cards"}],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    assert await client.list_collection_titles() == {"Pokemon", "Trading Cards"}
    assert calls == [
        {"first": 100, "after": None},
        {"first": 100, "after": "next"},
    ]


@pytest.mark.asyncio
async def test_shopify_collection_assignment_uses_exact_collection_and_product_ids() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    captured: dict[str, object] = {}

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        captured["query"] = query
        captured["variables"] = variables
        return {
            "collectionAddProducts": {
                "collection": {
                    "id": "gid://shopify/Collection/1",
                    "title": "Trading Cards",
                },
                "userErrors": [],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    await client.add_product_to_collection(
        collection_id="gid://shopify/Collection/1",
        product_id="gid://shopify/Product/2",
    )
    assert captured["variables"] == {
        "id": "gid://shopify/Collection/1",
        "productIds": ["gid://shopify/Product/2"],
    }
    assert "collectionAddProducts" in str(captured["query"])


@pytest.mark.asyncio
async def test_shopify_media_uses_unified_file_create_and_reference_association() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    calls: list[tuple[str, dict | None]] = []

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        calls.append((query, variables))
        if "fileCreate" in query:
            return {
                "fileCreate": {
                    "files": [{
                        "id": "gid://shopify/MediaImage/1",
                        "fileStatus": "PROCESSING",
                        "alt": "Seel front",
                    }],
                    "userErrors": [],
                }
            }
        return {
            "fileUpdate": {
                "files": [{
                    "id": "gid://shopify/MediaImage/1",
                    "fileStatus": "READY",
                    "alt": "Seel front",
                }],
                "userErrors": [],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    created = await client.create_file_from_url(
        source_url="https://cdn.example/seel-front.jpg",
        alt_text="Seel front",
    )
    assert created["id"] == "gid://shopify/MediaImage/1"
    assert created["fileStatus"] == "PROCESSING"

    await client.attach_file_to_product(
        file_id="gid://shopify/MediaImage/1",
        product_id="gid://shopify/Product/2",
    )
    assert calls[0][1] == {
        "files": [{
            "originalSource": "https://cdn.example/seel-front.jpg",
            "alt": "Seel front",
            "contentType": "IMAGE",
        }]
    }
    assert calls[1][1] == {
        "files": [{
            "id": "gid://shopify/MediaImage/1",
            "referencesToAdd": ["gid://shopify/Product/2"],
        }]
    }


@pytest.mark.asyncio
async def test_shopify_staged_media_upload_is_scope_checked_and_typed() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    calls: list[tuple[str, dict | None]] = []

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        calls.append((query, variables))
        if "DropRateAccessScopes" in query:
            return {
                "currentAppInstallation": {
                    "accessScopes": [
                        {"handle": "read_products"},
                        {"handle": "write_files"},
                    ]
                }
            }
        return {
            "stagedUploadsCreate": {
                "stagedTargets": [{
                    "url": "https://storage.example/upload",
                    "resourceUrl": "https://storage.example/resource/seel-front.jpg",
                    "parameters": [
                        {"name": "key", "value": "staged/key"},
                        {"name": "policy", "value": "signed-policy"},
                    ],
                }],
                "userErrors": [],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    assert await client.access_scopes() == {"read_products", "write_files"}

    target = await client.create_staged_image_upload(
        filename="seel-front.jpg",
        mime_type="image/jpeg",
        file_size=123456,
    )
    assert target == {
        "url": "https://storage.example/upload",
        "resourceUrl": "https://storage.example/resource/seel-front.jpg",
        "parameters": [
            {"name": "key", "value": "staged/key"},
            {"name": "policy", "value": "signed-policy"},
        ],
    }
    assert calls[1][1] == {
        "input": [{
            "filename": "seel-front.jpg",
            "mimeType": "image/jpeg",
            "httpMethod": "POST",
            "resource": "IMAGE",
            "fileSize": "123456",
        }]
    }


@pytest.mark.asyncio
async def test_shopify_product_snapshot_and_publication_are_read_back() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    calls: list[str] = []

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        calls.append(query)
        if "publishedOnPublication" in query:
            return {
                "product": {
                    "id": "gid://shopify/Product/2",
                    "publishedOnPublication": True,
                }
            }
        return {
            "product": {
                "id": "gid://shopify/Product/2",
                "title": "Seel",
                "descriptionHtml": "<p>Seel</p>",
                "handle": "drop-rate-inv-1",
                "status": "ACTIVE",
                "vendor": "Pokémon",
                "productType": "Trading Card",
                "tags": ["TCG"],
                "templateSuffix": None,
                "seo": {"title": "Seel", "description": "Seel"},
                "category": {"id": "gid://shopify/TaxonomyCategory/1"},
                "metafields": {"nodes": []},
                "collections": {"nodes": []},
                "media": {"nodes": []},
                "variants": {
                    "nodes": [{
                        "id": "gid://shopify/ProductVariant/1",
                        "price": "4.99",
                        "inventoryPolicy": "DENY",
                        "inventoryQuantity": 1,
                        "inventoryItem": {
                            "id": "gid://shopify/InventoryItem/1",
                            "sku": "INV-1",
                            "tracked": True,
                            "requiresShipping": True,
                            "measurement": {
                                "weight": {"value": 25.0, "unit": "GRAMS"}
                            },
                        },
                    }]
                },
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    snapshot = await client.get_product_snapshot("gid://shopify/Product/2")
    assert snapshot["variants"]["nodes"][0]["inventoryQuantity"] == 1
    assert await client.product_published_on_publication(
        product_id="gid://shopify/Product/2",
        publication_id="gid://shopify/Publication/3",
    ) is True
    assert any("inventoryQuantity" in query for query in calls)
    assert any("measurement" in query and "weight" in query for query in calls)
    assert any("publishedOnPublication" in query for query in calls)


@pytest.mark.asyncio
async def test_shopify_order_transactions_return_typed_fee_data() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    captured: dict[str, object] = {}

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        captured["query"] = query
        captured["variables"] = variables
        return {
            "order": {
                "id": "gid://shopify/Order/1002",
                "transactions": [{
                    "id": "gid://shopify/OrderTransaction/1",
                    "kind": "SALE",
                    "status": "SUCCESS",
                    "processedAt": "2026-09-25T12:00:00Z",
                    "fees": [{
                        "id": "gid://shopify/TransactionFee/1",
                        "type": "processing_fee",
                        "amount": {"amount": "0.36", "currencyCode": "GBP"},
                    }],
                }],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    rows = await client.get_order_transactions("gid://shopify/Order/1002")
    assert len(rows) == 1
    assert rows[0]["status"] == "SUCCESS"
    assert rows[0]["fees"][0]["type"] == "processing_fee"
    assert rows[0]["fees"][0]["amount"]["amount"] == "0.36"
    assert captured["variables"] == {"id": "gid://shopify/Order/1002"}
    query = str(captured["query"])
    assert "transactions(first: 100)" in query
    assert "fees {" in query
    assert "amount { amount currencyCode }" in query


def test_shopify_admin_client_mints_and_caches_client_credentials_token() -> None:
    source = CLIENT.read_text()
    assert "/admin/oauth/access_token" in source
    assert '"grant_type": "client_credentials"' in source
    assert '"client_id": self._client_id' in source
    assert '"client_secret": self._client_secret' in source
    assert '"X-Shopify-Access-Token": token' in source
    assert "_token_expires_at" in source
    assert "async def create_product" in source
    assert "async def set_inventory_quantity" in source
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    assert client.shop_domain == "drop-rate.myshopify.com"
    assert client.api_version == "2026-07"


def test_shopify_router_is_wired_and_publishing_has_no_mutation_path() -> None:
    main = MAIN.read_text()
    source = SHOPIFY.read_text()
    assert "from .shopify import router as shopify_router" in main
    assert "app.include_router(shopify_router)" in main
    assert 'shopify-settings.js' in main
    assert "productCreate" not in source


def test_shopify_webhook_topic_mapping_matches_expected_api_enums() -> None:
    assert SHOPIFY_WEBHOOK_TOPIC_ENUMS == {
        "orders/create": "ORDERS_CREATE",
        "orders/paid": "ORDERS_PAID",
        "orders/cancelled": "ORDERS_CANCELLED",
        "refunds/create": "REFUNDS_CREATE",
        "app/uninstalled": "APP_UNINSTALLED",
    }


def test_webhook_registration_plan_is_idempotent_for_exact_subscriptions() -> None:
    endpoint = "https://drop-rate.example/api/v1/shopify/webhooks"
    existing = [
        {"id": f"gid://shopify/WebhookSubscription/{index}", "topic": topic, "uri": endpoint}
        for index, topic in enumerate(SHOPIFY_WEBHOOK_TOPIC_ENUMS.values(), start=1)
    ]
    present, missing, conflicts = plan_webhook_registration(existing, endpoint)
    assert len(present) == 5
    assert missing == []
    assert conflicts == []


def test_webhook_registration_plan_creates_only_missing_topics() -> None:
    endpoint = "https://drop-rate.example/api/v1/shopify/webhooks"
    existing = [
        {
            "id": "gid://shopify/WebhookSubscription/1",
            "topic": "ORDERS_PAID",
            "uri": endpoint,
        }
    ]
    present, missing, conflicts = plan_webhook_registration(existing, endpoint)
    assert [item["shopify_topic"] for item in present] == ["ORDERS_PAID"]
    assert {topic for _, topic in missing} == {
        "ORDERS_CREATE",
        "ORDERS_CANCELLED",
        "REFUNDS_CREATE",
        "APP_UNINSTALLED",
    }
    assert conflicts == []


def test_webhook_registration_plan_fails_closed_on_wrong_endpoint() -> None:
    endpoint = "https://drop-rate.example/api/v1/shopify/webhooks"
    existing = [
        {
            "id": "gid://shopify/WebhookSubscription/1",
            "topic": "ORDERS_PAID",
            "uri": "https://old.example/webhooks",
        }
    ]
    present, missing, conflicts = plan_webhook_registration(existing, endpoint)
    assert present == []
    assert ("orders/paid", "ORDERS_PAID") not in missing
    assert conflicts == [
        {
            "topic": "orders/paid",
            "shopify_topic": "ORDERS_PAID",
            "existing": [
                {
                    "subscription_id": "gid://shopify/WebhookSubscription/1",
                    "uri": "https://old.example/webhooks",
                }
            ],
        }
    ]


def test_webhook_registration_plan_fails_closed_on_duplicate_exact_subscription() -> None:
    endpoint = "https://drop-rate.example/api/v1/shopify/webhooks"
    existing = [
        {"id": "gid://shopify/WebhookSubscription/1", "topic": "ORDERS_PAID", "uri": endpoint},
        {"id": "gid://shopify/WebhookSubscription/2", "topic": "ORDERS_PAID", "uri": endpoint},
    ]
    present, missing, conflicts = plan_webhook_registration(existing, endpoint)
    assert present == []
    assert ("orders/paid", "ORDERS_PAID") not in missing
    assert len(conflicts) == 1


def test_webhook_registration_is_founder_scoped_and_reverifies_remote_state() -> None:
    source = SHOPIFY.read_text()
    assert '@router.post("/webhooks/register", dependencies=[Depends(require_platform_admin_request)])' in source
    assert "await require_platform_admin(connection)" in source
    assert "plan_webhook_registration(existing, endpoint)" in source
    assert "verified = await client.list_webhook_subscriptions()" in source
    assert "Shopify webhook registration could not be verified" in source


def test_shopify_client_lists_and_creates_webhook_subscriptions() -> None:
    source = CLIENT.read_text()
    assert "async def list_webhook_subscriptions" in source
    assert "webhookSubscriptions(first: $first, after: $after)" in source
    assert "async def create_webhook_subscription" in source
    assert "webhookSubscriptionCreate" in source


def test_shopify_variant_update_marks_cards_as_physical_shipping_items() -> None:
    source = CLIENT.read_text()
    assert '"requiresShipping": True' in source
    assert '"tracked": True' in source
    assert '"inventoryPolicy": "DENY"' in source
    assert '"measurement"' in source
    assert '"weight"' in source


@pytest.mark.asyncio
async def test_shopify_variant_update_writes_verified_shipping_weight() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    captured: dict[str, object] = {}

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        captured["query"] = query
        captured["variables"] = variables
        return {
            "productVariantsBulkUpdate": {
                "productVariants": [{
                    "id": "gid://shopify/ProductVariant/1",
                    "price": "4.99",
                    "inventoryPolicy": "DENY",
                    "inventoryItem": {
                        "id": "gid://shopify/InventoryItem/1",
                        "sku": "INV-1",
                        "tracked": True,
                    },
                }],
                "userErrors": [],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    await client.update_variant(
        product_id="gid://shopify/Product/1",
        variant_id="gid://shopify/ProductVariant/1",
        price="4.99",
        sku="INV-1",
        cost="1.87",
        shipping_spec={
            "weight": {"value": 25.0, "unit": "GRAMS"},
            "shippingPackageId": None,
        },
    )

    variables = captured["variables"]
    assert isinstance(variables, dict)
    variant = variables["variants"][0]
    inventory_item = variant["inventoryItem"]
    assert inventory_item["requiresShipping"] is True
    assert inventory_item["tracked"] is True
    assert inventory_item["measurement"] == {
        "weight": {"value": 25.0, "unit": "GRAMS"}
    }
    assert "shippingPackageId" not in inventory_item["measurement"]


@pytest.mark.asyncio
async def test_shopify_price_only_update_does_not_touch_inventory_fields() -> None:
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        client_id="client-id",
        client_secret="client-secret",
        api_version="2026-07",
    )
    captured: dict[str, object] = {}

    async def fake_graphql(*, query: str, variables: dict | None = None) -> dict:
        captured["query"] = query
        captured["variables"] = variables
        return {
            "productVariantsBulkUpdate": {
                "productVariants": [{
                    "id": "gid://shopify/ProductVariant/1",
                    "price": "12.34",
                }],
                "userErrors": [],
            }
        }

    client.graphql = fake_graphql  # type: ignore[method-assign]
    result = await client.update_variant_price(
        product_id="gid://shopify/Product/1",
        variant_id="gid://shopify/ProductVariant/1",
        price="12.34",
    )

    assert result["price"] == "12.34"
    variables = captured["variables"]
    assert isinstance(variables, dict)
    variant = variables["variants"][0]
    assert variant == {
        "id": "gid://shopify/ProductVariant/1",
        "price": "12.34",
    }
    assert "inventoryItem" not in variant
    assert "inventoryPolicy" not in variant


def test_webhook_retry_after_cross_channel_failure_is_database_idempotent() -> None:
    source = SHOPIFY.read_text()
    assert "Shopify state committed but eBay cross-channel sync failed" in source
    assert "status='FAILED'" in source
    pipeline = (ROOT / "backend" / "app" / "shopify_pipeline.py").read_text()
    paid = pipeline[pipeline.index("async def _process_paid_order("):pipeline.index("async def _process_cancelled_order(")]
    assert '"action": "ORDER_ALREADY_RECORDED"' in paid
    assert "select id,status from tcg.orders where source='SHOPIFY' and source_reference=$1" in paid


def test_duplicate_webhook_id_with_different_payload_is_rejected() -> None:
    source = SHOPIFY.read_text()
    assert "on conflict(webhook_id) do nothing" in source
    assert 'event["payload_sha256"] != payload_sha256' in source
    assert "Webhook ID was reused with a different payload" in source


def test_processed_duplicate_returns_before_business_logic_replay() -> None:
    source = SHOPIFY.read_text()
    duplicate_check = source.index('if event["status"] in {"PROCESSED", "IGNORED"}:')
    processing = source.index("result = await process_shopify_webhook(")
    assert duplicate_check < processing


def test_webhook_business_logic_is_wrapped_in_database_transaction() -> None:
    source = SHOPIFY.read_text()
    transaction = source.index("async with connection.transaction():")
    processing = source.index("result = await process_shopify_webhook(")
    assert transaction < processing
    assert "except ShopifyProcessingError" in source[processing:]
