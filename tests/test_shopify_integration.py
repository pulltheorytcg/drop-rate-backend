from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path

from app.shopify import (
    INITIAL_WEBHOOK_TOPICS,
    _resource_id,
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


def test_shopify_status_does_not_return_credentials() -> None:
    source = SHOPIFY.read_text()
    status_start = source.index('async def shopify_status(')
    status_end = source.index('@router.post("/probe")')
    status_source = source[status_start:status_end]
    assert '"shopify_access_token"' not in status_source
    assert '"shopify_client_secret"' not in status_source
    assert '"access_token"' not in status_source
    assert '"client_secret"' not in status_source


def test_shopify_admin_client_is_graphql_and_server_side() -> None:
    source = CLIENT.read_text()
    assert "/graphql.json" in source
    assert '"X-Shopify-Access-Token": self._access_token' in source
    assert "productCreate" not in source
    client = ShopifyAdminClient(
        shop_domain="drop-rate.myshopify.com",
        access_token="test-token",
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
