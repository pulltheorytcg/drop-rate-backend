from pathlib import Path

import pytest

from app.shopify_linked_draft_reconciliation import (
    ReconciliationBlocked,
    parse_collectr_price_override,
    parse_language_map,
    remote_launch_blockers,
    resolve_reconciliation_language,
)
from app.shopify_pipeline import _test_sync_missing


def _row(**overrides):
    row = {
        "game": "Pokemon",
        "set_name": "Phantasmal Flames",
        "language": None,
        "catalogue_language": None,
    }
    row.update(overrides)
    return row


def _launch_item(**overrides):
    item = {
        "sale_intent": "FOR_SALE",
        "status": "APPROVED",
        "identity_confirmed": True,
        "acquisition_cost_minor": 187,
        "product_type": "CARD",
        "grading_company": None,
        "grade": None,
        "condition": "Near Mint",
        "condition_review_status": "NOT_REVIEWED",
        "language": "English",
        "catalogue_language": None,
        "store_price_minor": 100,
        "storage_location_id": "00000000-0000-0000-0000-000000000001",
        "registered_location_id": "00000000-0000-0000-0000-000000000001",
        "registered_location_active": True,
        "market_value_minor": 100,
        "recommended_retail_minor": 100,
    }
    item.update(overrides)
    return item


def _snapshot(**overrides):
    snapshot = {
        "id": "gid://shopify/Product/1",
        "handle": "drop-rate-inv-abc",
        "status": "DRAFT",
        "media": {"nodes": [{"id": "gid://shopify/MediaImage/1"}]},
        "collections": {
            "nodes": [
                {"id": "gid://shopify/Collection/1", "title": "Trading Cards"},
                {"id": "gid://shopify/Collection/2", "title": "Pokémon"},
            ]
        },
        "variants": {
            "nodes": [
                {
                    "id": "gid://shopify/ProductVariant/1",
                    "price": "1.00",
                    "inventoryQuantity": 1,
                    "inventoryItem": {
                        "id": "gid://shopify/InventoryItem/1",
                        "sku": "INV-ABC",
                        "tracked": True,
                    },
                }
            ]
        },
    }
    snapshot.update(overrides)
    return snapshot


def test_language_map_is_explicit_and_normalised():
    mapping = parse_language_map(
        '{"Pokemon|Phantasmal Flames":"English","Pokemon|Ninja Spinner":"Japanese"}'
    )
    assert mapping["pokemon|phantasmal flames"] == "English"
    assert mapping["pokemon|ninja spinner"] == "Japanese"


def test_existing_language_wins_over_set_map():
    mapping = {"pokemon|mega dream ex": "English"}
    assert resolve_reconciliation_language(
        _row(set_name="MEGA Dream ex", language="Japanese"),
        mapping,
    ) == "Japanese"


def test_missing_language_map_fails_closed():
    with pytest.raises(ReconciliationBlocked) as exc:
        resolve_reconciliation_language(_row(set_name="Unknown Set"), {})
    assert exc.value.code == "LANGUAGE_UNRESOLVED"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"Price Override": "40"}, 4000),
        ({"Price Override": "35.00"}, 3500),
        ({"Price Override": "1.235"}, 124),
        ({"Price Override": "0"}, None),
        ({"Price Override": "-1"}, None),
        ({"Price Override": "bad"}, None),
        ({}, None),
    ],
)
def test_collectr_price_override_parser(raw, expected):
    assert parse_collectr_price_override(raw) == expected


def test_low_risk_near_mint_raw_card_passes_without_manual_condition_review():
    assert _test_sync_missing(
        _launch_item(),
        physical_photo_threshold_minor=5000,
    ) == []


def test_graded_card_stays_blocked_without_slab_verification():
    missing = _test_sync_missing(
        _launch_item(
            condition=None,
            grading_company="PSA",
            grade="10",
            condition_review_status="NOT_REVIEWED",
        ),
        physical_photo_threshold_minor=5000,
    )
    assert "graded slab verification" in missing


def test_high_value_raw_card_requires_photo_backed_condition_verification():
    missing = _test_sync_missing(
        _launch_item(
            store_price_minor=6000,
            market_value_minor=6000,
            recommended_retail_minor=6000,
        ),
        physical_photo_threshold_minor=5000,
    )
    assert "photo-backed Near Mint verification" in missing


def test_remote_gate_requires_image():
    blockers = remote_launch_blockers(
        snapshot=_snapshot(media={"nodes": []}),
        product_gid="gid://shopify/Product/1",
        variant_gid="gid://shopify/ProductVariant/1",
        inventory_code="INV-ABC",
        expected_collections={"Trading Cards", "Pokémon"},
    )
    assert "REMOTE_IMAGE_MISSING" in blockers


def test_remote_gate_blocks_sku_and_variant_mismatch():
    blockers = remote_launch_blockers(
        snapshot=_snapshot(
            variants={
                "nodes": [
                    {
                        "id": "gid://shopify/ProductVariant/999",
                        "price": "1.00",
                        "inventoryQuantity": 1,
                        "inventoryItem": {
                            "id": "gid://shopify/InventoryItem/1",
                            "sku": "INV-WRONG",
                            "tracked": True,
                        },
                    }
                ]
            }
        ),
        product_gid="gid://shopify/Product/1",
        variant_gid="gid://shopify/ProductVariant/1",
        inventory_code="INV-ABC",
        expected_collections={"Trading Cards", "Pokémon"},
    )
    assert "REMOTE_VARIANT_ID_MISMATCH" in blockers
    assert "REMOTE_SKU_MISMATCH" in blockers


def test_remote_gate_requires_browse_collections():
    blockers = remote_launch_blockers(
        snapshot=_snapshot(collections={"nodes": [{"title": "Trading Cards"}]}),
        product_gid="gid://shopify/Product/1",
        variant_gid="gid://shopify/ProductVariant/1",
        inventory_code="INV-ABC",
        expected_collections={"Trading Cards", "Pokémon"},
    )
    assert "REMOTE_COLLECTION_MISSING" in blockers


def test_remote_gate_accepts_exact_linked_draft():
    blockers = remote_launch_blockers(
        snapshot=_snapshot(),
        product_gid="gid://shopify/Product/1",
        variant_gid="gid://shopify/ProductVariant/1",
        inventory_code="INV-ABC",
        expected_collections={"Trading Cards", "Pokémon"},
    )
    assert blockers == []


def test_worker_never_creates_duplicate_shopify_products_and_has_compensation():
    source = (
        Path(__file__).parents[1]
        / "backend"
        / "app"
        / "shopify_linked_draft_reconciliation.py"
    ).read_text()

    assert ".create_product(" not in source
    assert "get_product_snapshot(product_gid)" in source
    assert 'set_product_status(product_id=product_gid, status="ACTIVE")' in source
    assert 'set_product_status(product_id=product_gid, status="DRAFT")' in source
    assert "record_shopify_link_published_audit" in source
    assert "insert into tcg.audit_events" not in source
    assert "sync_state='PUBLISHED'" in source
    assert "i.id as inventory_id" in source


def test_worker_is_opt_in_and_dry_run_by_default():
    source = (
        Path(__file__).parents[1]
        / "backend"
        / "app"
        / "settings.py"
    ).read_text()
    assert "shopify_linked_draft_reconciliation_enabled: bool = False" in source
    assert "shopify_linked_draft_reconciliation_apply: bool = False" in source
