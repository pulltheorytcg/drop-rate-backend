import pytest
from pydantic import ValidationError

from app.schemas import InventoryPatch


def test_patch_requires_positive_version():
    with pytest.raises(ValidationError):
        InventoryPatch(version=0, location="A1")


def test_grading_fields_must_be_updated_together():
    with pytest.raises(ValidationError):
        InventoryPatch(version=1, grade="10")


def test_grading_fields_can_be_cleared_together():
    patch = InventoryPatch(version=1, grading_company=None, grade=None)
    assert patch.grading_company is None
    assert patch.grade is None


def test_negative_prices_are_rejected():
    with pytest.raises(ValidationError):
        InventoryPatch(version=1, store_price_minor=-1)
