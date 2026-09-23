from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import BulkCostAllocation, InventoryPatch


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
