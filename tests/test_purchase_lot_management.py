from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import PurchaseLotDetach, PurchaseLotPatch


ROOT = Path(__file__).parents[1]
BACKEND = ROOT / "backend" / "app"
STATIC = BACKEND / "static"


def test_purchase_lot_patch_requires_a_change() -> None:
    with pytest.raises(ValidationError, match="At least one"):
        PurchaseLotPatch(version=1)


def test_purchase_lot_patch_rejects_blank_description() -> None:
    with pytest.raises(ValidationError, match="description cannot be blank"):
        PurchaseLotPatch(version=1, description="   ")


def test_purchase_lot_patch_normalises_currency() -> None:
    patch = PurchaseLotPatch(version=1, currency="gbp")
    assert patch.currency == "GBP"


def test_purchase_lot_detach_requires_versions() -> None:
    payload = PurchaseLotDetach(version=3, inventory_version=9)
    assert payload.version == 3
    assert payload.inventory_version == 9


def test_detach_clears_cost_and_reopens_approved_inventory() -> None:
    source = (BACKEND / "purchase_lots.py").read_text()
    assert "acquisition_cost_minor = null" in source
    assert "acquisition_date = null" in source
    assert "status = case when status = 'APPROVED' then 'DRAFT' else status end" in source
    assert "Historical or sold inventory cannot be detached" in source


def test_lot_total_cannot_drop_below_allocated_cost() -> None:
    source = (BACKEND / "purchase_lots.py").read_text()
    assert "Purchase lot total cannot be lower than already allocated cost" in source


def test_purchase_lot_management_asset_is_loaded() -> None:
    html = (STATIC / "index.html").read_text()
    js = (STATIC / "purchase-lot-management.js").read_text()
    assert '/assets/purchase-lot-management.js' in html
    assert "openManagedLot" in js
    assert "detachManagedItem" in js
    assert "addSelectedToManagedLot" in js


def test_value_weighted_allocation_stays_deferred_until_pricing_engine() -> None:
    js = (STATIC / "purchase-lot-management.js").read_text()
    assert 'value="VALUE_WEIGHTED"' not in js
