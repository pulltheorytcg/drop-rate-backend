from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    BulkCostAllocation,
    InventoryPatch,
    PurchaseLotAllocation,
    PurchaseLotCreate,
)


def test_bulk_cost_requires_exact_total() -> None:
    with pytest.raises(ValidationError, match="exactly match"):
        BulkCostAllocation(
            total_cost_minor=1000,
            acquisition_date=date(2026, 9, 23),
            items=[
                {"inventory_id": uuid4(), "version": 1, "acquisition_cost_minor": 499},
                {"inventory_id": uuid4(), "version": 1, "acquisition_cost_minor": 500},
            ],
        )


def test_bulk_cost_rejects_duplicate_inventory_items() -> None:
    item_id = uuid4()
    with pytest.raises(ValidationError, match="only once"):
        BulkCostAllocation(
            total_cost_minor=1000,
            items=[
                {"inventory_id": item_id, "version": 1, "acquisition_cost_minor": 500},
                {"inventory_id": item_id, "version": 1, "acquisition_cost_minor": 500},
            ],
        )


def test_approved_cannot_bypass_approval_endpoint() -> None:
    with pytest.raises(ValidationError):
        InventoryPatch(version=1, status="APPROVED")


def test_grading_fields_are_updated_as_a_pair() -> None:
    with pytest.raises(ValidationError, match="updated together"):
        InventoryPatch(version=1, grading_company="PSA")


def test_purchase_lot_calculates_landed_cost_inputs_without_requiring_allocations() -> None:
    lot = PurchaseLotCreate(
        description="Phantasmal Flames binder",
        source="Private collection",
        purchase_date=date(2026, 9, 20),
        purchase_price_minor=50000,
        fees_minor=1500,
        shipping_minor=500,
    )
    assert lot.purchase_price_minor == 50000
    assert lot.fees_minor == 1500
    assert lot.shipping_minor == 500
    assert lot.currency == "GBP"


def test_purchase_lot_rejects_blank_description() -> None:
    with pytest.raises(ValidationError, match="description cannot be blank"):
        PurchaseLotCreate(description="   ", purchase_price_minor=1000)


def test_purchase_lot_allocation_rejects_duplicate_cards() -> None:
    item_id = uuid4()
    with pytest.raises(ValidationError, match="only once"):
        PurchaseLotAllocation(
            version=1,
            items=[
                {"inventory_id": item_id, "version": 1, "acquisition_cost_minor": 0},
                {"inventory_id": item_id, "version": 1, "acquisition_cost_minor": 1000},
            ],
        )


def test_inventory_unknown_cost_remains_none() -> None:
    patch = InventoryPatch(version=1, acquisition_cost_minor=None)
    assert patch.acquisition_cost_minor is None
