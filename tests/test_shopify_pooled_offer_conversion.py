from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.shopify_pooled_offer_conversion as conversion
from app.shopify_pooled_offer_conversion import _already_pooled


ROOT = Path(__file__).parents[1]
CONVERSION = ROOT / "backend" / "app" / "shopify_pooled_offer_conversion.py"
CLIENT = ROOT / "backend" / "app" / "shopify_client.py"
RUNNER = ROOT / "backend" / "scripts" / "run_shopify_pooled_offer_conversion.py"


def _settings(*, apply: bool = False):
    return SimpleNamespace(
        shopify_pooled_offer_conversion_enabled=True,
        shopify_pooled_offer_conversion_apply=apply,
        shopify_pooled_offer_language_map_json=None,
        shopify_pooled_offer_conversion_limit=100,
        shopify_catalogue_bootstrap_actor_user_id=str(uuid4()),
        shopify_shop_domain="example.myshopify.com",
        shopify_client_id=None,
        shopify_client_secret=None,
        shopify_location_gid=None,
        shopify_publication_gid=None,
        shopify_api_version="2026-07",
    )


@pytest.mark.asyncio
async def test_conversion_dry_run_never_constructs_shopify_client(monkeypatch) -> None:
    async def candidate_ids(*args, **kwargs):
        return []

    async def prepare(*args, **kwargs):
        return [], []

    def plan(_rows):
        return {"offers": []}

    class ForbiddenClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Shopify client must not be constructed during DRY_RUN")

    monkeypatch.setattr(conversion, "_candidate_ids", candidate_ids)
    monkeypatch.setattr(conversion, "_prepare_candidates_read_only", prepare)
    monkeypatch.setattr(conversion, "build_shopify_offer_plan", plan)
    monkeypatch.setattr(conversion, "ShopifyAdminClient", ForbiddenClient)

    result = await conversion.run_shopify_pooled_offer_conversion(
        object(),
        _settings(apply=False),
    )

    assert result["mode"] == "DRY_RUN"
    assert result["selected_pooled_offer_count"] == 0
    assert "results" not in result


@pytest.mark.asyncio
async def test_conversion_apply_requires_complete_shopify_config(monkeypatch) -> None:
    async def candidate_ids(*args, **kwargs):
        return []

    async def prepare(*args, **kwargs):
        return [], []

    monkeypatch.setattr(conversion, "_candidate_ids", candidate_ids)
    monkeypatch.setattr(conversion, "_prepare_candidates_read_only", prepare)
    monkeypatch.setattr(conversion, "build_shopify_offer_plan", lambda _rows: {"offers": []})

    with pytest.raises(RuntimeError, match="APPLY configuration"):
        await conversion.run_shopify_pooled_offer_conversion(
            object(),
            _settings(apply=True),
        )


def test_already_pooled_requires_every_physical_link_to_match_offer() -> None:
    target = {
        "shopify_product_gid": "gid://shopify/Product/1",
        "shopify_variant_gid": "gid://shopify/ProductVariant/2",
        "shopify_inventory_item_gid": "gid://shopify/InventoryItem/3",
        "shopify_location_gid": "gid://shopify/Location/4",
    }
    member = {
        "inventory_id": str(uuid4()),
        "current_listing_key": "offer:fingerprint",
        "current_sku": "DR-ABC",
        "current_product_gid": target["shopify_product_gid"],
        "current_variant_gid": target["shopify_variant_gid"],
        "current_inventory_item_gid": target["shopify_inventory_item_gid"],
        "current_location_gid": target["shopify_location_gid"],
        "sync_state": "PUBLISHED",
    }
    offer = {
        "listing_key": "offer:fingerprint",
        "sku": "DR-ABC",
        "target": target,
        "members": [member, {**member, "inventory_id": str(uuid4())}],
    }
    assert _already_pooled(offer) is True
    offer["members"][1]["current_variant_gid"] = "gid://shopify/ProductVariant/999"
    assert _already_pooled(offer) is False


def test_conversion_freezes_products_before_repoint_and_verifies_before_activation() -> None:
    source = CONVERSION.read_text()
    start = source.index("async def _apply_offer(")
    end = source.index("async def run_shopify_pooled_offer_conversion(", start)
    apply_block = source[start:end]

    freeze = apply_block.index('status="DRAFT"')
    repoint = apply_block.index("await _repoint_links(")
    quantity = apply_block.index("await client.set_inventory_quantity(", repoint)
    verify = apply_block.index("await _verify_anchor_draft(", quantity)
    activate = apply_block.index('status="ACTIVE"', verify)

    assert freeze < repoint < quantity < verify < activate
    assert "reserved_order_reference" in source
    assert "for update of sil,i" in source


def test_discovery_is_read_only_and_apply_preparation_is_scoped_to_selected_offer() -> None:
    source = CONVERSION.read_text()
    discovery_start = source.index("async def _prepare_candidates_read_only(")
    discovery_end = source.index("async def _prepare_offer_for_apply(", discovery_start)
    apply_start = discovery_end
    apply_end = source.index("async def _repoint_links(", apply_start)

    assert "apply=False" in source[discovery_start:discovery_end]
    assert "apply=True" in source[apply_start:apply_end]


def test_shared_variant_update_never_writes_one_members_cost_basis() -> None:
    source = CLIENT.read_text()
    start = source.index("async def update_pooled_offer_variant(")
    end = source.index("async def update_variant_price(", start)
    block = source[start:end]

    assert '"sku": clean_sku' in block
    assert '"tracked": True' in block
    assert '"inventoryPolicy": "DENY"' in block
    assert '"cost"' not in block
    assert "shipping_spec" not in block


def test_conversion_runner_is_standalone_from_fastapi_lifespan() -> None:
    source = RUNNER.read_text()
    assert "run_shopify_pooled_offer_conversion" in source
    assert "create_pool" in source
    assert "POOLED_OFFER_CONVERSION_RESULT=" in source
    assert "FastAPI" not in source
    assert "create_app" not in source
    assert "app.main" not in source
