from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.ebay_sales import (
    EBAY_GB_CCG_SINGLE_CATEGORY_ID,
    _channel_price,
    _condition_payload,
    _inventory_payload,
    _offer_payload,
    _order_line_rows,
    verify_ebay_notification_signature,
)
from app.settings import Settings


ROOT = Path(__file__).parents[1]
EBAY = ROOT / "backend" / "app" / "ebay_sales.py"
EBAY_CLIENT = ROOT / "backend" / "app" / "ebay_sell_client.py"
SHOPIFY = ROOT / "backend" / "app" / "shopify.py"
PIPELINE = ROOT / "backend" / "app" / "shopify_pipeline.py"
API = ROOT / "backend" / "app" / "api.py"
FRONTEND = ROOT / "backend" / "app" / "static" / "app.js"
MAIN = ROOT / "backend" / "app" / "main.py"
EBAY_MIGRATION = ROOT / "database" / "migrations" / "20260926144848_ebay_cross_channel_v1.sql"
EBAY_INDEX_MIGRATION = ROOT / "database" / "migrations" / "20260926144947_index_ebay_cross_channel_fks.sql"


def _base_env(monkeypatch) -> None:
    monkeypatch.setenv("TCG_DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("TCG_AUTH_ISSUER", "https://example.test/auth/v1")
    monkeypatch.setenv("TCG_AUTH_AUDIENCE", "authenticated")
    monkeypatch.setenv("TCG_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://example",
        auth_issuer="https://example.test/auth/v1",
        auth_audience="authenticated",
        jwks_url="https://example.test/jwks",
        supabase_url="https://example.test",
        supabase_publishable_key="sb_publishable_test",
        environment="test",
        db_pool_min=1,
        db_pool_max=2,
        parse_api_key=None,
        ebay_client_id="client",
        ebay_client_secret="secret",
        ebay_marketplace_id="EBAY_GB",
        ebay_user_refresh_token="refresh",
        ebay_payment_policy_id="payment",
        ebay_return_policy_id="return",
        ebay_fulfillment_policy_id="fulfilment",
        ebay_merchant_location_key="drop-rate-london",
        ebay_publish_enabled=True,
        ebay_price_markup_bps=500,
    )


def test_ebay_seller_settings_fail_closed_by_default(monkeypatch) -> None:
    _base_env(monkeypatch)
    for name in (
        "TCG_EBAY_USER_REFRESH_TOKEN",
        "TCG_EBAY_PAYMENT_POLICY_ID",
        "TCG_EBAY_RETURN_POLICY_ID",
        "TCG_EBAY_FULFILLMENT_POLICY_ID",
        "TCG_EBAY_MERCHANT_LOCATION_KEY",
        "TCG_EBAY_NOTIFICATION_ENDPOINT",
        "TCG_EBAY_PUBLISH_ENABLED",
        "TCG_EBAY_PRICE_MARKUP_BPS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.ebay_user_refresh_token is None
    assert settings.ebay_payment_policy_id is None
    assert settings.ebay_return_policy_id is None
    assert settings.ebay_fulfillment_policy_id is None
    assert settings.ebay_merchant_location_key is None
    assert settings.ebay_notification_endpoint is None
    assert settings.ebay_publish_enabled is False
    assert settings.ebay_price_markup_bps == 0


def test_ebay_price_markup_is_deterministic_and_respects_floor() -> None:
    assert _channel_price(100, 0) == 100
    assert _channel_price(100, 500) == 105
    assert _channel_price(12_999, 500) == 13_649
    with pytest.raises(ValueError, match="at least £1"):
        _channel_price(99, 0)


def test_ebay_raw_near_mint_uses_official_condition_descriptor_ids() -> None:
    condition, descriptors = _condition_payload({
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
    })
    assert condition == "USED_VERY_GOOD"
    assert descriptors == [{"name": "40001", "values": ["400010"]}]


def test_ebay_graded_card_uses_grader_grade_and_certificate_descriptors() -> None:
    condition, descriptors = _condition_payload({
        "condition": None,
        "grading_company": "PSA",
        "grade": "10",
        "certificate_number": "12345678",
    })
    assert condition == "LIKE_NEW"
    assert descriptors == [
        {"name": "27501", "values": ["275010"]},
        {"name": "27502", "values": ["275020"]},
        {"name": "27503", "additionalInfo": "12345678"},
    ]


def test_ebay_inventory_payload_is_one_physical_unit_with_front_and_back() -> None:
    payload = _inventory_payload({
        "name": "Charizard",
        "set_name": "Base Set",
        "card_number": "4/102",
        "language": "English",
        "game": "Pokemon",
        "rarity": "Rare Holo",
        "inventory_code": "INV-PKM-000001",
        "condition": "Near Mint",
        "grading_company": None,
        "grade": None,
    }, image_urls=["https://cdn.example/front.jpg", "https://cdn.example/back.jpg"])
    assert payload["availability"]["shipToLocationAvailability"]["quantity"] == 1
    assert payload["product"]["imageUrls"] == [
        "https://cdn.example/front.jpg",
        "https://cdn.example/back.jpg",
    ]
    assert "INV-PKM-000001" in payload["product"]["description"]


def test_ebay_offer_is_fixed_price_gtc_and_policy_driven() -> None:
    payload = _offer_payload(sku="INV-PKM-1", price_minor=1050, settings=_settings())
    assert EBAY_GB_CCG_SINGLE_CATEGORY_ID == "183454"
    assert payload["sku"] == "INV-PKM-1"
    assert payload["marketplaceId"] == "EBAY_GB"
    assert payload["format"] == "FIXED_PRICE"
    assert payload["listingDuration"] == "GTC"
    assert payload["availableQuantity"] == 1
    assert payload["categoryId"] == "183454"
    assert payload["pricingSummary"]["price"] == {"currency": "GBP", "value": "10.50"}
    assert payload["listingPolicies"] == {
        "paymentPolicyId": "payment",
        "fulfillmentPolicyId": "fulfilment",
        "returnPolicyId": "return",
    }


def test_ebay_order_requires_single_physical_unit_per_line() -> None:
    rows = _order_line_rows({
        "lineItems": [{
            "lineItemId": "line-1",
            "legacyItemId": "listing-1",
            "quantity": 1,
            "lineItemCost": {"value": "12.34", "currency": "GBP"},
        }]
    })
    assert rows == [{
        "listing_id": "listing-1",
        "line_item_id": "line-1",
        "quantity": 1,
        "sale_price_minor": 1234,
    }]
    with pytest.raises(ValueError, match="one physical unit"):
        _order_line_rows({
            "lineItems": [{
                "lineItemId": "line-1",
                "legacyItemId": "listing-1",
                "quantity": 2,
                "lineItemCost": {"value": "12.34", "currency": "GBP"},
            }]
        })


def test_ebay_notification_signature_accepts_valid_ec_and_rejects_tampering() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    payload = {
        "metadata": {"topic": "ORDER_CONFIRMATION"},
        "notification": {
            "notificationId": "notification-1",
            "data": {"order": {"orderId": "order-1"}},
        },
    }
    message = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    header = base64.b64encode(json.dumps({
        "kid": "key-1",
        "signature": base64.b64encode(signature).decode("ascii"),
    }, separators=(",", ":")).encode("utf-8")).decode("ascii")
    key_payload = {
        "keyId": "key-1",
        "key": public_pem,
        "algorithm": "EC",
        "digest": "SHA256",
    }
    assert verify_ebay_notification_signature(payload, header, key_payload) is True
    tampered = json.loads(json.dumps(payload))
    tampered["notification"]["data"]["order"]["orderId"] = "order-2"
    assert verify_ebay_notification_signature(tampered, header, key_payload) is False


def test_ebay_sell_client_uses_seller_refresh_token_not_application_token_for_selling() -> None:
    source = EBAY_CLIENT.read_text()
    assert '"grant_type": "refresh_token"' in source
    assert '"refresh_token": self._refresh_token' in source
    assert "/sell/inventory/v1/inventory_item/" in source
    assert "/sell/inventory/v1/offer" in source
    assert "/sell/fulfillment/v1/order/" in source
    assert "raw" not in source.casefold() or "raw payloads" in source.casefold()


def test_single_item_publish_is_fail_closed_and_never_bulk_publishes() -> None:
    source = EBAY.read_text()
    assert '@router.post("/listings/{inventory_id}")' in source
    assert "bulk" not in source[source.index('@router.post("/listings/{inventory_id}")'):]
    assert "TCG_EBAY_PUBLISH_ENABLED" in source
    assert "identity must be confirmed" in source
    assert "approved FRONT + BACK physical photos are required" in source
    assert "photo-backed condition verification is required" in source
    assert "shipping profile is required" in source
    assert "inventory changed while ebay was publishing" in source.casefold()


def test_founder_inventory_surfaces_ebay_status_and_one_click_action() -> None:
    api = API.read_text()
    ui = FRONTEND.read_text()
    assert "eil.state as ebay_state" in api
    assert "eil.listing_id as ebay_listing_id" in api
    assert "List on eBay" in ui
    assert "Retry eBay" in ui
    assert "/api/v1/ebay/listings/" in ui
    assert "eBay Live" in ui


def test_shopify_cross_channel_sync_runs_after_database_transaction_and_is_retryable() -> None:
    source = SHOPIFY.read_text()
    transaction = source.index("async with connection.transaction():")
    sync = source.index("await sync_ebay_after_shopify_result(")
    processed = source.index("set status=$2,processed_at=clock_timestamp()", sync)
    assert transaction < sync < processed
    assert "CROSS_CHANNEL_EBAY_ERROR" in source
    assert "FAILED" in source[source.index("CROSS_CHANNEL_EBAY_ERROR") - 500:processed]


def test_shopify_idempotent_paths_keep_inventory_ids_for_channel_retry() -> None:
    source = PIPELINE.read_text()
    assert '"action": "PENDING_ORDER_ALREADY_RESERVED"' in source
    assert '"action": "ORDER_ALREADY_RECORDED"' in source
    assert '"action": "PENDING_ORDER_RELEASED"' in source
    assert source.count('{"inventory_id": str(row["inventory_id"])}') >= 3


def test_ebay_sale_zeroes_and_drafts_shopify_then_reads_back() -> None:
    source = EBAY.read_text()
    start = source.index("async def _zero_shopify_for_ebay_sale(")
    end = source.index('@router.post("/order-notifications"', start)
    block = source[start:end]
    assert "set_inventory_quantity(" in block
    assert "quantity=0" in block
    assert 'status="DRAFT"' in block
    assert "get_product_snapshot(" in block
    assert 'snapshot.get("status") != "DRAFT"' in block
    assert "quantity != 0" in block


def test_ebay_sale_conflict_is_persisted_after_transaction_rolls_back() -> None:
    source = EBAY.read_text()
    assert "class EbayChannelConflict" in source
    assert "raise EbayChannelConflict" in source
    catch = source.index("except EbayChannelConflict as exc:")
    assert "CHANNEL_CONFLICT_" in source[catch:catch + 1400]
    assert "set state='ERROR'" in source[catch:catch + 1400]


def test_ebay_order_webhook_is_signature_checked_hash_deduped_and_fulfillment_verified() -> None:
    source = EBAY.read_text()
    start = source.index('@router.post("/order-notifications"')
    block = source[start:]
    assert "X-EBAY-SIGNATURE" in block
    assert "verify_ebay_notification_signature" in block
    assert "payload_sha256" in block
    assert "payload mismatch" in block
    assert "client.get_order(order_id)" in block
    assert "paymentMethod" in source
    assert '"EBAY"' in source


def test_ebay_routes_are_registered() -> None:
    source = MAIN.read_text()
    assert "from .ebay_sales import router as ebay_sales_router" in source
    assert "app.include_router(ebay_sales_router)" in source


def test_ebay_cross_channel_schema_is_unique_rls_protected_and_append_only() -> None:
    sql = EBAY_MIGRATION.read_text().casefold()
    index_sql = EBAY_INDEX_MIGRATION.read_text().casefold()
    assert "create table tcg.ebay_inventory_links" in sql
    assert "inventory_id uuid not null unique" in sql
    assert "sku text not null unique" in sql
    assert "offer_id text unique" in sql
    assert "listing_id text unique" in sql
    assert "force row level security" in sql
    assert "revoke all on table tcg.ebay_inventory_links from anon, authenticated" in sql
    assert "revoke delete on table tcg.ebay_inventory_links from tcg_api" in sql
    assert "eBay inventory link identity is immutable once created".casefold() in sql
    assert "create table tcg.ebay_order_item_links" in sql
    assert "order_item_id uuid not null unique" in sql
    assert "unique(ebay_order_id,ebay_line_item_id)" in sql
    assert "revoke update,delete on table tcg.ebay_order_item_links from tcg_api" in sql
    assert "create table tcg.ebay_webhook_events" in sql
    assert "payload_sha256" in sql
    assert "source in ('manual','shopify','ebay')" in sql
    assert "ebay_inventory_links_created_by_user_idx" in index_sql
    assert "ebay_order_item_links_created_by_user_idx" in index_sql
    assert "ebay_order_item_links_inventory_idx" in index_sql
    assert "ebay_order_item_links_internal_order_idx" in index_sql
