from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import asyncpg
import pytest
from fastapi import HTTPException

import app.shopify_pipeline as pipeline
from app.shopify_client import ShopifyApiError


INVENTORY_ID = UUID("33333333-3333-3333-3333-333333333333")
OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")
EVENT_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture(autouse=True)
def _shopify_settings(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            shopify_location_gid="gid://shopify/Location/40",
            shopify_publication_gid="gid://shopify/Publication/50",
            shopify_shop_domain="drop-rate.myshopify.com",
            media_physical_photo_threshold_minor=5_000,
        ),
    )


def _item() -> dict:
    return {
        "id": str(INVENTORY_ID),
        "inventory_code": "INV-PKM-000001",
        "catalogue_id": "44444444-4444-4444-4444-444444444444",
        "owner_id": str(OWNER_ID),
        "status": "APPROVED",
        "sale_intent": "FOR_SALE",
        "version": 4,
        "identity_confirmed": True,
        "acquisition_cost_minor": 187,
        "store_price_minor": 499,
        "product_type": "CARD",
        "game": "Pokemon",
        "name": "Pikachu",
        "set_name": "Test Set",
        "card_number": "001",
        "variant": "",
        "rarity": "Rare",
        "language": "English",
        "catalogue_language": "English",
        "condition": "Near Mint",
        "condition_review_status": "VERIFIED_NEAR_MINT",
        "grading_company": None,
        "grade": None,
        "seal_status": None,
        "storage_location_id": "55555555-5555-5555-5555-555555555555",
        "registered_location_id": "55555555-5555-5555-5555-555555555555",
        "registered_location_active": True,
    }


def _context(*, existing_link=None) -> dict:
    return {
        "item": _item(),
        "existing_link": existing_link,
        "pooled_membership": None,
        "media_assets": [],
        "shipping_profiles": [],
    }


class FakeConnection:
    def __init__(self, context: dict, *, lock: bool = True, fail_finalize: bool = False):
        self.context = context
        self.lock = lock
        self.fail_finalize = fail_finalize
        self.calls: list[str] = []

    async def fetchval(self, query: str, *args):
        normalized = " ".join(query.split())
        self.calls.append(normalized)
        if "pg_try_advisory_lock" in normalized:
            return self.lock
        if "pg_advisory_unlock" in normalized:
            return True
        if "shopify_publication_context" in normalized:
            return deepcopy(self.context)
        if "save_shopify_inventory_draft" in normalized:
            return {
                "id": "66666666-6666-6666-6666-666666666666",
                "inventory_id": str(INVENTORY_ID),
                "owner_id": str(OWNER_ID),
                "shopify_product_gid": args[8],
                "shopify_variant_gid": args[9],
                "shopify_inventory_item_gid": args[10],
                "sync_state": "DRAFT",
            }
        if "mark_shopify_inventory_published" in normalized:
            if self.fail_finalize:
                raise asyncpg.PostgresError("simulated optimistic conflict")
            return {
                "id": "66666666-6666-6666-6666-666666666666",
                "inventory_id": str(INVENTORY_ID),
                "owner_id": str(OWNER_ID),
                "shopify_product_gid": args[6],
                "shopify_variant_gid": args[7],
                "shopify_inventory_item_gid": args[8],
                "sync_state": "PUBLISHED",
            }
        raise AssertionError(f"Unexpected SQL: {normalized}")


class FakeShopify:
    def __init__(self, *, remote=None, collections_error: Exception | None = None):
        self.remote = remote
        self.collections_error = collections_error
        self.calls: list[str] = []
        self.statuses: list[str] = []

    async def list_collections_by_title(self):
        self.calls.append("list_collections")
        if self.collections_error:
            raise self.collections_error
        return {}

    async def find_product_by_handle(self, handle):
        self.calls.append("find_product")
        return deepcopy(self.remote)

    async def update_product(self, *, product_id, product):
        self.calls.append("update_product")
        return {
            "id": product_id,
            "variants": {"nodes": [{"id": "gid://shopify/ProductVariant/20"}]},
        }

    async def create_product(self, product):
        self.calls.append("create_product")
        return {
            "id": "gid://shopify/Product/10",
            "variants": {"nodes": [{"id": "gid://shopify/ProductVariant/20"}]},
        }

    async def add_product_to_collection(self, **kwargs):
        self.calls.append("collection")

    async def attach_file_to_product(self, **kwargs):
        self.calls.append("media")

    async def update_variant(self, **kwargs):
        self.calls.append("update_variant")
        return {"inventoryItem": {"id": "gid://shopify/InventoryItem/30"}}

    async def activate_inventory(self, **kwargs):
        self.calls.append("activate")

    async def set_inventory_quantity(self, **kwargs):
        self.calls.append("quantity")

    async def get_product_snapshot(self, product_id):
        self.calls.append("snapshot")
        return {"id": product_id}

    async def set_product_status(self, *, product_id, status):
        self.calls.append("set_status")
        self.statuses.append(status)

    async def publish_product(self, **kwargs):
        self.calls.append("publish")

    async def product_published_on_publication(self, **kwargs):
        self.calls.append("published_check")
        return True


def _patch_launch(monkeypatch) -> None:
    plan = {
        "title": "Pikachu 001",
        "descriptionHtml": "<p>Pikachu</p>",
        "statusBeforePublish": "DRAFT",
        "vendor": "Pokémon",
        "productType": "Trading Card",
        "tags": ["Drop Rate"],
        "seo": {"title": "Pikachu", "description": "Pikachu"},
        "metafields": [],
        "requiredCollections": [],
    }
    launch = {
        "complete": True,
        "blockers": [],
        "mediaReadiness": {"shopifyFileIds": []},
        "shippingSpec": {"weight": {"value": 100.0, "unit": "GRAMS"}},
    }
    monkeypatch.setattr(
        pipeline,
        "_launch_completeness",
        lambda *args, **kwargs: (deepcopy(plan), deepcopy(launch)),
    )
    monkeypatch.setattr(
        pipeline,
        "verify_remote_product",
        lambda *args, **kwargs: {"complete": True, "blockers": []},
    )
    async def _copy_group(*args, **kwargs):
        return {"status": "SYNCED"}

    monkeypatch.setattr(
        pipeline,
        "sync_shopify_copy_group_metadata",
        _copy_group,
    )


async def _publish(connection, client):
    return await pipeline.publish_inventory_to_shopify(
        connection,
        inventory_id=INVENTORY_ID,
        owner_id=OWNER_ID,
        expected_version=4,
        actor_user_id=None,
        automation_event_id=EVENT_ID,
        request_id="77777777-7777-7777-7777-777777777777",
        test_mode=False,
        client=client,
    )


@pytest.mark.asyncio
async def test_duplicate_published_event_is_idempotent_without_shopify_write() -> None:
    existing = {
        "sync_state": "PUBLISHED",
        "shopify_product_gid": "gid://shopify/Product/10",
        "shopify_variant_gid": "gid://shopify/ProductVariant/20",
        "shopify_inventory_item_gid": "gid://shopify/InventoryItem/30",
    }
    connection = FakeConnection(_context(existing_link=existing))
    client = FakeShopify()

    result = await _publish(connection, client)

    assert result["status"] == "ALREADY_LINKED"
    assert client.calls == []
    assert any("pg_advisory_unlock" in call for call in connection.calls)


@pytest.mark.asyncio
async def test_concurrent_publication_returns_retryable_503_before_remote_write() -> None:
    connection = FakeConnection(_context(), lock=False)
    client = FakeShopify()

    with pytest.raises(HTTPException) as exc:
        await _publish(connection, client)

    assert exc.value.status_code == 503
    assert exc.value.detail["retryable"] is True
    assert client.calls == []


@pytest.mark.asyncio
async def test_stale_approval_version_fails_before_remote_write() -> None:
    context = _context()
    context["item"]["version"] = 5
    connection = FakeConnection(context)
    client = FakeShopify()

    with pytest.raises(HTTPException) as exc:
        await _publish(connection, client)

    assert exc.value.status_code == 409
    assert exc.value.detail["current_version"] == 5
    assert client.calls == []


@pytest.mark.asyncio
async def test_missing_launch_prerequisites_never_create_remote_product() -> None:
    connection = FakeConnection(_context())
    client = FakeShopify()

    with pytest.raises(HTTPException) as exc:
        await _publish(connection, client)

    assert exc.value.status_code == 422
    assert "create_product" not in client.calls
    assert "update_product" not in client.calls


@pytest.mark.asyncio
async def test_handle_collision_fails_closed(monkeypatch) -> None:
    _patch_launch(monkeypatch)
    client = FakeShopify(
        remote={
            "id": "gid://shopify/Product/999",
            "metafield": {"value": "INV-SOMEONE-ELSE"},
        }
    )
    connection = FakeConnection(_context())

    with pytest.raises(HTTPException) as exc:
        await _publish(connection, client)

    assert exc.value.status_code == 409
    assert "different inventory item" in str(exc.value.detail)
    assert "create_product" not in client.calls
    assert "update_product" not in client.calls


@pytest.mark.asyncio
async def test_partial_remote_product_is_reused_instead_of_created(monkeypatch) -> None:
    _patch_launch(monkeypatch)
    client = FakeShopify(
        remote={
            "id": "gid://shopify/Product/10",
            "metafield": {"value": "INV-PKM-000001"},
        }
    )
    connection = FakeConnection(_context())

    result = await _publish(connection, client)

    assert result["status"] == "PUBLISHED"
    assert "update_product" in client.calls
    assert "create_product" not in client.calls
    assert result["link"]["sync_state"] == "PUBLISHED"


@pytest.mark.asyncio
async def test_retryable_shopify_failure_surfaces_as_gateway_failure() -> None:
    client = FakeShopify(
        collections_error=ShopifyApiError("timeout", retryable=True)
    )
    connection = FakeConnection(_context())

    with pytest.raises(HTTPException) as exc:
        await _publish(connection, client)

    assert exc.value.status_code == 502
    assert exc.value.detail["retryable"] is True
    assert "create_product" not in client.calls


@pytest.mark.asyncio
async def test_final_remote_verification_failure_forces_product_back_to_draft(
    monkeypatch,
) -> None:
    _patch_launch(monkeypatch)
    results = iter([
        {"complete": True, "blockers": []},
        {"complete": False, "blockers": ["remote price"]},
    ])
    monkeypatch.setattr(
        pipeline,
        "verify_remote_product",
        lambda *args, **kwargs: next(results),
    )
    client = FakeShopify()
    connection = FakeConnection(_context())

    with pytest.raises(HTTPException) as exc:
        await _publish(connection, client)

    assert exc.value.status_code == 502
    assert client.statuses == ["ACTIVE", "DRAFT"]
    assert not any("mark_shopify_inventory_published" in call for call in connection.calls)


@pytest.mark.asyncio
async def test_database_finalize_conflict_forces_remote_product_back_to_draft(
    monkeypatch,
) -> None:
    _patch_launch(monkeypatch)
    client = FakeShopify()
    connection = FakeConnection(_context(), fail_finalize=True)

    with pytest.raises(asyncpg.PostgresError):
        await _publish(connection, client)

    assert client.statuses == ["ACTIVE", "DRAFT"]
    assert any("save_shopify_inventory_draft" in call for call in connection.calls)
    assert any("mark_shopify_inventory_published" in call for call in connection.calls)
