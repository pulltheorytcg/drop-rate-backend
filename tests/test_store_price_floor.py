from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.pricing_rules import MIN_STORE_PRICE_MINOR, store_price_floor
from app.schemas import InventoryPatch, ManualInventoryCreate


def test_store_price_floor_is_one_pound() -> None:
    assert MIN_STORE_PRICE_MINOR == 100
    assert store_price_floor(0) == 100
    assert store_price_floor(99) == 100
    assert store_price_floor(100) == 100
    assert store_price_floor(1234) == 1234


def test_store_price_floor_rejects_negative_basis() -> None:
    with pytest.raises(ValueError, match="negative"):
        store_price_floor(-1)


def test_manual_inventory_patch_rejects_store_price_below_floor() -> None:
    with pytest.raises(ValidationError):
        InventoryPatch(version=1, store_price_minor=99)


def test_manual_intake_rejects_store_price_below_floor() -> None:
    with pytest.raises(ValidationError):
        ManualInventoryCreate(
            catalogue_id=uuid4(),
            store_price_minor=99,
        )


def test_database_migration_enforces_store_price_floor() -> None:
    migration = (
        __import__("pathlib").Path(__file__).parents[1]
        / "database"
        / "migrations"
        / "20260925233000_store_price_floor.sql"
    ).read_text()
    assert "inventory_items_store_price_floor_check" in migration
    assert "store_price_minor is null or store_price_minor >= 100" in migration
